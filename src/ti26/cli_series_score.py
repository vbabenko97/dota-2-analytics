"""Score the calibrated strengths against every TI 2025 series.

Registered in docs/ti26/2026-08-08-ti2025-series-scoring-spec.md before this
file existed. Read that first: it fixes the window, the orientation, the
metrics, the subgroups and the stop conditions, and it explains why the headline
is all 58 series rather than the 14 playoff series that prompted it.

Every out-of-sample result this project has is card-level. D4 collapses the whole
model output into one integer between 0 and 16, which is one observation. The
same event carries 58 series with known winners, all starting on or after D4's
own training cutoff, so a model trained strictly before it has never seen any of
them. Nothing had ever scored them.

DIAGNOSTIC. No threshold, gates nothing, cannot alter the card. Series-level
skill and card-level skill are different quantities.
"""

import argparse
import json
import math
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from ti26.cli_card import apply_correction, derive_glicko_calibration_slope
from ti26.data.store import load_rows, open_store
from ti26.observed import load_backtest_truth
from ti26.ratings import load_gate_config
from ti26.ratings.glicko import GlickoModel
from ti26.roster import RosterIndex, load_aliases
from ti26.series import map_win_prob, series_win_prob
from ti26.teams import load_teams, resolve_rosters, team_strengths

# The spec fixes these. A run that does not see them is not the registered run.
EXPECTED_TOTAL = 58
EXPECTED_SWISS = 44
EXPECTED_PLAYOFF = 14
MAX_EXCLUSIONS = 2


def reconstruct_series(rows: Sequence, league_id: int) -> list[dict]:
    """Group one league's maps into series, earliest first.

    Keyed on `series_id`, which `observed.py` already verifies is non-null and
    unique per pairing for this event.
    """
    grouped: dict[int, dict] = {}
    for row in rows:
        if row.league_id != league_id:
            continue
        entry = grouped.setdefault(
            row.series_id,
            {"series_id": row.series_id, "start": row.start_time, "maps": 0, "wins": defaultdict(int)},
        )
        entry["start"] = min(entry["start"], row.start_time)
        entry["maps"] += 1
        winner = row.radiant_team_id if row.radiant_win else row.dire_team_id
        loser = row.dire_team_id if row.radiant_win else row.radiant_team_id
        entry["wins"][str(winner)] += 1
        entry.setdefault("teams", set()).update((str(winner), str(loser)))
    out = sorted(grouped.values(), key=lambda e: e["start"])
    for entry in out:
        if len(entry["teams"]) != 2:
            raise SystemExit(
                f"series {entry['series_id']} has {len(entry['teams'])} teams, expected 2"
            )
    return out


def best_of_for(entry: dict) -> int:
    """The series length implied by the maps actually played.

    Read from the data rather than assumed: the population is 57 Bo3 and one
    Bo5 grand final. A race to `need` wins ends as soon as it is decided, so
    the winner's map count IS `need` and `best_of` follows.
    """
    need = max(entry["wins"].values())
    return 2 * need - 1


def score_series(
    entries: Sequence[dict], strengths: dict[str, float], ids_by_team: dict[str, str]
) -> tuple[list[dict], list[dict]]:
    """Predict each series; return the scored rows and the excluded ones.

    Orientation is the lexicographically smaller team id, NOT the model's own
    favourite: predicting for the favourite would make Brier and log loss depend
    on a choice the model makes, which is not what they measure.
    """
    strength_by_id = {ids_by_team[name]: value for name, value in strengths.items() if name in ids_by_team}
    scored: list[dict] = []
    excluded: list[dict] = []
    for entry in entries:
        a, b = sorted(entry["teams"])
        if a not in strength_by_id or b not in strength_by_id:
            excluded.append(
                {
                    "series_id": entry["series_id"],
                    "teams": [a, b],
                    "missing": [t for t in (a, b) if t not in strength_by_id],
                }
            )
            continue
        best_of = best_of_for(entry)
        p_map = map_win_prob(strength_by_id[a], strength_by_id[b])
        p = series_win_prob(p_map, best_of)
        won = entry["wins"].get(a, 0) > entry["wins"].get(b, 0)
        scored.append(
            {
                "series_id": entry["series_id"],
                "start": entry["start"],
                "best_of": best_of,
                "team_a": a,
                "team_b": b,
                "p_a": p,
                "a_won": won,
            }
        )
    return scored, excluded


def _clip(p: float, eps: float = 1e-12) -> float:
    return min(max(p, eps), 1.0 - eps)


def metrics_for(scored: Sequence[dict]) -> dict:
    """Accuracy, Brier, log loss and calibration slope, plus the 0.5 baseline.

    The slope is a logistic refit of outcome on the predicted logit, by
    Newton-Raphson on the two-parameter fit. 1.0 is perfect; below 1.0 is
    overconfidence, which is the failure the design spec named.
    """
    n = len(scored)
    if not n:
        return {"n": 0}
    ps = [_clip(s["p_a"]) for s in scored]
    ys = [1.0 if s["a_won"] else 0.0 for s in scored]

    hits = sum(
        1 for p, y in zip(ps, ys, strict=True) if (p >= 0.5) == (y == 1.0)
    )
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys, strict=True)) / n
    logloss = -sum(
        y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in zip(ps, ys, strict=True)
    ) / n

    xs = [math.log(p / (1 - p)) for p in ps]
    a, b = 0.0, 1.0
    for _ in range(100):
        preds = [_clip(1.0 / (1.0 + math.exp(-(a + b * x)))) for x in xs]
        g0 = sum(pr - y for pr, y in zip(preds, ys, strict=True))
        g1 = sum((pr - y) * x for pr, y, x in zip(preds, ys, xs, strict=True))
        h00 = sum(pr * (1 - pr) for pr in preds)
        h01 = sum(pr * (1 - pr) * x for pr, x in zip(preds, xs, strict=True))
        h11 = sum(pr * (1 - pr) * x * x for pr, x in zip(preds, xs, strict=True))
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-14:
            a = b = float("nan")
            break
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        a, b = a - da, b - db
        if max(abs(da), abs(db)) < 1e-10:
            break

    # The slope's standard error, from the inverse of the same Hessian the fit
    # already builds. NOT in the registered metric list, and added deliberately
    # before any number was written up rather than after: at n=58 a slope can
    # sit far from 1.0 and still be indistinguishable from it, and reporting the
    # point estimate alone would invite exactly that over-reading. It widens the
    # claim rather than narrowing it, and it changes no registered metric.
    slope_se = float("nan")
    if not math.isnan(b):
        preds = [_clip(1.0 / (1.0 + math.exp(-(a + b * x)))) for x in xs]
        h00 = sum(pr * (1 - pr) for pr in preds)
        h01 = sum(pr * (1 - pr) * x for pr, x in zip(preds, xs, strict=True))
        h11 = sum(pr * (1 - pr) * x * x for pr, x in zip(preds, xs, strict=True))
        det = h00 * h11 - h01 * h01
        if abs(det) > 1e-14 and h00 / det > 0:
            slope_se = math.sqrt(h00 / det)

    base_rate = sum(ys) / n
    return {
        "n": n,
        "accuracy": hits / n,
        "brier": brier,
        "log_loss": logloss,
        "calibration_slope": b,
        "calibration_slope_stderr": slope_se,
        "calibration_slope_ci95": [b - 1.96 * slope_se, b + 1.96 * slope_se],
        "calibration_intercept": a,
        "baseline_accuracy_constant_half": 0.5,
        "baseline_brier_constant_half": sum((0.5 - y) ** 2 for y in ys) / n,
        "baseline_log_loss_constant_half": math.log(2.0),
        "orientation_base_rate": base_rate,
    }


def one_sided_p_value(hits: int, n: int) -> float:
    """P(at least this many correct | the model is a coin flip)."""
    return sum(math.comb(n, k) for k in range(hits, n + 1)) / 2.0**n


def render_markdown(payload: dict) -> str:
    lines = [
        "# S1: series-level scoring on TI 2025",
        "",
        ("Registered in `docs/ti26/2026-08-08-ti2025-series-scoring-spec.md` "
        "before this producer existed. **Diagnostic: no threshold, gates "
        "nothing, cannot alter the card.**"),
        "",
        (f"Training window {payload['training_maps']:,} maps over "
        f"{payload['training_window_days']:.1f} days "
        f"({payload['training_window_days'] / 30.44:.1f} months), strictly before "
        f"the {payload['training_cutoff']} cutoff. Calibration slope refit on "
        f"those rows only: {payload['calibration_slope_precutoff']:.4f}."),
        "",
        "| population | n | accuracy | one-sided p | Brier | vs 0.5 | log loss | vs 0.5 | calib. slope |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key, label in (
        ("all", "all TI 2025"),
        ("swiss", "Swiss stage"),
        ("playoff", "playoffs"),
    ):
        m = payload["metrics"][key]
        if not m.get("n"):
            continue
        lines.append(
            f"| {label} | {m['n']} | {m['accuracy']:.3f} | "
            f"{payload['p_values'][key]:.4f} | {m['brier']:.4f} | "
            f"{m['baseline_brier_constant_half']:.4f} | {m['log_loss']:.4f} | "
            f"{m['baseline_log_loss_constant_half']:.4f} | "
            f"{m['calibration_slope']:.4f} |"
        )
    lines += [
        "",
        ("A calibration slope of 1.0 is perfect. Below 1.0 is overconfidence -- "
        "the model saying 65% where the truth is 80% -- which is the specific "
        "failure the design spec named."),
        "",
        ("**The playoff row is the weakest line in this table and was registered "
        "as a subgroup for that reason.** At n=14 the model needs 11 correct to "
        "beat a coin flip at one-sided p<0.05, which a genuinely 65%-accurate "
        "model reaches only 22% of the time. It is reported because it was "
        "named in advance, not because it can settle anything."),
        "",
        f"Excluded for missing strengths: {len(payload['excluded'])}.",
        "",
        ("All 58 series share a patch, a venue, a meta and a field, so they are "
        "not 58 independent draws and the effective sample is smaller than 58 "
        "by an amount this producer does not estimate."),
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Series-level scoring on TI 2025")
    parser.add_argument("--truth", default="config/ti2025_backtest.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--store", default="data/processed/release-deep.sqlite")
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    parser.add_argument("--min-train", type=int, default=500)
    parser.add_argument("--train-from", type=int, default=None)
    parser.add_argument("--swiss-series", type=int, default=EXPECTED_SWISS)
    parser.add_argument("--out", default="reports/series_score")
    args = parser.parse_args(argv)

    truth = load_backtest_truth(args.truth)
    aliases = load_aliases(args.aliases)
    gate_config = load_gate_config(args.gate_config)

    all_rows = load_rows(open_store(args.store))
    if not all_rows:
        raise SystemExit(f"{args.store} is empty; run `python -m ti26.cli_ingest` first")

    train = [r for r in all_rows if r.start_time < truth.training_cutoff]
    if args.train_from is not None:
        train = [r for r in train if r.start_time >= args.train_from]
    if not train:
        raise SystemExit("no maps in the training window")
    if max(r.start_time for r in train) >= truth.training_cutoff:
        raise SystemExit("training rows include a map at or after the cutoff")
    if args.train_from is not None and min(r.start_time for r in train) < args.train_from:
        raise SystemExit("training rows precede --train-from")
    span_days = (max(r.start_time for r in train) - min(r.start_time for r in train)) / 86400

    slope, _intercept = derive_glicko_calibration_slope(
        train, aliases, gate_config.glicko_tau, args.min_train
    )

    model = GlickoModel(tau=gate_config.glicko_tau, roster_index=RosterIndex(aliases))
    for row in train:
        model.update(row)
    model.flush()
    fitted = model.strengths()

    teams = load_teams(args.truth)
    resolved = resolve_rosters(train, teams, aliases)
    raw_strengths, _prior_driven = team_strengths(resolved, fitted)
    strengths = apply_correction(raw_strengths, slope)
    ids_by_team = {entry.name: str(entry.team_id) for entry in teams}

    entries = reconstruct_series(all_rows, truth.league_id)
    if len(entries) != EXPECTED_TOTAL:
        raise SystemExit(
            f"reconstructed {len(entries)} series, spec fixes {EXPECTED_TOTAL}; "
            "the population is not the registered one"
        )
    swiss_entries, playoff_entries = entries[: args.swiss_series], entries[args.swiss_series :]
    if len(playoff_entries) != EXPECTED_PLAYOFF:
        raise SystemExit(
            f"split gives {len(swiss_entries)}/{len(playoff_entries)}, spec fixes "
            f"{EXPECTED_SWISS}/{EXPECTED_PLAYOFF}"
        )

    scored_all, excluded = score_series(entries, strengths, ids_by_team)
    if len(excluded) > MAX_EXCLUSIONS:
        raise SystemExit(
            f"{len(excluded)} series excluded for missing strengths, spec allows "
            f"at most {MAX_EXCLUSIONS}"
        )
    swiss_ids = {e["series_id"] for e in swiss_entries}
    scored_swiss = [s for s in scored_all if s["series_id"] in swiss_ids]
    scored_playoff = [s for s in scored_all if s["series_id"] not in swiss_ids]

    metrics = {
        "all": metrics_for(scored_all),
        "swiss": metrics_for(scored_swiss),
        "playoff": metrics_for(scored_playoff),
    }
    p_values = {
        key: one_sided_p_value(round(m["accuracy"] * m["n"]), m["n"]) if m.get("n") else 1.0
        for key, m in metrics.items()
    }

    payload = {
        "status": "DIAGNOSTIC -- no threshold, gates nothing, cannot alter the card",
        "spec": "docs/ti26/2026-08-08-ti2025-series-scoring-spec.md",
        "store": args.store,
        "league_id": truth.league_id,
        "training_cutoff": truth.training_cutoff,
        "training_from": args.train_from,
        "training_maps": len(train),
        "training_window_days": round(span_days, 1),
        "calibration_slope_precutoff": slope,
        "series_total": len(entries),
        "series_swiss": len(swiss_entries),
        "series_playoff": len(playoff_entries),
        "metrics": metrics,
        "p_values": p_values,
        "excluded": excluded,
        "scored": scored_all,
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "series_score.json").write_text(json.dumps(payload, indent=2, sort_keys=True))
    (out / "series_score.md").write_text(render_markdown(payload))
    for key, label in (("all", "all"), ("swiss", "swiss"), ("playoff", "playoff")):
        m = metrics[key]
        print(
            f"series-score {label}: n={m['n']} accuracy={m['accuracy']:.3f} "
            f"p={p_values[key]:.4f} brier={m['brier']:.4f} "
            f"(0.5 baseline {m['baseline_brier_constant_half']:.4f}) "
            f"slope={m['calibration_slope']:.4f}"
        )
    print(f"series-score: written to {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
