"""Optimal TI 2026 playoff bracket, under both lower-bracket topologies.

Registered in `docs/superpowers/specs/2026-08-16-ti2026-playoff-bracket-prediction.md`
before this producer existed.

It deliberately does NOT choose a topology. The lower-bracket feed edge is
unverified, it changes the optimal slate, and the registered blocking condition
forbids shipping a bracket until the locked client settles it. So both slates
are printed, together with the slots on which they disagree, and the caller
does the one check the code cannot do.

Strengths are built exactly as `cli_card` builds them -- same rolling-backtest
calibration slope, same Glicko fit, same roster resolution -- so this adds no
modelling layer. It reads `observed_recent_form` not at all: that stays a
diagnostic, and promoting it after seeing which group-stage picks it would have
saved is precisely the criterion-after-the-number this project forbids.
"""

import argparse

from ti26.bracket import (
    SLOTS,
    best_bracket,
    coherent_coin_null,
    disagreements,
    slot_distributions,
)
from ti26.cli_card import apply_correction, derive_glicko_calibration_slope
from ti26.data.store import load_rows, open_store
from ti26.ratings import load_gate_config
from ti26.ratings.glicko import GlickoModel
from ti26.roster import RosterIndex, load_aliases
from ti26.series import map_win_prob, series_win_prob
from ti26.teams import load_teams, resolve_rosters, team_strengths

# The four Upper Bracket quarterfinal pairings, in bracket order, as shown by
# the client. Seeds[0] plays seeds[1], seeds[2] plays seeds[3], and so on.
DEFAULT_SEEDS = (
    "Iron Wing",
    "Team Spirit",
    "Team Vision",
    "BoomBoys",
    "Team Liquid",
    "Team Yandex",
    "Nigma Galaxy",
    "Team Falcons",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TI 2026 playoff bracket, both topologies")
    parser.add_argument("--store", required=True)
    parser.add_argument("--teams", default="config/ti2026_teams.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    parser.add_argument("--min-train", type=int, default=500)
    parser.add_argument(
        "--seeds",
        default=",".join(DEFAULT_SEEDS),
        help="eight team names in Upper Bracket quarterfinal order",
    )
    args = parser.parse_args(argv)

    seeds = [name.strip() for name in args.seeds.split(",")]
    if len(seeds) != 8 or len(set(seeds)) != 8:
        raise SystemExit("--seeds needs eight distinct team names")

    teams = load_teams(args.teams)
    aliases = load_aliases(args.aliases)
    gate_config = load_gate_config(args.gate_config)
    rows = load_rows(open_store(args.store))
    if not rows:
        raise SystemExit(f"{args.store} is empty")

    slope, _intercept = derive_glicko_calibration_slope(
        rows, aliases, gate_config.glicko_tau, args.min_train
    )
    model = GlickoModel(tau=gate_config.glicko_tau, roster_index=RosterIndex(aliases))
    for row in rows:
        model.update(row)
    model.flush()
    resolved = resolve_rosters(rows, teams, aliases)
    raw, _prior_driven = team_strengths(resolved, model.strengths())
    strengths = apply_correction(raw, slope)

    missing = [name for name in seeds if name not in strengths]
    if missing:
        raise SystemExit(f"no strength for: {missing}")

    def prob(a: str, b: str, best_of: int) -> float:
        return series_win_prob(map_win_prob(strengths[a], strengths[b]), best_of)

    print("# TI 2026 playoff bracket")
    print()
    print("**The topology is NOT chosen here.** The lower-bracket feed edge is unverified,")
    print("it changes the answer, and the registered blocking condition forbids shipping")
    print("a bracket until the locked client settles it.")
    print()
    print(f"Store: `{args.store}`. Calibration slope measured this run: **{slope:.4f}**.")
    print()
    print("| team | calibrated strength |")
    print("|---|---|")
    for name in sorted(seeds, key=lambda n: -strengths[n]):
        print(f"| {name} | {strengths[name]:+.4f} |")
    print()

    slates = {}
    for cross in (True, False):
        label = "cross-feed" if cross else "direct-feed"
        slate, expected = best_bracket(seeds, prob, cross)
        slates[cross] = slate
        null = coherent_coin_null(seeds, cross)
        dist = slot_distributions(seeds, prob, cross)
        print(f"## {label}")
        print()
        print(
            f"Expected hits **{expected:.4f}** / {len(SLOTS)} "
            f"against a coherent-coin null of **{null:.4f}**."
        )
        print()
        print("| slot | pick | P(pick wins slot) |")
        print("|---|---|---|")
        for slot in SLOTS:
            pick = slate[slot]
            print(f"| {slot} | {pick} | {dist[slot][pick]:.4f} |")
        print()

    differing = disagreements(slates[True], slates[False])
    print("## Where the unverified edge changes the answer")
    print()
    if not differing:
        print("The two slates are identical, so the edge does not block this artifact.")
    else:
        print(f"**{len(differing)} of {len(SLOTS)} picks differ.** The edge must be verified.")
        print()
        print("| slot | cross-feed | direct-feed |")
        print("|---|---|---|")
        for slot in differing:
            print(f"| {slot} | {slates[True][slot]} | {slates[False][slot]} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
