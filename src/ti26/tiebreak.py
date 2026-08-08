import random
from collections.abc import Callable

from ti26.types import TeamState

# The order `_primary_key` plus the duration/coin-toss fallback below actually
# implement. `rules.load_rules` checks the config's tiebreak_order against
# this so a divergent YAML raises instead of silently doing nothing.
#
# THIS IS TI 2026's ORDER, fetched 2026-08-08 from Valve's rules page (archived
# verbatim in docs/ti26/2026-08-08-ti2026-rules-fetched.md):
#
#     Number of Matches Won
#     Number of Matches Lost
#     Total Number of Matches Won by Opponents Played
#     Percentage of Games Won
#     Average Percentage of Games Won by Opponents Played
#     Average Game Duration (Shorter is Better)
#     Coin Toss
#
# It is NOT TI 2025's, and the difference is not cosmetic. TI 2025 ran six
# criteria with percentage of games won THIRD and no duration at all. Earlier on
# 2026-08-08, before the 2026 page carried a pairing section, commit 23beac3
# rewrote this list to TI 2025's on the reasonable assumption that the format
# carried over. It did not: Valve transposed criteria 3 and 4 and added a
# duration criterion for 2026.
#
# So `avg_duration` is a live criterion again, and `rank_teams` requires a
# resolver rather than falling through to the coin toss. Skipping a published
# criterion because it is inconvenient to sample is how a tie gets decided by
# the wrong rule.
TIEBREAK_ORDER = [
    "series_wins",
    "series_losses",
    "opponent_series_wins",
    "game_win_pct",
    "opponent_game_win_pct",
    "avg_duration",
    "coin_toss",
]


class DurationUnavailableError(RuntimeError):
    """Raised when criterion 6 is required but no duration source exists."""


class DurationResolver:
    """Lazily samples per-map durations, memoised and extended per team.

    Durations are drawn only when a tie survives the first five criteria, so
    the common path never pays for them. Samples persist across rounds and are
    extended as maps accumulate, keeping a team's average monotone in its own
    history rather than resampled each time it is consulted.
    """

    def __init__(self, rng: random.Random, log_mean: float, log_sigma: float) -> None:
        self._rng = rng
        self._log_mean = log_mean
        self._log_sigma = log_sigma
        self._samples: dict[str, list[float]] = {}
        self.consultations = 0

    def average_for(self, team_id: str, maps_played: int) -> float:
        self.consultations += 1
        if maps_played <= 0:
            raise DurationUnavailableError(
                f"team {team_id!r} has no maps; cannot compute average duration"
            )
        samples = self._samples.setdefault(team_id, [])
        if maps_played < len(samples):
            raise DurationUnavailableError(
                f"team {team_id!r} has {len(samples)} cached duration samples but was "
                f"asked for maps_played={maps_played}; map counts must not decrease"
            )
        while len(samples) < maps_played:
            samples.append(self._rng.lognormvariate(self._log_mean, self._log_sigma))
        return sum(samples) / len(samples)

    def bind(self, states: dict[str, TeamState]) -> Callable[[str], float]:
        def resolve(team_id: str) -> float:
            return self.average_for(team_id, states[team_id].maps_played)

        return resolve


def game_win_pct(team: TeamState) -> float:
    total = team.map_wins + team.map_losses
    return team.map_wins / total if total else 0.0


def _primary_key(team: TeamState, by_id: dict[str, TeamState]) -> tuple:
    known = []
    for opponent_id in team.opponents:
        if opponent_id not in by_id:
            raise ValueError(
                f"team {team.team_id!r} references opponent {opponent_id!r} "
                "which is not in the ranked team list"
            )
        known.append(by_id[opponent_id])
    opp_series_wins = sum(o.series_wins for o in known)
    opp_gwp = sum(game_win_pct(o) for o in known) / len(known) if known else 0.0
    return (
        -team.series_wins,
        team.series_losses,
        -opp_series_wins,
        -game_win_pct(team),
        -opp_gwp,
    )


def rank_teams(
    states: list[TeamState],
    rng: random.Random,
    duration_fn: Callable[[str], float] | None = None,
) -> list[str]:
    """Order team ids best to worst by the official tiebreak sequence.

    Criteria 1-5 are computed eagerly. Average duration is consulted only
    inside blocks still tied after those five. A surviving tie with no
    duration source is an error, not a licence to skip to the coin toss.
    """
    by_id = {s.team_id: s for s in states}
    keys = {s.team_id: _primary_key(s, by_id) for s in states}
    ordered = sorted(states, key=lambda s: keys[s.team_id])

    out: list[TeamState] = []
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and keys[ordered[j + 1].team_id] == keys[ordered[i].team_id]:
            j += 1
        block = ordered[i : j + 1]
        if len(block) > 1:
            if duration_fn is None:
                tied = [s.team_id for s in block]
                raise DurationUnavailableError(
                    f"teams {tied} tied through five criteria; duration resolver required"
                )
            durations = {s.team_id: duration_fn(s.team_id) for s in block}
            block = sorted(block, key=lambda s: (durations[s.team_id], rng.random()))
        out.extend(block)
        i = j + 1
    return [s.team_id for s in out]
