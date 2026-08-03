"""Rung 3: OpenDota's `team_rating` table piped straight into the D1 simulator.

Spec X: when the D2 forecast-value gate fails -- it did, see
`docs/audits/2026-08-02-d2-build-ledger.md` -- public external ratings are
the prescribed strength source. Spec X names "Noxville, datdota"; both are
unreachable from this environment (403 to every access path tried, see
`docs/audits/2026-08-02-rung3-source-research.md`). This CLI uses OpenDota's
own `team_rating` table instead, via the existing `explorer_query` network
seam, and reports the three mitigations the source research calls for: a
scale-conversion sensitivity sweep with a noise floor, an Elo-ordering
sanity anchor, and printed implied map win probabilities -- because a public
rating snapshot cannot be backtested the way Elo/Glicko were.
"""

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from ti26.cli import main as cli_main
from ti26.data.opendota import TEAM_RATING_QUERY, explorer_query, http_transport
from ti26.data.store import load_rows, open_store
from ti26.public_ratings import (
    LOGIT_PER_ELO,
    STALE_DAYS_THRESHOLD,
    THIN_GAMES_THRESHOLD,
    parse_ratings,
    scale_sensitivity_sweep,
    strengths_from_ratings,
)
from ti26.ratings import load_gate_config
from ti26.ratings.elo import EloModel
from ti26.roster import load_aliases
from ti26.rules import load_rules
from ti26.series import map_win_prob
from ti26.teams import load_teams, resolve_rosters, team_strengths


def _rank_correlation(a: dict[str, float], b: dict[str, float]) -> float:
    """Spearman rank correlation over the names common to both mappings.

    Used only as a sanity anchor (spec V rung 6): Elo is disqualified as a
    strength SOURCE (it lost to the constant floor, see the D2 ledger) but
    its ORDERING is still a valid consistency check -- it would catch a
    sign error or a wildly wrong scale in the rung-3 conversion.
    """
    names = sorted(set(a) & set(b))
    n = len(names)
    if n < 2:
        return float("nan")
    rank_a = {name: i for i, name in enumerate(sorted(names, key=lambda t: a[t]))}
    rank_b = {name: i for i, name in enumerate(sorted(names, key=lambda t: b[t]))}
    d2_sum = sum((rank_a[name] - rank_b[name]) ** 2 for name in names)
    return 1.0 - (6.0 * d2_sum) / (n * (n**2 - 1))


def _top_n(strengths: dict[str, float], n: int) -> set[str]:
    return set(sorted(strengths, key=lambda t: strengths[t], reverse=True)[:n])


def _elo_anchor_strengths(store_path: str, teams, aliases, elo_k: float) -> dict[str, float]:
    """Fit Elo over the FULL local store (no folds) and resolve to team names.

    Same method `cli_d2`'s final fit uses -- a single pass over every row,
    then `resolve_rosters`/`team_strengths` to bridge roster-hash space to
    the card's team names. This is a consistency ANCHOR only: Elo already
    failed the spec V floor gate, so its strengths are never a candidate
    card input here, only an independent ordering to compare against.
    """
    rows = load_rows(open_store(store_path))
    model = EloModel(k=elo_k)
    for row in rows:
        model.update(row)
    fitted = model.strengths()
    resolved = resolve_rosters(rows, teams, aliases)
    strengths, _prior_driven = team_strengths(resolved, fitted)
    return strengths


def main(argv: list[str] | None = None, transport=http_transport) -> int:
    parser = argparse.ArgumentParser(
        description="D3 rung 3: OpenDota team_rating fallback strength source"
    )
    parser.add_argument("--teams", default="config/ti2026_teams.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    # No numeric default: the Elo anchor is only a valid comparison against
    # D2's backtest if it uses the SAME k that backtest used, and that value
    # lives in the gate config. A hardcoded default here would match today
    # and drift silently the moment the config changed.
    parser.add_argument("--elo-k", type=float, default=None)
    parser.add_argument("--card-sims", type=int, default=250_000)
    parser.add_argument("--card-seed", type=int, default=1)
    parser.add_argument("--sweep-sims", type=int, default=20_000)
    parser.add_argument("--sweep-seed", type=int, default=0)
    parser.add_argument("--out", default="reports")
    args = parser.parse_args(argv)

    teams = load_teams(args.teams)
    rules = load_rules(args.rules)
    elo_k = args.elo_k if args.elo_k is not None else load_gate_config(args.gate_config).elo_k
    if len(teams) != rules.n_teams:
        raise SystemExit(
            f"{args.teams} lists {len(teams)} teams but the rules require {rules.n_teams}"
        )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # --- 1. Fetch public ratings, current configured team_id only ------------
    # Controller ruling: look up each team's rating by its CURRENT configured
    # team_id, as-is. Do not follow rosters back across team_ids, and do not
    # blend across them -- layering our own transform onto a source we
    # cannot validate reintroduces the unverifiable-transform risk rung 3
    # exists to avoid.
    team_ids = [t.team_id for t in teams]
    sql = TEAM_RATING_QUERY.format(team_ids=",".join(str(i) for i in team_ids))
    rows = explorer_query(sql, transport)
    by_id = parse_ratings(rows)

    missing = [t for t in teams if t.team_id not in by_id]
    if missing:
        names = ", ".join(f"{t.name} (team_id={t.team_id})" for t in missing)
        raise SystemExit(
            f"{len(missing)} of {len(teams)} configured teams have no team_rating row: "
            f"{names} -- refusing to fabricate a default strength; a card built on a "
            "fabricated strength is worse than no card"
        )

    ratings = {t.name: by_id[t.team_id] for t in teams}
    now = datetime.now(UTC)

    # --- 2. Convert to strengths, write the card's direct input --------------
    strengths = strengths_from_ratings(ratings)

    strengths_path = out / "strengths_public.csv"
    with strengths_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["team", "strength"])
        for name in sorted(strengths):
            writer.writerow([name, f"{strengths[name]:.6f}"])

    # --- 3(a). Scale-conversion sensitivity sweep, with a noise floor ---------
    sweep = scale_sensitivity_sweep(
        ratings, rules, [1.0, 0.5, 2.0], n_sims=args.sweep_sims, seed=args.sweep_seed
    )
    (out / "rung3_scale_sensitivity.json").write_text(json.dumps(sweep, indent=2) + "\n")

    # --- 3(b). Elo-ordering sanity anchor (spec V rung 6) ---------------------
    aliases = load_aliases(args.aliases)
    elo_strengths = _elo_anchor_strengths(args.store, teams, aliases, elo_k)
    rank_corr = _rank_correlation(strengths, elo_strengths)
    top4_public = _top_n(strengths, 4)
    top4_elo = _top_n(elo_strengths, 4)
    top4_overlap = len(top4_public & top4_elo)

    # --- 3(c). Implied map win probabilities -----------------------------------
    ordered = sorted(strengths, key=lambda t: strengths[t], reverse=True)
    strongest, weakest = ordered[0], ordered[-1]
    mid = len(ordered) // 2
    mid_a, mid_b = ordered[mid - 1], ordered[mid]
    mid_c, mid_d = ordered[mid], ordered[min(mid + 1, len(ordered) - 1)]
    implied = [
        (strongest, weakest, map_win_prob(strengths[strongest], strengths[weakest])),
        (mid_a, mid_b, map_win_prob(strengths[mid_a], strengths[mid_b])),
        (mid_c, mid_d, map_win_prob(strengths[mid_c], strengths[mid_d])),
    ]

    # --- 4. Provenance report ---------------------------------------------------
    lines = [
        "# Rung 3 provenance: OpenDota `team_rating` fallback",
        "",
        (
            "Spec X names \"Noxville, datdota\" for rung 3. Both are unreachable from "
            "this environment: HTTP 403 to every access path tried (browser-emulating "
            "fetch, curl under multiple User-Agents, and the Internet Archive's own "
            "crawler), and Noxville's public dataset has been dead since 2020-12-29. "
            "See `docs/audits/2026-08-02-rung3-source-research.md` for the full survey. "
            "This report uses OpenDota's own `team_rating` table instead, via the "
            "existing `explorer_query` network seam -- no new network path."
        ),
        "",
        (
            "**Scale caveat, stated plainly:** `team_rating.rating` is empirically "
            f"Elo-shaped but OpenDota documents NO divisor for this table. The "
            f"conversion used here, `logit_per_elo = math.log(10) / 400 = "
            f"{LOGIT_PER_ELO:.8f}`, is INFERRED by convention (it matches this repo's "
            "own `EloModel.strengths()`), not a documented constant. Every number "
            "below derived from it inherits that inference."
        ),
        "",
        "## Per-team ratings",
        "",
        (
            f"Thin-history threshold: under {THIN_GAMES_THRESHOLD} games. "
            f"Stale threshold: {STALE_DAYS_THRESHOLD:.0f}+ days since the last recorded match."
        ),
        "",
        "| team | team_id | rating | games (W/L) | days stale | thin | stale |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in sorted(ratings):
        r = ratings[name]
        lines.append(
            f"| {name} | {r.team_id} | {r.rating:.2f} | {r.games} ({r.wins}/{r.losses}) | "
            f"{r.stale_days(now):.1f} | {'YES' if r.is_thin() else 'no'} | "
            f"{'YES' if r.is_stale(now) else 'no'} |"
        )
    thin_names = sorted(n for n, r in ratings.items() if r.is_thin())
    stale_names = sorted(n for n, r in ratings.items() if r.is_stale(now))
    lines += [
        "",
        f"**{len(thin_names)} thin team(s):** " + (", ".join(thin_names) if thin_names else "none"),
        f"**{len(stale_names)} stale team(s):** " + (", ".join(stale_names) if stale_names else "none"),
        "",
        "## Scale-conversion sensitivity sweep",
        "",
        (
            "Varies the inferred `/400` divisor at 0.5x, 1.0x (baseline) and 2.0x and "
            "measures how far the simulated card moves. `noise_floor` is the max of "
            "three pairwise max-abs-deltas among baseline reruns at seeds "
            f"{args.sweep_seed}, {args.sweep_seed + 1}, {args.sweep_seed + 2} -- a "
            "delta at or below it is NOT evidence the divisor moved anything, only "
            "what resampling noise looks like at this sample size."
        ),
        "",
        "| divisor | max abs delta vs 1.0x baseline | noise floor | resolvable |",
        "|---|---|---|---|",
    ]
    for entry in sweep:
        lines.append(
            f"| {entry['divisor']:.0f} | {entry['max_abs_delta']:.5f} | "
            f"{entry['noise_floor']:.5f} | {entry['resolvable']} |"
        )
    any_resolvable = any(e["resolvable"] for e in sweep if not e["is_baseline"])
    lines += [
        "",
        (
            "**The scale factor IS resolvably distinguishable from noise at these "
            "sample sizes.**" if any_resolvable else
            "**The scale factor is NOT resolvably distinguishable from noise at these "
            "sample sizes** -- every non-baseline delta fell at or below the noise "
            "floor."
        ),
        "",
        "## Elo-ordering sanity anchor (spec V rung 6)",
        "",
        (
            "Elo is disqualified as a strength SOURCE (it lost to the constant floor "
            "-- see `docs/audits/2026-08-02-d2-build-ledger.md`) but its ORDERING is "
            "still a valid consistency check: it would catch a sign error or a wildly "
            "wrong scale in the conversion above."
        ),
        "",
        (
            f"Anchor fitted with `elo_k={elo_k}`, read from the gate config so it "
            "matches the k D2's backtest actually used. A different k here would "
            "make this comparison an anchor against a model we never evaluated."
        ),
        "",
        (
            f"Spearman rank correlation (public ratings vs Elo, same 16 teams): "
            f"**{rank_corr:.4f}**."
        ),
        "",
        f"Top-4 by public rating: {', '.join(sorted(top4_public))}.",
        f"Top-4 by Elo: {', '.join(sorted(top4_elo))}.",
        f"Top-4 overlap: **{top4_overlap} of 4**.",
        "",
        "## Implied map win probabilities",
        "",
        "Printed so a human can judge plausibility before publishing.",
        "",
        "| favorite | underdog | P(favorite wins map) |",
        "|---|---|---|",
    ]
    for a, b, p in implied:
        lines.append(f"| {a} | {b} | {p:.4f} |")
    (out / "rung3_provenance.md").write_text("\n".join(lines) + "\n")

    print(f"rung3: {len(ratings)} teams rated, {len(thin_names)} thin, {len(stale_names)} stale")
    print(f"rung3: Elo rank correlation {rank_corr:.4f}, top-4 overlap {top4_overlap}/4")
    print(f"rung3: scale sweep resolvable={any_resolvable}")

    # --- 5. Card, from D1's generator fed OUR rung-3 strengths ------------------
    card_rc = cli_main(
        [
            "--strengths", str(strengths_path),
            "--rules", args.rules,
            "--n-sims", str(args.card_sims),
            "--seed", str(args.card_seed),
            "--out", str(out),
        ]
    )
    if card_rc != 0:
        raise SystemExit(f"card generation failed with exit code {card_rc}")
    print(f"rung3: card written to {out}/recommended_card.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
