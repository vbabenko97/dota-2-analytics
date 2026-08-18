"""Validate the five frozen playoff cards and recompute what the model implies.

Registered in `docs/superpowers/specs/2026-08-17-playoff-card-comparison.md`.

DIAGNOSTIC. It scores nothing -- the playoff has not been played -- and alters
no card. It exists so that the freeze can be checked rather than trusted:

1. every frozen card is a COHERENT bracket, i.e. each pick names a team that
   the same card actually advanced into that slot. An incoherent card would
   still look like fourteen plausible team names in a YAML file, and would
   score as a bad forecast rather than as the malformed input it is;
2. the `model_implied_expected` literal on each card still matches what the
   store produces. Those literals are quoted in the registration document, and
   a number in a document that no longer matches the code is exactly the rot
   the project's evidence rule exists to prevent.

It reports the A -> D -> E decomposition because that, not the fourteen-slot
diff, is what the owner's card actually costs on the model's own account.
"""

import argparse
import hashlib
from pathlib import Path

import yaml

from ti26.bracket import SLOTS, slot_distributions
from ti26.cli_card import apply_correction, derive_glicko_calibration_slope
from ti26.data.store import load_rows, open_store
from ti26.ratings import load_gate_config
from ti26.ratings.glicko import GlickoModel
from ti26.roster import RosterIndex, load_aliases
from ti26.series import map_win_prob, series_win_prob
from ti26.teams import load_teams, resolve_rosters, team_strengths

# The literals are quoted in the registration document, so drift beyond this is
# a mismatch to fix rather than to round away. Four decimals are published; half
# a unit in the last place is the most a correct recomputation can differ by.
TOLERANCE = 0.00005


class PlayoffCardError(ValueError):
    """A frozen card that is malformed, incoherent, or no longer matches the model."""


def coherent_picks(card: dict[str, str], seeds: list[str], cross_feed: bool) -> dict[str, str]:
    """Replay `card` through the bracket, proving every pick was reachable.

    Raises if a pick names a team that this same card never advanced into that
    slot -- the one error a hand-transcribed bracket is most likely to contain
    and the one a hit count would silently absorb as a miss.
    """
    from ti26.bracket import resolve

    missing = [slot for slot in SLOTS if slot not in card]
    if missing:
        raise PlayoffCardError(f"missing slots: {missing}")
    extra = sorted(set(card) - set(SLOTS))
    if extra:
        raise PlayoffCardError(f"unknown slots: {extra}")

    def decide(a: str, b: str, slot: str) -> str:
        pick = card[slot]
        if pick == a:
            return a
        if pick == b:
            return b
        raise PlayoffCardError(f"{slot}: picked {pick!r}, but the match is {a!r} vs {b!r}")

    return resolve(seeds, decide, cross_feed)


SOURCE_ROOT = Path("predictions-from-llms")


def verify_source_digest(entry: dict) -> None:
    """For an external card, bind the frozen picks to the raw file's bytes.

    Without this the 14 picks are a transcription nobody can check against the
    document they came from, and the document could be edited afterwards to
    match whatever happened. Cards with no `source_sha256` -- the model's own
    and the owner's -- have no external source and are skipped.
    """
    stated = entry.get("source_sha256")
    if stated is None:
        return
    path = SOURCE_ROOT / f"{entry['id'].split('-', 1)[1]}.md"
    if not path.exists():
        raise PlayoffCardError(f"{entry['id']}: frozen source {path} is missing")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != stated:
        raise PlayoffCardError(
            f"{entry['id']}: {path} hashes to {digest}, not the frozen {stated}"
        )
    if len(raw) != entry["source_bytes"]:
        raise PlayoffCardError(
            f"{entry['id']}: {path} is {len(raw)} bytes, not the frozen {entry['source_bytes']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the frozen playoff cards")
    parser.add_argument("--store", required=True)
    parser.add_argument("--cards", default="data/ti2026_playoff_cards.yaml")
    parser.add_argument("--teams", default="config/ti2026_teams.yaml")
    parser.add_argument("--aliases", default="config/team_aliases.yaml")
    parser.add_argument("--gate-config", default="config/d2_gate.yaml")
    parser.add_argument("--min-train", type=int, default=500)
    args = parser.parse_args(argv)

    frozen = yaml.safe_load(Path(args.cards).read_text())
    if frozen["topology"] != "cross-feed":
        raise PlayoffCardError(
            f"cards are frozen under {frozen['topology']!r}; this producer only knows cross-feed, "
            "which is what the locked client shows"
        )
    seeds = list(frozen["seeds"])
    cards = frozen["cards"]

    teams = load_teams(args.teams)
    aliases = load_aliases(args.aliases)
    gate_config = load_gate_config(args.gate_config)
    rows = load_rows(open_store(args.store))
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

    def prob(a: str, b: str, best_of: int) -> float:
        return series_win_prob(map_win_prob(strengths[a], strengths[b]), best_of)

    dist = slot_distributions(seeds, prob, True)

    print("# Frozen playoff cards")
    print()
    print("**DIAGNOSTIC -- nothing is scored here; the playoff has not been played.**")
    print()
    print(f"Topology **{frozen['topology']}**, provenance `{frozen['topology_provenance']}`.")
    print(f"Registered null: **{frozen['null_expected_hits']:.4f}** / {len(SLOTS)}.")
    print()
    print("| card | role | model-implied E[hits] | recomputed | coherent |")
    print("|---|---|---|---|---|")

    recomputed: dict[str, float] = {}
    for entry in cards:
        picks = entry["picks"]
        coherent_picks(picks, seeds, True)
        verify_source_digest(entry)
        value = sum(dist[slot][picks[slot]] for slot in SLOTS)
        recomputed[entry["id"]] = value
        stated = entry["model_implied_expected"]
        if abs(value - stated) > TOLERANCE:
            raise PlayoffCardError(
                f"{entry['id']}: frozen literal {stated} but the store gives {value:.6f}"
            )
        print(f"| {entry['id']} | {entry['role']} | {stated:.4f} | {value:.4f} | yes |")
    print()

    if {"A-model", "D-override-both", "E-owner"} <= set(recomputed):
        a, d, e = (recomputed[k] for k in ("A-model", "D-override-both", "E-owner"))
        root, cascade = a - d, d - e
        print("## Where the owner's card actually costs")
        print()
        print("```")
        print(f"A -> D   {-root:+.4f}     the two root decisions")
        print(f"D -> E   {-cascade:+.4f}     all six remaining differences combined")
        print(f"A -> E   {-(a - e):+.4f}")
        print("```")
        print()
        print(
            f"**{root / (a - e):.0%} of the cost sits in the two root decisions.** The cascade "
            "into six further slots looks large in a diff and is nearly free in expectation."
        )
        print()

    print("## Stated probabilities on the two root decisions")
    print()
    print("| match | model | reviewer | owner |")
    print("|---|---|---|---|")
    blocks = [
        ("reviewer", frozen.get("external_reviewer_probabilities") or {}),
        ("owner", frozen.get("owner_probabilities") or {}),
    ]
    for label, key, a, b in (
        ("Liquid > Yandex", "liquid_beats_yandex", "Team Liquid", "Team Yandex"),
        ("Iron Wing > Spirit", "iron_wing_beats_spirit", "Iron Wing", "Team Spirit"),
    ):
        model_p = prob(a, b, 3)
        cells = []
        for _name, block in blocks:
            value = block.get(key)
            cells.append("not stated" if value is None else f"{value:.2f}")
        print(f"| {label} | {model_p:.4f} | {cells[0]} | {cells[1]} |")
    print()
    for name, block in blocks:
        if not block.get("elicited"):
            print(f"The {name}'s probabilities are **not stated**.")
            continue
        stated = [
            (key, block[key], prob(a, b, 3))
            for key, a, b in (
                ("liquid_beats_yandex", "Team Liquid", "Team Yandex"),
                ("iron_wing_beats_spirit", "Iron Wing", "Team Spirit"),
            )
            if block.get(key) is not None
        ]
        deltas = ", ".join(f"{value - model_p:+.4f}" for _key, value, model_p in stated)
        print(f"The {name} is {deltas} from the model on those two matches.")
    print()
    print(
        "Both are judgmental forecasts made after the model's numbers were visible: out of "
        "sample with respect to the outcomes, not independent of the model. Two binary "
        "outcomes cannot establish calibration and are not scored as though they could."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
