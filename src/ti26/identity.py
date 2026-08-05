"""What identifies a team to the model, as opposed to what labels it on a card.

Display names are presentation. They must not reach any ordering decision,
because ordering decisions reach the RNG streams and the solver's choice among
equal-cost optima. Where two teams are indistinguishable on the numbers -- equal
strengths, or byte-identical marginal rows -- something still has to order them,
and that something is the configured team id.
"""

from collections.abc import Callable, Mapping


def order_key(
    keyed: Mapping[str, object], team_ids: Mapping[str, object] | None
) -> Callable[[str], str]:
    """Return the final ordering key for `keyed`'s teams.

    With `team_ids`, ties are ordered by the configured identifier, so renaming
    a team cannot change any result. Without it, the mapping's own keys are
    treated as the caller's stable identities -- which is true for synthetic
    fields whose keys are already ids, and is why this is not defaulted away:
    a caller that has real ids must pass them.

    Validation is strict rather than best-effort. A silently ignored id mapping
    is worse than none, because the caller then believes the result is
    name-independent while the name is still deciding.
    """
    if team_ids is None:
        return lambda team: team
    if set(team_ids) != set(keyed):
        missing = sorted(set(keyed) - set(team_ids))
        extra = sorted(set(team_ids) - set(keyed))
        raise ValueError(
            f"team_ids must name exactly the teams supplied; missing {missing}, extra {extra}"
        )
    values = [str(team_ids[team]) for team in keyed]
    if any(not value for value in values):
        raise ValueError("team_ids must not contain an empty identifier")
    if len(set(values)) != len(values):
        raise ValueError("team_ids must be unique; duplicates cannot order a tie")
    return lambda team: str(team_ids[team])
