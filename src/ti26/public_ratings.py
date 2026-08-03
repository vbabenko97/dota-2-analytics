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


def parse_ratings(rows: Sequence[Mapping]) -> dict[int, PublicRating]:
    """Parse `TEAM_RATING_QUERY` explorer rows into `PublicRating` by team_id.

    OpenDota's explorer serialises bigint columns (`team_id`,
    `last_match_time`) as JSON strings (confirmed 2026-08-02, see
    `docs/audits/2026-08-02-rung3-source-research.md`), so every int-typed
    field is cast defensively with `int()` rather than assumed to already be
    a Python int; `int()` accepts both a numeric string and a native int
    unchanged, so this is safe either way the explorer happens to encode it.
    """
    out: dict[int, PublicRating] = {}
    for row in rows:
        team_id = int(row["team_id"])
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
