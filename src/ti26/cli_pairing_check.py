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
from ti26.elimination import pair_elimination
from ti26.observed import load_backtest_truth
from ti26.pairing import perfect_matchings
from ti26.rules import Rules, load_rules
from ti26.tiebreak import TIEBREAK_ORDER, rank_teams
from ti26.types import TeamState

# The event this producer replays. It is the only event that has ever run a
# 16-team Swiss stage in this format, and TI 2026 has not been played.
EVENT_YEAR = 2025

# Which tournament's rule each check models. These are not all the same year,
# and that is the single most misreadable thing about this report: TI 2026's
# published rules replaced TI 2025's elimination round outright, so a `false`
# in `engine_reproduces_the_real_bracket` is a statement about a rule the
# shipping engine no longer uses. See `rule_year` in the payload.
SWISS_PAIRING_RULE_YEAR = 2025
ELIMINATION_RULE_YEAR = 2025
TIEBREAK_ORDER_YEAR = 2026

# A documented, external, non-rule cause of a difference between the real
# bracket and the engine's. Recorded so a reader cannot mistake it for evidence
# about the rule. It carries no numbers: the arithmetic that once supported it
# was measured on a superseded ranking, and the current figures are computed
# below and reported beside it rather than asserted here.
KNOWN_DEVIATIONS = (
    {
        "id": "ti2025_two_series_per_day",
        "applies_to": "elimination_round",
        "announced": False,
        "what": (
            "Teams were notified on 6 September 2025 of a constraint that did "
            "not previously exist -- no more than two series per day. It forced "
            "HEROIC onto Yakult; the rule-following pairing was HEROIC vs Spirit "
            "and Falcons vs Yakult."
        ),
        "why_it_matters": (
            "An organiser constraint absent from the rules, unannounced, and "
            "applied mid-event is not forecastable. A difference it caused is "
            "not evidence that the pairing rule is wrong."
        ),
        "source": "docs/ti26/2026-08-08-published-format-rules.md",
    },
)


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
    """Each team's mean map duration over the rounds before `upto`.

    Average Game Duration is the published sixth ranking criterion, so a block
    still tied after five needs a duration source or `rank_teams` refuses to
    rank it. Simulation supplies a fitted `DurationResolver`; this producer is
    replaying a real event and has the real durations in the store, so it uses
    them. Substituting the fitted model here would rank the actual bracket by
    sampled numbers.

    Deleted on 2026-08-08 alongside the criterion itself, and restored on
    2026-08-09 with it. In between, this producer raised
    `DurationUnavailableError` on the TI 2025 store: three teams tie through
    five criteria in that bracket, and nothing ran it.
    """
    total: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    for rnd in rounds[: upto - 1]:
        for entry in rnd:
            for team in (str(t) for t in entry["teams"]):
                total[team] += sum(entry["durations"])
                count[team] += len(entry["durations"])
    return {t: total[t] / count[t] for t in total if count[t]}


def check_elimination_pairing(
    rounds: Sequence[Sequence[dict]],
    groups: dict[str, str],
    rules: Rules,
    seeds: Sequence[int],
) -> dict:
    """Does the real elimination round pair at MAXIMUM ranking distance?

    Added 2026-08-08. The published rule -- 3-2 against 2-3, distance in
    ranking maximised -- was implemented on that date, replacing a model in
    which the 3-2 team chose its opponent. That model was never checked against
    the one event that has run this format, and neither was its replacement.
    This checks it.

    Distance is measured on SEED WITHIN EACH RECORD CLASS and summed over the
    matching, which is how the tournament's own bracket analysis scored it.
    Overall ranking position cannot be the metric: every 3-2 team outranks
    every 2-3 team, so the total is invariant and the rule would say nothing.

    Reports the real bracket's score against the best reachable score, where
    reachable means "without a rematch" -- on TI 2025 the unconstrained optimum
    required teams to meet twice and was not available.
    """
    # Carried by every return, including the ones that check nothing: which
    # rule was being checked is a property of the check, not of its outcome,
    # and a report that bailed out still has to say what it would have tested.
    year = {"rule_year": ELIMINATION_RULE_YEAR}

    elimination = [r for r in rounds[rules.total_rounds :] if r]
    if len(elimination) != 1:
        return {**year, "status": "not_a_single_elimination_round", "rounds": len(elimination)}

    states = _states_before(rounds, rules.total_rounds + 1, groups)
    durations = _mean_duration(rounds, rules.total_rounds + 1)
    actual = [tuple(sorted(str(t) for t in e["teams"])) for e in elimination[0]]

    top = max(states[t].record for pair in actual for t in pair)
    bottom = min(states[t].record for pair in actual for t in pair)
    if top == bottom:
        return {**year, "status": "elimination_round_is_not_two_record_classes"}

    out: dict = {
        **year,
        "status": "checked",
        "higher_record": f"{top[0]}-{top[1]}",
        "lower_record": f"{bottom[0]}-{bottom[1]}",
        "series": len(actual),
        "seeds": list(seeds),
    }
    real_scores: list[int] = []
    reachable: list[int] = []
    unconstrained: list[int] = []
    engine_agrees: list[bool] = []
    shared_pairs: list[int] = []
    only_real: list[list] = []
    only_engine: list[list] = []
    for seed in seeds:
        ranking = rank_teams(
            list(states.values()), random.Random(seed), duration_fn=durations.get
        )
        order = {t: i for i, t in enumerate(ranking)}
        higher = sorted((t for t in states if states[t].record == top), key=order.get)
        lower = sorted((t for t in states if states[t].record == bottom), key=order.get)
        seat = {t: i for i, t in enumerate(higher)} | {t: i for i, t in enumerate(lower)}
        prior = {t: set(states[t].opponents) for t in higher}

        real_scores.append(sum(abs(seat[a] - seat[b]) for a, b in actual))
        engine = pair_elimination(higher, lower, prior, random.Random(seed), maximize=True)
        reachable.append(sum(abs(seat[a] - seat[b]) for a, b in engine))
        unconstrained.append(
            sum(
                abs(seat[a] - seat[b])
                for a, b in pair_elimination(higher, lower, {}, random.Random(seed))
            )
        )
        engine_set = {frozenset(p) for p in engine}
        actual_set = {frozenset(p) for p in actual}
        shared = engine_set & actual_set
        engine_agrees.append(len(shared) == len(actual))
        shared_pairs.append(len(shared))
        # Which pairs differ, not just how many. A deviation with a documented
        # external cause names specific teams, so a reader has to be able to
        # check that claim against the pairs rather than against a count.
        only_real.append(sorted(sorted(pair) for pair in actual_set - engine_set))
        only_engine.append(sorted(sorted(pair) for pair in engine_set - actual_set))

    out["real_bracket_distance"] = real_scores
    out["best_reachable_distance"] = reachable
    out["best_unconstrained_distance"] = unconstrained
    out["engine_reproduces_the_real_bracket"] = engine_agrees
    out["pairs_shared_with_engine"] = shared_pairs
    out["pairs_only_in_real_bracket"] = only_real
    out["pairs_only_in_engine_bracket"] = only_engine
    # Positive means the real bracket fell short of the rule's optimum. This is
    # the quantity a known deviation has to account for, and it is computed
    # rather than restated: the figure the documentation carried until
    # 2026-08-09 was measured under a ranking that has since been corrected.
    out["distance_shortfall"] = [
        best - real for best, real in zip(reachable, real_scores, strict=True)
    ]
    out["note"] = (
        "Distance is the sum of |seed| differences within each record class. "
        "`best_reachable_distance` forbids rematches; `best_unconstrained_"
        "distance` does not, and is generally unreachable. A real bracket "
        f"following the rule scores its reachable optimum. The rule modelled "
        f"here is TI {ELIMINATION_RULE_YEAR}'s, which TI 2026 replaced with a "
        "sequential choice by the best-ranked team, so a `false` here says "
        "nothing about the engine that builds the shipping card."
    )
    return out


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
        # No Swiss round maximises ranking distance: the published text gives
        # Round 5 no modifications. This check used to maximise at Round 5 for
        # buckets where a loss eliminated, which is the defect corrected on
        # 2026-08-08 -- so the earlier "4 of 11 buckets" figure was measured
        # against a rule the event does not use.
        maximize_distance = False
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


def summarise(per_round: Sequence[dict]) -> dict:
    """Counts over every bucket where the pairing rule actually had a choice.

    A bucket with one legal matching tests nothing, so it is excluded here and
    the denominator is the number of buckets that could have disagreed.

    This exists so the provenance comment in `config/ti2026_rules.yaml` can cite
    an artifact instead of restating a figure. The figure it used to restate was
    measured on an engine that has since been corrected twice, and neither
    correction reached the comment.
    """
    buckets = [b for r in per_round for b in r["buckets"] if "seeds_agreeing" in b]
    # The denominator that actually tests the rule. Where every legal matching
    # scores the same distance, the preference cannot be wrong and agreement
    # there is not evidence for it -- counting those inflates the headline.
    deciding = [b for b in buckets if b["min_distance"] != b["max_distance"]]
    return {
        "buckets_with_a_choice": len(buckets),
        "buckets_agreeing_on_every_seed": sum(1 for b in buckets if b["status"] == "always"),
        "buckets_agreeing_on_no_seed": sum(1 for b in buckets if b["status"] == "never"),
        "buckets_agreeing_on_some_seeds": sum(1 for b in buckets if b["status"] == "sometimes"),
        "real_pairing_at_min_distance": sum(1 for b in buckets if b["actual_is_min"]),
        "real_pairing_at_max_distance": sum(1 for b in buckets if b["actual_is_max"]),
        "real_pairing_matches_fold": sum(1 for b in buckets if b["matches_fold_pairing"]),
        "where_distance_discriminates": {
            "buckets": len(deciding),
            "agreeing_on_every_seed": sum(1 for b in deciding if b["status"] == "always"),
            "real_pairing_at_min_distance": sum(1 for b in deciding if b["actual_is_min"]),
            "real_pairing_at_max_distance": sum(1 for b in deciding if b["actual_is_max"]),
            "real_pairing_strictly_between": sum(
                1 for b in deciding if not b["actual_is_min"] and not b["actual_is_max"]
            ),
            "real_pairing_matches_fold": sum(1 for b in deciding if b["matches_fold_pairing"]),
        },
    }


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
    elimination_rule = check_elimination_pairing(rounds, groups, rules, seeds)
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
        # Which tournament's rules each part of this report models. They are not
        # all the same year, and a reader who assumes they are will draw the
        # wrong conclusion from `engine_reproduces_the_real_bracket` -- which
        # two entries in the strengthening plan already did.
        "rule_year": {
            "event_replayed": EVENT_YEAR,
            "swiss_pairing_rule": SWISS_PAIRING_RULE_YEAR,
            "elimination_rule": ELIMINATION_RULE_YEAR,
            "tiebreak_order": TIEBREAK_ORDER_YEAR,
            "tiebreak_criteria_used": list(TIEBREAK_ORDER),
            "rules_config": rules_path,
            "note": (
                f"This replays TI {EVENT_YEAR} and models TI "
                f"{ELIMINATION_RULE_YEAR}'s elimination rule, which TI 2026 "
                "replaced with a sequential choice by the best-ranked 3-2 team. "
                "A `false` in `engine_reproduces_the_real_bracket` is therefore "
                "not a verdict on the engine that builds the shipping card. "
                f"The ranking, however, uses TI {TIEBREAK_ORDER_YEAR}'s "
                f"criteria, because `tiebreak.py` carries one order and it is "
                f"the shipping one -- so ties broken below the fifth criterion "
                f"are resolved by a rule TI {EVENT_YEAR} did not use. That "
                "mixture is disclosed rather than resolved: changing it is a "
                "modelling decision, and this producer gates nothing."
            ),
        },
        "known_deviations": [dict(d) for d in KNOWN_DEVIATIONS],
        "rounds_observed": len(rounds),
        "swiss_rounds_modelled": rules.total_rounds,
        "elimination_rounds_observed": len(elimination),
        "elimination_series": [len(r) for r in elimination],
        "elimination_pairing_rule": elimination_rule,
        "group_sizes": {
            g: sum(1 for v in groups.values() if v == g) for g in sorted(set(groups.values()))
        },
        "seeds": list(seeds),
        "final_records_match_frozen_truth": not mismatched,
        "final_record_mismatches": mismatched,
        "summary": summarise(per_round),
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
