import random

from ti26.types import TeamState

# The order `_primary_key` plus the coin-toss fallback below actually implement.
# `rules.load_rules` checks the config's tiebreak_order against this so a
# divergent YAML raises instead of silently doing nothing.
#
# Corrected 2026-08-08 against the published rules the owner transcribed (see
# docs/ti26/2026-08-08-published-format-rules.md), which read:
#
#     Number of Matches Won
#     Number of Matches Lost
#     Percentage of Games Won
#     Total Number of Matches Won by Opponents Played
#     Average Percentage of Games Won by Opponents Played
#     Coin Toss
#
# Two defects. `opponent_series_wins` and `game_win_pct` were TRANSPOSED -- the
# published third criterion is a team's own game-win percentage, not its
# opponents' match wins. And an `avg_duration` criterion sat sixth, ahead of the
# coin toss, which appears nowhere in the published list; `rank_teams` used to
# RAISE if a tie reached it without a duration source. The design spec asserted
# average duration was official and cited nothing.
TIEBREAK_ORDER = [
    "series_wins",
    "series_losses",
    "game_win_pct",
    "opponent_series_wins",
    "opponent_game_win_pct",
    "coin_toss",
]


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
        -game_win_pct(team),
        -opp_series_wins,
        -opp_gwp,
    )


def rank_teams(states: list[TeamState], rng: random.Random) -> list[str]:
    """Order team ids best to worst by the published tiebreak sequence.

    Criteria 1-5 are computed eagerly; anything still tied after them goes to
    the coin toss, which is what the published rules specify and all they
    specify. There is no sixth criterion: the average-duration step this
    function used to take, and used to RAISE for when no duration source was
    supplied, was not in the rules.
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
            block = sorted(block, key=lambda s: rng.random())
        out.extend(block)
        i = j + 1
    return [s.team_id for s in out]
