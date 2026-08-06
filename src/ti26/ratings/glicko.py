"""Roster-aware Glicko-2 (Glickman 2013), map-level.

The rating deviation is the reason spec V prefers this over Elo: qualifier
teams and freshly assembled rosters genuinely are uncertain, and the measured
collapse in recent match volume (spec III) makes thin evidence the norm.
"""

import math
from dataclasses import dataclass

from ti26.data.schema import MapRow
from ti26.ratings import skip_reason
from ti26.roster import RosterIndex, roster_version_id

SCALE = 173.7178  # Glicko-2 internal scale conversion
LOGIT_PER_GLICKO = math.log(10) / 400.0


@dataclass(frozen=True)
class GlickoRating:
    rating: float
    rd: float
    volatility: float


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _e(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def expected_score(player: GlickoRating, opponent: GlickoRating) -> float:
    """Win probability for FORECASTING, accounting for BOTH rating deviations.

    Glickman specifies two different expected-score forms and they are not
    interchangeable. Do not "simplify" one into the other:

    * `_e(mu, mu_j, phi_j)` above uses the OPPONENT's deviation only. That is
      the Glicko-2 update step, and it is what `update_rating` calls.
    * This function uses the COMBINED `sqrt(phi_a^2 + phi_b^2)`. That is the
      outcome-prediction form, and it is what a log-loss backtest needs:
      uncertainty about EITHER side must flatten the forecast toward 0.5.

    Using the opponent-only form here would let a roster we know nothing about
    still receive an extreme prediction, deleting the exact property that makes
    Glicko worth preferring to Elo (spec V).
    """
    mu = (player.rating - 1500.0) / SCALE
    mu_j = (opponent.rating - 1500.0) / SCALE
    phi = math.sqrt(player.rd**2 + opponent.rd**2) / SCALE
    return 1.0 / (1.0 + math.exp(-_g(phi) * (mu - mu_j)))


def _solve_volatility(delta: float, phi: float, v: float, sigma: float, tau: float) -> float:
    """Illinois-variant regula falsi, per Glickman step 5."""
    a = math.log(sigma * sigma)
    delta_sq, phi_sq = delta * delta, phi * phi

    def f(x: float) -> float:
        ex = math.exp(x)
        numerator = ex * (delta_sq - phi_sq - v - ex)
        denominator = 2.0 * (phi_sq + v + ex) ** 2
        return numerator / denominator - (x - a) / (tau * tau)

    A = a
    if delta_sq > phi_sq + v:
        B = math.log(delta_sq - phi_sq - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        B = a - k * tau

    fa, fb = f(A), f(B)
    for _ in range(100):
        if abs(B - A) <= 1e-6:
            break
        C = A + (A - B) * fa / (fb - fa)
        fc = f(C)
        if fc * fb <= 0:
            A, fa = B, fb
        else:
            fa /= 2.0
        B, fb = C, fc
    return math.exp(A / 2.0)


def update_rating(
    player: GlickoRating, results: list[tuple[GlickoRating, float]], tau: float
) -> GlickoRating:
    """One Glicko-2 rating period for one player."""
    mu = (player.rating - 1500.0) / SCALE
    phi = player.rd / SCALE

    if not results:
        # No games: only uncertainty grows.
        phi_star = math.sqrt(phi * phi + player.volatility**2)
        return GlickoRating(player.rating, phi_star * SCALE, player.volatility)

    v_inv = 0.0
    delta_sum = 0.0
    for opponent, score in results:
        mu_j = (opponent.rating - 1500.0) / SCALE
        phi_j = opponent.rd / SCALE
        g_j = _g(phi_j)
        e_j = _e(mu, mu_j, phi_j)
        v_inv += g_j * g_j * e_j * (1.0 - e_j)
        delta_sum += g_j * (score - e_j)
    v = 1.0 / v_inv
    delta = v * delta_sum

    sigma_prime = _solve_volatility(delta, phi, v, player.volatility, tau)
    phi_star = math.sqrt(phi * phi + sigma_prime * sigma_prime)
    phi_prime = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    mu_prime = mu + phi_prime * phi_prime * delta_sum

    return GlickoRating(mu_prime * SCALE + 1500.0, phi_prime * SCALE, sigma_prime)


class GlickoModel:
    """Glicko-2 over integer rating periods, with idle-time RD inflation.

    Two things distinguish this from a naive per-match implementation, and
    both matter given the measured collapse in recent match volume (spec III):

    1. A roster that stops playing gets LESS certain, not frozen. Idle periods
       inflate RD by `sqrt(phi^2 + k*sigma^2)`. Without this a team last seen
       in March 2026 would arrive at TI carrying a March-tight RD, and the
       error lands squarely in the tails where the 4-0 and 0-4 slots live.
    2. Inheritance is weighted by MEASURED player overlap, not a constant.
    """

    def __init__(
        self,
        tau: float = 0.5,
        initial_rating: float = 1500.0,
        initial_rd: float = 350.0,
        initial_volatility: float = 0.06,
        period_seconds: int = 604800,
        roster_index: RosterIndex | None = None,
    ) -> None:
        self._tau = tau
        self._initial = GlickoRating(initial_rating, initial_rd, initial_volatility)
        self._period_seconds = period_seconds
        self._index = roster_index
        self._ratings: dict[str, GlickoRating] = {}
        self._last_period: dict[str, int] = {}
        self._maps: dict[str, int] = {}
        self._maps_by_period: dict[int, dict[str, int]] = {}
        self._pending: dict[str, list[tuple[GlickoRating, float]]] = {}
        self._epoch: int | None = None
        self._current_period: int = 0
        self.skipped: dict[str, int] = {}

    def _period_of(self, start_time: int) -> int:
        if self._epoch is None:
            self._epoch = start_time
        return (start_time - self._epoch) // self._period_seconds

    def _inflate(self, rating: GlickoRating, periods: int) -> GlickoRating:
        """Idle-period RD growth, capped at the prior's uncertainty.

        Uncapped inflation would eventually make a long-idle roster MORE
        uncertain than one never seen at all, which is incoherent.
        """
        if periods <= 0:
            return rating
        phi = rating.rd / SCALE
        phi_star = math.sqrt(phi * phi + periods * rating.volatility**2)
        return GlickoRating(
            rating.rating, min(phi_star * SCALE, self._initial.rd), rating.volatility
        )

    def rating_of(self, rvid: str, at_period: int | None = None) -> GlickoRating:
        period = self._current_period if at_period is None else at_period
        if rvid not in self._ratings:
            return self._inherit(rvid, period)
        idle = period - self._last_period.get(rvid, period)
        return self._inflate(self._ratings[rvid], idle)

    def _rating_for_update(self, rvid: str) -> GlickoRating:
        """The pre-update rating, carrying one FEWER inflation than `rating_of`.

        `update_rating` applies Glicko-2's own step-6 increment,
        `sqrt(phi^2 + sigma'^2)`, for the period being scored. Passing it
        `rating_of`'s value charged that increment twice: a roster playing in
        consecutive periods has `idle == 1`, so it took one inflation here and
        a second inside the update, and a roster returning after `k` idle
        periods took `k + 1` where Glicko-2 specifies `k`.

        `rating_of` stays as it is. It is right for prediction and for
        `strengths`, where no update follows and the full elapsed gap is
        exactly the uncertainty the caller should see.
        """
        if rvid not in self._ratings:
            return self._inherit(rvid, self._current_period)
        idle = self._current_period - self._last_period.get(rvid, self._current_period)
        return self._inflate(self._ratings[rvid], idle - 1)

    def _inherit(self, rvid: str, period: int) -> GlickoRating:
        """Continuity-weighted initialization (spec III), overlap-measured."""
        if self._index is None:
            return self._initial
        predecessor = self._index.predecessor(rvid)
        if predecessor is None or predecessor not in self._ratings:
            return self._initial
        weight = self._index.continuity_with_predecessor(rvid)
        if weight <= 0.0:
            return self._initial
        prior = self.rating_of(predecessor, at_period=period)
        rating = weight * prior.rating + (1.0 - weight) * self._initial.rating
        # Variance blend: uncertainty must never fall below the predecessor's,
        # because this exact roster has played nothing.
        rd = math.sqrt(weight * prior.rd**2 + (1.0 - weight) * self._initial.rd**2)
        return GlickoRating(rating, max(rd, prior.rd), prior.volatility)

    def predict(self, row: MapRow) -> float:
        if self._index is not None and skip_reason(row) is None:
            # Register rosters without counting maps. Uses team ids and player
            # ids only -- no outcome -- so it cannot leak. Guarded by
            # `skip_reason` so a `has_bad_roster` row (whose accounts carry
            # the -1 missing-player sentinel) never pollutes the stored
            # account sets or predecessor chain.
            self._index.observe(row, count=False)
        a = self.rating_of(roster_version_id(row.radiant_accounts))
        b = self.rating_of(roster_version_id(row.dire_accounts))
        return expected_score(a, b)

    def update(self, row: MapRow) -> None:
        """Accumulate one map's result into the current rating period.

        Rows must be observed in chronological `start_time` order, like
        `RosterIndex.observe`. Nothing here enforces or checks ordering: an
        out-of-order row would be bucketed into the wrong rating period and
        could be flushed against the wrong set of concurrent results.
        """
        reason = skip_reason(row)
        if reason is not None:
            self.skipped[reason] = self.skipped.get(reason, 0) + 1
            return
        if self._index is not None:
            self._index.observe(row)

        period = self._period_of(row.start_time)
        if period > self._current_period:
            self.flush()
            self._current_period = period

        a = roster_version_id(row.radiant_accounts)
        b = roster_version_id(row.dire_accounts)
        ra, rb = self.rating_of(a), self.rating_of(b)
        score = 1.0 if row.radiant_win else 0.0
        self._pending.setdefault(a, []).append((rb, score))
        self._pending.setdefault(b, []).append((ra, 1.0 - score))
        for rvid in (a, b):
            self._maps[rvid] = self._maps.get(rvid, 0) + 1
            bucket = self._maps_by_period.setdefault(period, {})
            bucket[rvid] = bucket.get(rvid, 0) + 1

    def flush(self) -> None:
        if not self._pending:
            return
        updated = {
            rvid: update_rating(self._rating_for_update(rvid), results, self._tau)
            for rvid, results in self._pending.items()
        }
        self._ratings.update(updated)
        for rvid in updated:
            self._last_period[rvid] = self._current_period
        self._pending = {}

    def strengths(self) -> dict[str, float]:
        """Zero-centred logit strengths, inflated to the current period.

        Calling this closes the current rating period: it calls `flush()`,
        which pushes whatever results are pending through `update_rating`
        immediately. Every caller in this codebase calls it after the period
        is already done, so this is latent today -- but calling it mid-period
        forces a premature, partial update and fragments that period into
        two sequential updates instead of one combined update.
        """
        self.flush()
        if not self._ratings:
            return {}
        current = {rvid: self.rating_of(rvid) for rvid in self._ratings}
        mean = sum(r.rating for r in current.values()) / len(current)
        return {k: (r.rating - mean) * LOGIT_PER_GLICKO for k, r in current.items()}

    def rating_deviations(self) -> dict[str, float]:
        """Current RD per roster. Calling this closes the current rating
        period (see `strengths`'s docstring for the mid-period hazard)."""
        self.flush()
        return {rvid: self.rating_of(rvid).rd for rvid in self._ratings}

    def prior_driven(self, min_maps: int = 10) -> list[str]:
        return sorted(r for r in self._ratings if self._maps.get(r, 0) < min_maps)

    def activity_report(self) -> list[dict]:
        """Maps per roster per rating period, plus current idle length.

        Spec III measured recent volume collapsing to ~1,600 maps in the last
        90 days; this is how that shows up per team rather than in aggregate.

        Calling this closes the current rating period (see `strengths`'s
        docstring for the mid-period hazard) -- a real risk here, since a
        diagnostic report is exactly the kind of thing a future caller might
        reach for mid-period.
        """
        self.flush()
        rows = []
        for rvid in sorted(self._ratings):
            per_period = {
                period: counts[rvid]
                for period, counts in sorted(self._maps_by_period.items())
                if rvid in counts
            }
            rows.append(
                {
                    "roster_version_id": rvid,
                    "total_maps": self._maps.get(rvid, 0),
                    "active_periods": len(per_period),
                    "maps_by_period": per_period,
                    "idle_periods": self._current_period - self._last_period.get(rvid, 0),
                    "rating": self.rating_of(rvid).rating,
                    "rd": self.rating_of(rvid).rd,
                }
            )
        return rows
