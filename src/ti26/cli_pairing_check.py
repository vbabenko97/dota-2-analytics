"""Check the simulator's bracket rules against the only event that has run them.

The spec registered an acceptance criterion for the pairing engine -- reproduce
TI 2025's pairings from actual results -- and it was never discharged. No
producer existed, so `config/ti2026_rules.yaml` carried format values tagged from
citations nobody could open, and the base pairing preference carried no
provenance tag at all. This module discharges what the data can discharge.

It reconstructs TI 2025's Swiss bracket from the committed store and asks four
questions, in descending order of how much they matter:

1. Does the real bracket pair on equal records, and does the round structure
   match `total_rounds` plus a separate elimination round?
2. Do the group constraints hold -- within-group where the rules say so, and
   cross-group in the round the rules say?
3. Inside each record bucket, is the real pairing among those the engine's
   ranking-distance preference would choose?
4. Where the engine had to break a tie at random, how often does the real
   pairing survive?

Question 3 is the one nobody had answered. A NEGATIVE result here would matter
more than a positive one: it would mean every simulated marginal comes from a
bracket that pairs teams differently from the real thing.

This is a DIAGNOSTIC. It has no pass threshold, it gates nothing, and it cannot
alter the shipping card. It also cannot show that TI 2026 will use these rules --
only that TI 2025 did, which is the strongest evidence obtainable offline.
"""

import argparse
import json
import random
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from ti26.data.schema import MapRow
from ti26.data.store import load_rows, open_store
from ti26.observed import load_backtest_truth
from ti26.pairing import perfect_matchings
from ti26.rules import Rules, load_rules
from ti26.tiebreak import rank_teams
from ti26.types import TeamState


class BracketError(ValueError):
    """The reconstructed bracket is not shaped like a Swiss stage."""


def series_of(rows: Sequence[MapRow]) -> list[dict]:
    """Group maps into series, earliest first.

    Keyed on `series_id`, which `observed.py` already verifies is non-null and
    unique per pairing for this event.
    """
    grouped: dict[int, dict] = {}
    for row in rows:
        entry = grouped.setdefault(
            row.series_id,
            {"start": row.start_time, "teams": set(), "map_wins": defaultdict(int), "durations": []},
        )
        entry["start"] = min(entry["start"], row.start_time)
        winner = row.radiant_team_id if row.radiant_win else row.dire_team_id
        loser = row.dire_team_id if row.radiant_win else row.radiant_team_id
        entry["teams"].update((winner, loser))
        entry["map_wins"][winner] += 1
        entry["durations"].append(row.duration)
    out = sorted(grouped.values(), key=lambda e: e["start"])
    for entry in out:
        if len(entry["teams"]) != 2:
            raise BracketError(f"series with {len(entry['teams'])} teams, expected 2")
    return out


def split_rounds(series: Sequence[dict]) -> list[list[dict]]:
    """Cut the series stream into rounds.

    A team cannot play twice in one round, so the first repeat of any team
    starts the next round. This uses only the ordering, never wall-clock gaps,
    which would break on a rescheduled match.
    """
    rounds: list[list[dict]] = []
    current: list[dict] = []
    seen: set[int] = set()
    for entry in series:
        if entry["teams"] & seen:
            rounds.append(current)
            current, seen = [], set()
        current.append(entry)
        seen |= entry["teams"]
    if current:
        rounds.append(current)
    return rounds


def infer_groups(rounds: Sequence[Sequence[dict]], within_rounds: int) -> dict[str, str]:
    """Recover the initial groups from the rounds the rules pair within.

    Connected components over the first `within_rounds` rounds. Two rounds are
    not enough: after round 1 the winners and losers of a group never meet
    again inside it, so components come out at half the true group size.
    """
    adjacency: dict[str, set[str]] = defaultdict(set)
    for rnd in rounds[:within_rounds]:
        for entry in rnd:
            a, b = (str(t) for t in sorted(entry["teams"]))
            adjacency[a].add(b)
            adjacency[b].add(a)
    groups: dict[str, str] = {}
    index = 0
    for team in sorted(adjacency):
        if team in groups:
            continue
        stack, component = [team], set()
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            stack.extend(adjacency[node])
        for node in component:
            groups[node] = chr(ord("A") + index)
        index += 1
    return groups


def _states_before(
    rounds: Sequence[Sequence[dict]], upto: int, groups: dict[str, str]
) -> dict[str, TeamState]:
    """Every team's standing entering round `upto` (1-indexed)."""
    states = {t: TeamState(team_id=t, initial_group=groups[t]) for t in groups}
    for rnd in rounds[: upto - 1]:
        for entry in rnd:
            a, b = (str(t) for t in sorted(entry["teams"]))
            wins = {str(k): v for k, v in entry["map_wins"].items()}
            winner, loser = (a, b) if wins.get(a, 0) > wins.get(b, 0) else (b, a)
            states[winner].series_wins += 1
            states[loser].series_losses += 1
            for team, other in ((a, b), (b, a)):
                states[team].map_wins += wins.get(team, 0)
                states[team].map_losses += wins.get(other, 0)
                states[team].opponents.append(other)
    return states


def _mean_duration(rounds: Sequence[Sequence[dict]], upto: int) -> dict[str, float]:
    total: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    for rnd in rounds[: upto - 1]:
        for entry in rnd:
            for team in (str(t) for t in entry["teams"]):
                total[team] += sum(entry["durations"])
                count[team] += len(entry["durations"])
    return {t: total[t] / count[t] for t in total if count[t]}


def check_round(
    rounds: Sequence[Sequence[dict]],
    round_no: int,
    groups: dict[str, str],
    rules: Rules,
    seeds: Sequence[int],
) -> dict:
    """Compare one real round against what the engine would have allowed."""
    states = _states_before(rounds, round_no, groups)
    durations = _mean_duration(rounds, round_no)
    actual = [tuple(sorted(str(t) for t in e["teams"])) for e in rounds[round_no - 1]]
    playing = {t for pair in actual for t in pair}

    buckets: dict[tuple, list[str]] = defaultdict(list)
    for team in sorted(playing):
        state = states[team]
        key = (
            (state.record, state.initial_group)
            if round_no in rules.within_group_rounds
            else (state.record,)
        )
        buckets[key].append(team)

    equal_record = all(states[a].record == states[b].record for a, b in actual)
    results = []
    for key in sorted(buckets, key=str):
        members = sorted(buckets[key])
        actual_pairs = [p for p in actual if p[0] in members and p[1] in members]
        if len(members) % 2 or len(actual_pairs) * 2 != len(members):
            results.append({"bucket": str(key), "teams": len(members), "status": "not_self_contained"})
            continue
        record = key[0]
        loser_out = record[1] + 1 >= rules.eliminate_at_losses
        maximize_distance = loser_out and round_no in rules.max_distance_elimination_rounds
        agree = 0
        for seed in seeds:
            rng = random.Random(seed)
            # ALL states, not just this round's actives: `swiss.py` ranks the
            # full field, and the opponent-wins criterion needs every team a
            # ranked team has already played, including eliminated ones.
            ranking = rank_teams(list(states.values()), rng, duration_fn=durations.get)
            rank_index = {t: i for i, t in enumerate(ranking)}
            prior = {t: set(states[t].opponents) for t in members}
            allowed = _allowed_matchings(
                members,
                rank_index,
                prior,
                groups,
                cross_group=round_no in rules.cross_group_rounds,
                maximize_distance=maximize_distance,
            )
            if {frozenset(p) for p in actual_pairs} in [
                {frozenset(p) for p in m} for m in allowed
            ]:
                agree += 1
        # Where does the REAL pairing sit in the distance ordering? "Not the
        # engine's choice" says the rule is wrong; this says what it is wrong
        # about, and whether the real bracket prefers the opposite extreme.
        rng = random.Random(seeds[0])
        ranking = rank_teams(list(states.values()), rng, duration_fn=durations.get)
        rank_index = {t: i for i, t in enumerate(ranking)}
        every = list(perfect_matchings(members))
        if round_no in rules.cross_group_rounds:
            every = [m for m in every if all(groups[a] != groups[b] for a, b in m)]
        prior = {t: set(states[t].opponents) for t in members}

        def repeats(matching, _prior=prior):
            return sum(1 for a, b in matching if b in _prior.get(a, set()))

        # The engine filters on repeats BEFORE distance, so distance stats over
        # the unfiltered set describe a choice it never faced. Mirror the order.
        fewest = min(repeats(m) for m in every)
        survivors = [m for m in every if repeats(m) == fewest]
        span = [sum(abs(rank_index[a] - rank_index[b]) for a, b in m) for m in survivors]
        actual_distance = sum(abs(rank_index[a] - rank_index[b]) for a, b in actual_pairs)
        results.append(
            {
                "bucket": str(key),
                "teams": len(members),
                "seeds_agreeing": agree,
                "seeds": len(seeds),
                "status": "always" if agree == len(seeds) else ("never" if agree == 0 else "sometimes"),
                "legal_matchings": len(every),
                "after_repeat_filter": len(survivors),
                "actual_repeats": repeats(actual_pairs),
                "fewest_repeats_possible": fewest,
                "actual_distance": actual_distance,
                "min_distance": min(span),
                "max_distance": max(span),
                "actual_is_min": actual_distance == min(span),
                "actual_is_max": actual_distance == max(span),
                "engine_prefers": "max" if maximize_distance else "min",
                # The competing hypothesis. Conventional Swiss seeds the bucket
                # and pairs the top half against the bottom half -- 1 vs n/2+1,
                # 2 vs n/2+2 -- which deliberately keeps the strongest teams
                # apart and is close to the OPPOSITE of minimising rank
                # distance. If this matches where the engine does not, the rule
                # is wrong in a specific and fixable way rather than unknowable.
                "matches_fold_pairing": _is_fold(members, rank_index, actual_pairs),
            }
        )
    return {
        "round": round_no,
        "series": len(actual),
        "equal_record_pairing": equal_record,
        "within_group": sum(1 for a, b in actual if groups[a] == groups[b]),
        "cross_group": sum(1 for a, b in actual if groups[a] != groups[b]),
        "buckets": results,
    }


def _is_fold(
    members: list[str], rank_index: dict[str, int], actual: list[tuple[str, str]]
) -> bool:
    """Is `actual` the conventional Swiss fold within this bucket?

    Seed the bucket by the field ranking, then pair seed i against seed
    i + n/2. This is the standard bracket-style pairing and is what most Swiss
    formats use inside a record group.
    """
    seeded = sorted(members, key=lambda t: rank_index[t])
    half = len(seeded) // 2
    fold = {frozenset((seeded[i], seeded[i + half])) for i in range(half)}
    return fold == {frozenset(p) for p in actual}


def _allowed_matchings(
    members: list[str],
    rank_index: dict[str, int],
    prior: dict[str, set[str]],
    groups: dict[str, str],
    *,
    cross_group: bool,
    maximize_distance: bool,
) -> list[list[tuple[str, str]]]:
    """The candidate set `choose_pairing` draws from, before its random pick.

    Re-derived here rather than called, because `choose_pairing` returns one
    sample. Every filter below mirrors it in the same order; a divergence
    between the two would make this check meaningless, so
    `tests/test_cli_pairing_check.py` asserts the sampled pairing is always a
    member of this set.
    """
    candidates = list(perfect_matchings(list(members)))
    if cross_group:
        candidates = [m for m in candidates if all(groups[a] != groups[b] for a, b in m)]
    if not candidates:
        raise BracketError(f"no legal matching for {members}")
    def repeats(m):
        return sum(1 for a, b in m if b in prior.get(a, set()))

    fewest = min(repeats(m) for m in candidates)
    candidates = [m for m in candidates if repeats(m) == fewest]
    sign = -1 if maximize_distance else 1

    def distance(m):
        return sum(abs(rank_index[a] - rank_index[b]) for a, b in m)

    best = min(sign * distance(m) for m in candidates)
    return [m for m in candidates if sign * distance(m) == best]


def run(store: str, truth_path: str, rules_path: str, seeds: Sequence[int]) -> dict:
    truth = load_backtest_truth(truth_path)
    rules = load_rules(rules_path)
    rows = [
        r
        for r in load_rows(open_store(store))
        if r.league_id == truth.league_id and r.start_time < truth.swiss_end
    ]
    if not rows:
        raise BracketError(f"no Swiss maps for league {truth.league_id} in {store}")
    rounds = split_rounds(series_of(rows))
    swiss = [r for r in rounds if len(r) > 0][: rules.total_rounds]
    # Rounds 1..max(within_group_rounds) are the within-group ones: round 1 is
    # paired by seeding and is not listed in the config, but it is still inside
    # the group, and omitting it splits every group in half.
    groups = infer_groups(rounds, within_rounds=max(rules.within_group_rounds))
    sizes = {g: sum(1 for v in groups.values() if v == g) for g in set(groups.values())}
    if len(set(sizes.values())) != 1:
        raise BracketError(
            f"inferred groups are not equal-sized: {sizes}. A Swiss stage splits "
            "evenly, so this means the within-group rounds were misidentified "
            "and every group-constrained check below would be measuring nothing."
        )
    per_round = [
        check_round(rounds, n, groups, rules, seeds) for n in range(2, len(swiss) + 1)
    ]
    elimination = rounds[rules.total_rounds :]
    # Self-check: reconstruct every team's FINAL Swiss record and compare with
    # the frozen truth file. If this disagrees, the standings feeding the
    # rankings above are wrong and nothing else in this report means anything.
    final = _states_before(rounds, len(rounds) + 1, groups)
    mismatched = sorted(
        str(team_id)
        for team_id, record in truth.records.items()
        if final[str(team_id)].record != tuple(int(x) for x in record.split("-"))
    )
    return {
        "league_id": truth.league_id,
        "status": "DIAGNOSTIC -- no threshold, gates nothing, cannot alter the card",
        "rounds_observed": len(rounds),
        "swiss_rounds_modelled": rules.total_rounds,
        "elimination_rounds_observed": len(elimination),
        "elimination_series": [len(r) for r in elimination],
        "group_sizes": {
            g: sum(1 for v in groups.values() if v == g) for g in sorted(set(groups.values()))
        },
        "seeds": list(seeds),
        "final_records_match_frozen_truth": not mismatched,
        "final_record_mismatches": mismatched,
        "per_round": per_round,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate bracket rules against TI 2025")
    parser.add_argument("--store", default="data/processed/d2.sqlite")
    parser.add_argument("--truth", default="config/ti2025_backtest.yaml")
    parser.add_argument("--rules", default="config/ti2026_rules.yaml")
    parser.add_argument("--seeds", default="1,2,3,4,5")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    payload = run(args.store, args.truth, args.rules, seeds)
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "pairing_check.json").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
