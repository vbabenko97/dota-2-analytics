"""Rung 3 fallback strength source: OpenDota's `team_rating` table.

Spec X names "Noxville, datdota" for rung 3, but that source is unreachable
from this environment -- 403 to every access path tried, including the
Internet Archive's own crawler; Noxville's public dataset dead since
2020-12-29 (see `docs/audits/2026-08-02-rung3-source-research.md`).
`team_rating` is the only machine-readable public source this project could
actually reach, so this module converts its raw `rating` column into the
zero-centred logit strengths `ti26.series.map_win_prob` consumes.

The scale conversion is the load-bearing risk here. `team_rating.rating` is
empirically Elo-shaped (our 16 configured teams: range 1183.6-1553.3, mean
1333.6) but OpenDota documents NO divisor for this specific table anywhere
reachable. `LOGIT_PER_ELO` below is inferred by convention -- it matches
this repo's own `EloModel.strengths()` (`src/ti26/ratings/elo.py`), which
uses the classic Elo `/400` logistic -- NOT a documented constant for
`team_rating`. Every place this conversion surfaces must say so plainly,
and `cli_rung3`'s scale-sensitivity sweep exists specifically because this
inference cannot be backtested: unlike Elo/Glicko, a single public rating
snapshot has no rolling out-of-sample history to check it against.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise

from ti26.data.schema import MapRow
from ti26.roster import roster_version_id
from ti26.series import map_win_prob

# Inferred, NOT documented by OpenDota for `team_rating` (see the module
# docstring and `docs/audits/2026-08-02-rung3-source-research.md` section
# 4). Matches `math.log(10) / self._scale` in `EloModel.strengths()` at the
# conventional Elo scale of 400.
LOGIT_PER_ELO = math.log(10) / 400.0

# Below this many recorded games (wins + losses), `team_rating` is treating
# a recent rebrand/roster change as if it had an established team's sample
# size. 200 was picked because it cleanly separates the six known-thin TI
# 2026 teams (max observed: GamerLegion at 184 games) from the next-smallest
# established team (Team Yandex, 295 games) with a wide margin on both
# sides -- not tuned to hit a target count.
THIN_GAMES_THRESHOLD = 200

# Days since a roster's last recorded match before its rating is flagged
# stale. 30 sits inside the observed gap, across TI 2026's 16 configured
# teams, between the "recently active" cluster (<=18 days) and the "long
# inactive" cluster (>=34 days) -- not tuned to hit a target count.
STALE_DAYS_THRESHOLD = 30.0

_DAY_SECONDS = 86400.0

# Window length for the observed-recent-form diagnostic (see
# `observed_recent_form` below). 90 days is a window long enough to
# accumulate a usable map count for most rosters without reaching so far
# back that it stops describing the CURRENT roster's form.
OBSERVED_FORM_WINDOW_DAYS = 90.0

# Standard two-sided 95% Wilson score z-score.
WILSON_Z_95 = 1.96

# Observed magnitude of same-day OpenDota `team_rating` drift, in rating
# points -- measured directly (2026-08-02 rung-3 review, Finding 4) between
# two live runs hours apart: a single head-to-head result moved two teams
# (BoomBoys, Team Falcons) by exactly +/-17.74 rating points each (equal and
# opposite -- the signature of a head-to-head result), collapsing their
# strength gap from 0.2189 to 0.0146 logits while they sat across a card
# category boundary. A citation of an OBSERVED magnitude, not a tuned
# constant: an adjacent pair in the strength ordering separated by less
# than this is one plausible match result away from swapping order.
DAILY_DRIFT_RATING_POINTS = 17.74


@dataclass(frozen=True)
class PublicRating:
    """One team's row from OpenDota's `team_rating` table.

    `rating` is on `team_rating`'s own undocumented scale (see the module
    docstring) -- not yet a logit. `last_match_time` is a unix epoch second,
    exactly as the explorer returns it (after the defensive int cast in
    `parse_ratings`).
    """

    team_id: int
    rating: float
    wins: int
    losses: int
    last_match_time: int

    @property
    def games(self) -> int:
        return self.wins + self.losses

    def is_thin(self, threshold: int = THIN_GAMES_THRESHOLD) -> bool:
        """True when the sample size is an order of magnitude below the
        established part of the field -- see `THIN_GAMES_THRESHOLD`."""
        return self.games < threshold

    def stale_days(self, now: datetime) -> float:
        """Days between this rating's last recorded match and `now`.

        `now` is a parameter, never `datetime.now()` internally, so this is
        testable without the assertion changing meaning on every run.
        """
        last = datetime.fromtimestamp(self.last_match_time, tz=UTC)
        return (now - last).total_seconds() / _DAY_SECONDS

    def is_stale(self, now: datetime, threshold: float = STALE_DAYS_THRESHOLD) -> bool:
        return self.stale_days(now) >= threshold


class NullRatingFieldError(ValueError):
    """A `team_rating` row for `team_id` is present but has a null `field`.

    A different failure mode from the row being absent entirely (the
    "missing team_rating row" refusal in `cli_rung3.py`): OpenDota can return
    a row for a `team_id` with one of its numeric columns set to `null`
    (confirmed foreseeable, per the 2026-08-02 rung-3 review, Finding 3).
    Raised instead of letting the bare `float()`/`int()` cast below raise an
    unhandled `TypeError` deep in the parser -- this still halts the run
    (via `cli_rung3.main`'s refusal path) with no fabricated strength, but
    with a message that names the team and the field, not a stack trace.
    """

    def __init__(self, team_id: int, field: str):
        self.team_id = team_id
        self.field = field
        super().__init__(f"team_id={team_id}'s team_rating row has a null {field!r} field")


def parse_ratings(rows: Sequence[Mapping]) -> dict[int, PublicRating]:
    """Parse `TEAM_RATING_QUERY` explorer rows into `PublicRating` by team_id.

    OpenDota's explorer serialises bigint columns (`team_id`,
    `last_match_time`) as JSON strings (confirmed 2026-08-02, see
    `docs/audits/2026-08-02-rung3-source-research.md`), so every int-typed
    field is cast defensively with `int()` rather than assumed to already be
    a Python int; `int()` accepts both a numeric string and a native int
    unchanged, so this is safe either way the explorer happens to encode it.

    A row can also be present but carry a null `rating`/`wins`/`losses`/
    `last_match_time` -- checked explicitly and raised as
    `NullRatingFieldError`, naming the team_id and field, rather than
    letting the cast below raise an unhandled `TypeError`.
    """
    out: dict[int, PublicRating] = {}
    for row in rows:
        team_id = int(row["team_id"])
        for field in ("rating", "wins", "losses", "last_match_time"):
            if row.get(field) is None:
                raise NullRatingFieldError(team_id, field)
        out[team_id] = PublicRating(
            team_id=team_id,
            rating=float(row["rating"]),
            wins=int(row["wins"]),
            losses=int(row["losses"]),
            last_match_time=int(row["last_match_time"]),
        )
    return out


def strengths_from_ratings(
    ratings: Mapping[str, PublicRating], logit_per_elo: float = LOGIT_PER_ELO
) -> dict[str, float]:
    """Zero-centred logit strengths from raw `team_rating.rating` values.

    Centred on the MEAN OVER THE TEAMS PASSED IN -- this project's 16 TI
    2026 teams, per the controller ruling to look up each team by its
    current configured `team_id` as-is, not any wider OpenDota population.
    `logit_per_elo` is overridable so the scale-sensitivity sweep can probe
    a different inferred divisor without duplicating this function.
    """
    if not ratings:
        return {}
    mean = sum(r.rating for r in ratings.values()) / len(ratings)
    return {name: (r.rating - mean) * logit_per_elo for name, r in ratings.items()}


def boundary_proximity(
    strengths: Mapping[str, float],
    ordered_by_strength: Sequence[str],
    logit_per_elo: float = LOGIT_PER_ELO,
    threshold_points: float = DAILY_DRIFT_RATING_POINTS,
) -> list[dict]:
    """Gap between each ADJACENT pair in the strength ordering, in logits AND
    converted back to rating points (`gap_logit / logit_per_elo` -- the
    inverse of the conversion `strengths_from_ratings` applies), flagged
    when that gap is smaller than `threshold_points` of observed same-day
    drift (see `DAILY_DRIFT_RATING_POINTS`).

    `ordered_by_strength` must already be sorted descending (strongest
    first) -- this function does not sort, so a caller passing an unsorted
    sequence would silently get nonsense adjacent pairs. Diagnostic only:
    reported, never gated on, never feeds back into a strength or the card.
    """
    out = []
    for a, b in pairwise(ordered_by_strength):
        gap_logit = strengths[a] - strengths[b]
        gap_points = gap_logit / logit_per_elo
        out.append(
            {
                "team_a": a,
                "team_b": b,
                "gap_logit": gap_logit,
                "gap_points": gap_points,
                "flagged": gap_points < threshold_points,
            }
        )
    return out


def scale_sensitivity_sweep(
    ratings: Mapping[str, PublicRating],
    rules,
    divisor_multipliers: Sequence[float],
    n_sims: int = 20000,
    seed: int = 0,
) -> list[dict]:
    """How far does the card move if the inferred `/400` divisor is wrong?

    Mirrors `ti26.duration.sensitivity_sweep`'s noise-floor discipline
    exactly (read that function first): `noise_floor` is the MAX of three
    pairwise max-abs-deltas among baseline (the FIRST `divisor_multipliers`
    entry) runs at seeds `seed`, `seed + 1`, and `seed + 2` -- deliberately
    conservative, biased toward calling fewer multipliers resolvable. Every
    entry carries the same `noise_floor` and a `resolvable` flag
    (`max_abs_delta > noise_floor`). A `max_abs_delta` at or below the floor
    is NOT evidence that the divisor moved anything -- it is what pure
    resampling noise looks like at this sample size.

    Unlike `duration.py`'s target (`rules.duration_log_sigma`, one shared
    scalar), the parameter swept here rescales every team's raw
    `team_rating.rating` into logits BEFORE `strengths_from_ratings`'s
    zero-centring, so a wrong divisor changes every team's strength
    simultaneously and by an amount proportional to its distance from the
    field mean -- the exact failure mode named in the module docstring.
    """
    from ti26.montecarlo import category_marginals
    from ti26.types import Category

    def _strengths_for(multiplier: float) -> dict[str, float]:
        divisor = 400.0 * multiplier
        return strengths_from_ratings(ratings, logit_per_elo=math.log(10) / divisor)

    def _max_abs_delta(a: dict[str, dict], b: dict[str, dict]) -> float:
        return max(
            abs(a[team][category] - b[team][category]) for team in a for category in Category
        )

    baseline: dict[str, dict] | None = None
    noise_floor = 0.0
    out: list[dict] = []
    for multiplier in divisor_multipliers:
        strengths = _strengths_for(multiplier)
        marginals = category_marginals(strengths, rules, n_sims=n_sims, seed=seed)
        if baseline is None:
            baseline = marginals
            baseline_runs = [
                marginals,
                category_marginals(strengths, rules, n_sims=n_sims, seed=seed + 1),
                category_marginals(strengths, rules, n_sims=n_sims, seed=seed + 2),
            ]
            noise_floor = max(
                _max_abs_delta(baseline_runs[a], baseline_runs[b])
                for a, b in [(0, 1), (0, 2), (1, 2)]
            )
            out.append(
                {
                    "divisor_multiplier": multiplier,
                    "divisor": 400.0 * multiplier,
                    "max_abs_delta": 0.0,
                    "is_baseline": True,
                    "noise_floor": noise_floor,
                    "resolvable": False,
                }
            )
            continue
        delta = _max_abs_delta(marginals, baseline)
        out.append(
            {
                "divisor_multiplier": multiplier,
                "divisor": 400.0 * multiplier,
                "max_abs_delta": float(delta),
                "is_baseline": False,
                "noise_floor": noise_floor,
                "resolvable": bool(delta > noise_floor),
            }
        )
    return out


@dataclass(frozen=True)
class ObservedForm:
    """One team's observed-vs-implied recent form (see `observed_recent_form`).

    `rate`/`ci_low`/`ci_high` are `None` when `n == 0` -- there is no rate to
    report or bound in that case, and `verdict` is `"no data"`.

    Diagnostic only: nothing here feeds back into a strength, the `/400`
    divisor, or the card. See `reports/rung3_provenance.md`'s "Observed
    recent form" section for the caveats this must always carry.
    """

    wins: int
    losses: int
    n: int
    rate: float | None
    ci_low: float | None
    ci_high: float | None
    implied: float
    verdict: str


def wilson_interval(wins: int, n: int, z: float = WILSON_Z_95) -> tuple[float, float]:
    """95% (at the default `z`) Wilson score interval on `wins / n`.

    The classic closed form (Wilson 1927): centred on `phat + z**2/(2n)`
    rather than `phat` alone, and both the centring and the half-width carry
    a `z**2/n`-scale continuity term -- dropping those terms (i.e. falling
    back to the naive `phat +/- z*sqrt(phat*(1-phat)/n)` normal-approximation
    interval) changes the bounds measurably, especially at small `n`.
    """
    if n <= 0:
        raise ValueError(f"wilson_interval requires n > 0, got {n}")
    phat = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = phat + z2 / (2.0 * n)
    adjustment = z * math.sqrt(phat * (1.0 - phat) / n + z2 / (4.0 * n * n))
    return (centre - adjustment) / denom, (centre + adjustment) / denom


def classify_form_verdict(
    implied: float, ci_low: float | None, ci_high: float | None, n: int
) -> str:
    """`"form ABOVE implied"` when the field's own implied rate sits BELOW
    the observed CI's low end (the team is doing better than its strength
    says it should), `"form BELOW implied"` for the opposite, else
    `"consistent"`. `"no data"` when `n == 0` -- there is no CI to compare
    against.
    """
    if n == 0:
        return "no data"
    if implied < ci_low:
        return "form ABOVE implied"
    if implied > ci_high:
        return "form BELOW implied"
    return "consistent"


def _implied_map_win_rate(name: str, strengths: Mapping[str, float]) -> float:
    """Mean of `map_win_prob(s_self, s_other)` over every OTHER team in
    `strengths` -- what `name`'s own strength implies its map win rate
    against this field should be. Excludes `name` itself: including it would
    silently pull every implied rate toward 0.5 by `1/len(strengths)`.
    """
    s_self = strengths[name]
    others = [s for other, s in strengths.items() if other != name]
    if not others:
        raise ValueError(f"cannot compute an implied rate for {name!r} against an empty field")
    return sum(map_win_prob(s_self, s_other) for s_other in others) / len(others)


def _roster_record(
    rows: Sequence[MapRow], rvid: str, window_start: int, window_end: int
) -> tuple[int, int]:
    """(wins, losses) for the roster `rvid`, counted by matching the ROSTER
    hash on either side of each map -- never by `team_id` -- so the record
    follows the roster across a team_id change (org rebrand, sponsor
    rename). Only maps with `window_start <= start_time <= window_end` count.
    """
    wins = losses = 0
    for r in rows:
        if r.start_time < window_start or r.start_time > window_end:
            continue
        if roster_version_id(r.radiant_accounts) == rvid:
            if r.radiant_win:
                wins += 1
            else:
                losses += 1
        elif roster_version_id(r.dire_accounts) == rvid:
            if r.radiant_win:
                losses += 1
            else:
                wins += 1
    return wins, losses


def observed_recent_form(
    rows: Sequence[MapRow],
    resolved: Mapping[str, str],
    strengths: Mapping[str, float],
    reference_time: int,
    window_days: float = OBSERVED_FORM_WINDOW_DAYS,
) -> dict[str, ObservedForm]:
    """Each configured team's CURRENT roster's observed map record over the
    last `window_days`, measured back from `reference_time` -- always a
    parameter (typically the store's own most recent `start_time`), never
    `datetime.now()` or any other wall-clock read, so this is testable and
    means the same thing on any day this runs against a fixed snapshot.

    `resolved` must come from `ti26.teams.resolve_rosters` (team name ->
    current `roster_version_id`); this function does not re-resolve rosters,
    it only counts maps that hash to the given rvid via `_roster_record` --
    see that function's docstring for why that must be roster-keyed, not
    team_id-keyed.

    Compares each team's `implied` rate (from `_implied_map_win_rate`,
    computed from `strengths` regardless of `n`) against a 95% Wilson CI on
    the observed `rate`. This is a DIAGNOSTIC only: a rating-vs-rating
    anchor (like the Elo ordering check elsewhere in `cli_rung3`) cannot
    catch a strength source that is biased in the same direction our own
    models are biased; a direct read of actual recent results can. It must
    never be read as a ranking or as grounds to override a strength or the
    card on its own -- opposing strength is not controlled for (see the
    provenance report's caveats).
    """
    window_start = reference_time - round(window_days * _DAY_SECONDS)
    out: dict[str, ObservedForm] = {}
    for name, rvid in resolved.items():
        wins, losses = _roster_record(rows, rvid, window_start, reference_time)
        n = wins + losses
        implied = _implied_map_win_rate(name, strengths)
        if n == 0:
            out[name] = ObservedForm(
                wins=0, losses=0, n=0, rate=None, ci_low=None, ci_high=None,
                implied=implied, verdict="no data",
            )
            continue
        rate = wins / n
        ci_low, ci_high = wilson_interval(wins, n)
        verdict = classify_form_verdict(implied, ci_low, ci_high, n)
        out[name] = ObservedForm(
            wins=wins, losses=losses, n=n, rate=rate, ci_low=ci_low, ci_high=ci_high,
            implied=implied, verdict=verdict,
        )
    return out


def deviation_summary(
    observed_form: Mapping[str, ObservedForm], ordered_by_strength: Sequence[str]
) -> str:
    """Prose interpretation of `observed_form`'s verdict counts.

    Computed from `observed_form` on every call -- FIX A in the 2026-08-02
    rung-3 review found a version of this paragraph that hardcoded one run's
    specific finding ("five deviations, all bottom-half, none below") as
    permanent boilerplate; it stayed on the page verbatim even against a
    fixture whose real distribution was 16 consistent / 0 above / 0 below.
    Every number and direction claim below is read back out of
    `observed_form` and `ordered_by_strength`, never out of a prior run.

    `ordered_by_strength` must be every team in strength order, descending
    (strongest first) -- used only to test whether a one-directional set of
    deviations clusters in the bottom (weaker) or top (stronger) half, which
    is the specific pattern the `/400` divisor's over-spreading would
    produce. A `"no data"` verdict does not count as either direction.
    """
    above = sorted(n for n, f in observed_form.items() if f.verdict == "form ABOVE implied")
    below = sorted(n for n, f in observed_form.items() if f.verdict == "form BELOW implied")
    consistent = sum(1 for f in observed_form.values() if f.verdict == "consistent")

    if not above and not below:
        return (
            f"**No deviations this run:** all {consistent} team(s) with observed "
            "data fall inside their implied rate's 95% CI. This is weak evidence "
            "either way at these map counts -- the absence of a flagged "
            "deviation is not confirmation the strengths are correct."
        )
    if above and below:
        return (
            f"**Deviations point BOTH ways this run** ({len(above)} form ABOVE "
            f"implied, {len(below)} form BELOW implied) -- not the "
            "one-directional signature a systematic divisor or schedule bias "
            "would produce. More consistent with sampling noise across small "
            "map counts than with a shared cause."
        )

    half_size = len(ordered_by_strength) // 2
    bottom_half = set(ordered_by_strength[half_size:])
    top_half = set(ordered_by_strength[:half_size])
    direction, names, relevant_half, half_name = (
        ("ABOVE", above, bottom_half, "bottom") if above else ("BELOW", below, top_half, "top")
    )
    clustered = bool(names) and set(names) <= relevant_half
    if clustered:
        where = f"all in the {half_name} half"
        mechanism = (
            "ambiguous between the `/400` divisor over-spreading strengths and "
            "the schedule confound above, and this data cannot separate them."
        )
    else:
        where = "not clustered in either half of the field"
        mechanism = (
            "not explained by either the divisor over-spreading or the "
            "schedule confound above on its own; this data does not identify "
            "the cause."
        )
    return (
        f"**All {len(names)} current deviation(s) point the same way** (form "
        f"{direction} implied, {where}) with none the other way. Noise would be "
        f"roughly symmetric, so a one-directional pattern like this is "
        f"systematic -- but it is {mechanism}"
    )
