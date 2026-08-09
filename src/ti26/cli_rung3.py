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
    DAILY_DRIFT_RATING_POINTS,
    LOGIT_PER_ELO,
    OBSERVED_FORM_WINDOW_DAYS,
    STALE_DAYS_THRESHOLD,
    THIN_GAMES_THRESHOLD,
    NullRatingFieldError,
    boundary_proximity,
    deviation_summary,
    observed_recent_form,
    parse_ratings,
    scale_sensitivity_sweep,
    strengths_from_ratings,
)
from ti26.ratings import load_gate_config
from ti26.ratings.elo import EloModel
from ti26.roster import load_aliases
from ti26.rules import load_rules
from ti26.series import map_win_prob
from ti26.teams import UnresolvedTeamError, load_teams, resolve_rosters, team_strengths


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
    try:
        by_id = parse_ratings(rows)
    except NullRatingFieldError as exc:
        name = next((t.name for t in teams if t.team_id == exc.team_id), None)
        who = f"{name} (team_id={exc.team_id})" if name else f"team_id={exc.team_id}"
        raise SystemExit(
            f"{who} has a null {exc.field!r} team_rating field -- refusing to "
            "fabricate a default strength; a card built on a fabricated strength "
            "is worse than no card"
        ) from exc

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

    # team_id travels with the strength: this file is a card input, and the
    # card generator orders teams by configured identity, never by name.
    team_id_by_name = {entry.name: str(entry.team_id) for entry in teams}
    strengths_path = out / "strengths_public.csv"
    with strengths_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["team", "team_id", "strength"])
        for name in sorted(strengths):
            writer.writerow([name, team_id_by_name[name], f"{strengths[name]:.6f}"])

    # --- 3(a). Scale-conversion sensitivity sweep, with a noise floor ---------
    sweep = scale_sensitivity_sweep(
        ratings, rules, [1.0, 0.5, 2.0], n_sims=args.sweep_sims, seed=args.sweep_seed
    )
    (out / "rung3_scale_sensitivity.json").write_text(json.dumps(sweep, indent=2) + "\n")

    # --- 3(b). Elo-ordering sanity anchor (spec V rung 6) ---------------------
    aliases = load_aliases(args.aliases)
    try:
        elo_strengths = _elo_anchor_strengths(args.store, teams, aliases, elo_k)
    except UnresolvedTeamError as exc:
        # An unusable store is one of the registered triggers for reaching rung 3
        # at all, so hitting it here is not an edge case -- it is the scenario.
        # The public ratings are already fetched and written by this point, so
        # the card is still reachable; without this message that fact is buried
        # under a traceback from two modules away, at the worst possible moment.
        raise SystemExit(
            f"the Elo-ordering anchor cannot be fitted from {args.store}: {exc}\n\n"
            f"The public ratings WERE fetched and written to {strengths_path}, so a "
            "card can still be produced without this store:\n\n"
            f"  .venv/bin/python -m ti26.cli --strengths {strengths_path} \\\n"
            f"    --rules {args.rules} --n-sims {args.card_sims} "
            f"--seed {args.card_seed} --out {out}\n\n"
            "That card ships WITHOUT the Elo-ordering anchor and WITHOUT the "
            "observed-form diagnostic. Those are the only two independent checks "
            "on a rating conversion whose divisor this project has never been able "
            "to document, so say plainly wherever it is published that neither ran."
        ) from exc
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

    # --- 3(d). Observed recent form (diagnostic only, never a card input) ------
    # A rating-vs-rating anchor (3(b) above) cannot catch a strength source
    # that shares a correlated error with our own models -- if Elo and this
    # public source were biased the SAME way for a given team, an anchor
    # built from Elo would miss it. This run computes no history-bucket
    # calibration or error split for Elo, so it does not measure whether or
    # how Elo is biased for any team; `is_thin()` below is only a sample-size
    # FLAG (games < THIN_GAMES_THRESHOLD), not a measured bias. A direct read
    # of what each CURRENT roster has actually done recently is independent
    # of the shared-source failure mode either way. See the report's
    # caveats: this never overrides a strength or the card on its own.
    rows_for_form = load_rows(open_store(args.store))
    resolved_rosters = resolve_rosters(rows_for_form, teams, aliases)
    reference_time = max((r.start_time for r in rows_for_form), default=0)
    observed_form = observed_recent_form(rows_for_form, resolved_rosters, strengths, reference_time)
    form_consistent = sum(1 for f in observed_form.values() if f.verdict == "consistent")
    form_above = sum(1 for f in observed_form.values() if f.verdict == "form ABOVE implied")
    form_below = sum(1 for f in observed_form.values() if f.verdict == "form BELOW implied")
    form_no_data = sum(1 for f in observed_form.values() if f.verdict == "no data")

    # --- 3(e). Boundary-proximity diagnostic (day-to-day drift, not gated) ----
    # `team_rating` is a live, continuously updated table: nothing before
    # this reported that the snapshot behind this card is a moving target,
    # or how close any card-boundary-adjacent pair sits to a plausible
    # single-match swap (see FIX D, 2026-08-02 rung-3 review, Finding 4).
    boundary_gaps = boundary_proximity(strengths, ordered)

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
        (
            f"**Ratings snapshot valid as of: {now.isoformat()} (UTC).** Every "
            "strength, rating, and probability in this report is a read of "
            "OpenDota's `team_rating` table at this exact moment. `team_rating` "
            "updates continuously as new matches are recorded, so a re-run even "
            "hours later can report different numbers for the same teams -- see "
            "the boundary-proximity diagnostic near the end of this report for "
            "how much that has already moved a card-adjacent pair in practice."
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

    lines += [
        "",
        "## Observed recent form (diagnostic only)",
        "",
        (
            "Independent of the Elo-ordering anchor above: a rating-vs-rating "
            "comparison cannot catch a source that shares a correlated error "
            "with our own models -- if Elo and this public source were biased "
            "the SAME way for a given team, an anchor built from Elo would "
            "miss it. This run computes no history-bucket calibration or "
            "error split for Elo, so it does not measure whether or how Elo "
            "is biased for any team; the 'thin' flag in the table above is "
            "only a sample-size flag, not a measured bias. This compares each "
            "team's IMPLIED map win rate (the mean of "
            "`map_win_prob` against the other 15 teams, from the strengths "
            "above) against what that team's CURRENT roster has actually done "
            f"over its last {OBSERVED_FORM_WINDOW_DAYS:.0f} days of maps in the "
            "local store, counted by `roster_version_id` so the record follows "
            "the roster across a team_id change. The window is measured back "
            "from the store's own most recent match, never wall-clock."
        ),
        "",
        (
            "**Opposition strength is not controlled.** Each record is against "
            "whatever opponents that team actually played, not against the TI "
            "field. Bottom-half teams tend to play weaker regional circuits, "
            "which alone would make them look better than their implied rate. "
            "This is a diagnostic, never a ranking, and never grounds to "
            "override a rating on its own."
        ),
        "",
        deviation_summary(observed_form, ordered),
        "",
        "| team | strength | implied | observed | n | 95% Wilson CI | verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for name in sorted(strengths, key=lambda t: strengths[t], reverse=True):
        f = observed_form[name]
        if f.n == 0:
            lines.append(f"| {name} | {strengths[name]:.3f} | {f.implied:.3f} | - | 0 | - | no data |")
        else:
            lines.append(
                f"| {name} | {strengths[name]:.3f} | {f.implied:.3f} | {f.rate:.3f} | {f.n} | "
                f"[{f.ci_low:.3f}, {f.ci_high:.3f}] | {f.verdict} |"
            )
    lines += [
        "",
        (
            f"**{form_consistent} consistent, {form_above} form ABOVE implied, "
            f"{form_below} form BELOW implied**"
            + (f", {form_no_data} no data" if form_no_data else "")
            + "."
        ),
        "",
        "## Boundary-proximity diagnostic (day-to-day drift, not gated)",
        "",
        (
            "`team_rating` is live and continuously updated (see the fetch "
            "timestamp above), so the strength gap behind any card boundary can "
            "move between the day a card is generated and the day it is used. "
            "On 2026-08-02, a single head-to-head result moved two teams "
            "(BoomBoys, Team Falcons) by exactly +/-17.74 rating points each "
            "(equal and opposite -- the signature of a head-to-head result) in "
            "a matter of hours, collapsing their strength gap from 0.2189 to "
            "0.0146 logits while they sat across the 4-1/elim_win card "
            "boundary. That is a single past observation, not a general drift "
            "rate -- this run does not recompute it and it is not a forecast "
            "of how much any other pair could move. Every ADJACENT pair below "
            "is flagged only when its CURRENT gap is smaller than that observed "
            f"{DAILY_DRIFT_RATING_POINTS:.2f}-rating-point movement, as a "
            "reference scale for how large a same-day move has been seen to "
            "be. Diagnostic only: reported, not gated on, and never changes a "
            "strength or the card."
        ),
        "",
        "| team A (stronger) | team B (weaker) | gap (logits) | gap (rating points) | flagged |",
        "|---|---|---|---|---|",
    ]
    for gap in boundary_gaps:
        lines.append(
            f"| {gap['team_a']} | {gap['team_b']} | {gap['gap_logit']:.4f} | "
            f"{gap['gap_points']:.2f} | {'YES' if gap['flagged'] else 'no'} |"
        )
    flagged_count = sum(1 for g in boundary_gaps if g["flagged"])
    lines += [
        "",
        f"**{flagged_count} of {len(boundary_gaps)} adjacent pair(s) flagged.**",
    ]
    (out / "rung3_provenance.md").write_text("\n".join(lines) + "\n")

    print(f"rung3: {len(ratings)} teams rated, {len(thin_names)} thin, {len(stale_names)} stale")
    print(f"rung3: Elo rank correlation {rank_corr:.4f}, top-4 overlap {top4_overlap}/4")
    print(f"rung3: scale sweep resolvable={any_resolvable}")
    print(
        f"rung3: observed form {form_consistent} consistent, {form_above} above implied, "
        f"{form_below} below implied"
    )

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
