"""Multiclass proper scoring rules for the card's category forecasts.

Registered in `docs/superpowers/specs/2026-08-16-group-card-postmortem.md`
before this module existed.

A hit count answers "how many categories did the card get right". It cannot
distinguish a 51% forecast that lost from a 95% forecast that lost, and those
are very different errors for a probabilistic model. These scoring rules read
the forecast distribution the card was solved from, not the assignment it was
collapsed to.

CONVENTIONS ARE FROZEN HERE BECAUSE MORE THAN ONE EXISTS. `multiclass_brier`
is the unscaled sum form, `mean_i sum_k (p_ik - y_ik)^2`. `backtest.brier` in
this same repository is the BINARY `mean((p - y)^2)`, which for two classes is
exactly HALF this. The two are on different scales and comparing them across
modules is a category error that produces a plausible-looking ratio. They are
deliberately not named alike.

Log loss is in nats (natural log), matching `backtest.log_loss`.
"""

import math
from collections.abc import Mapping, Sequence


class ScoreInputError(ValueError):
    """A forecast that is not a distribution, or an outcome it cannot score."""


def _checked(
    forecasts: Mapping[str, Mapping[str, float]],
    actual: Mapping[str, str],
    categories: Sequence[str],
) -> list[tuple[Mapping[str, float], str]]:
    """Pair each subject's forecast with its realised category.

    Rejects a forecast whose mass does not sum to 1, a subject present in one
    mapping and not the other, and an outcome naming a category the forecast
    never mentions. Each of those would otherwise score as a merely bad
    forecast rather than as the bug it is.
    """
    if not actual:
        raise ScoreInputError("no outcomes to score")
    missing = sorted(set(actual) - set(forecasts))
    if missing:
        raise ScoreInputError(f"no forecast for: {missing}")
    extra = sorted(set(forecasts) - set(actual))
    if extra:
        raise ScoreInputError(f"forecast for subjects with no outcome: {extra}")
    paired = []
    for subject, observed in actual.items():
        row = forecasts[subject]
        if observed not in categories:
            raise ScoreInputError(f"{subject} realised {observed!r}, not one of {list(categories)}")
        unknown = sorted(set(row) - set(categories))
        if unknown:
            raise ScoreInputError(f"{subject} forecasts unknown categories: {unknown}")
        total = math.fsum(row.get(c, 0.0) for c in categories)
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ScoreInputError(f"{subject}'s forecast sums to {total!r}, not 1")
        paired.append((row, observed))
    return paired


def multiclass_brier(
    forecasts: Mapping[str, Mapping[str, float]],
    actual: Mapping[str, str],
    categories: Sequence[str],
) -> float:
    """`mean_i sum_k (p_ik - y_ik)^2` -- the UNSCALED sum form.

    See the module docstring: this is twice `backtest.brier`'s binary
    convention, on purpose, and the two must never be compared.
    """
    paired = _checked(forecasts, actual, categories)
    per_subject = []
    for row, observed in paired:
        per_subject.append(
            math.fsum((row.get(c, 0.0) - (1.0 if c == observed else 0.0)) ** 2 for c in categories)
        )
    return math.fsum(per_subject) / len(per_subject)


def multiclass_log_loss(
    forecasts: Mapping[str, Mapping[str, float]],
    actual: Mapping[str, str],
    categories: Sequence[str],
) -> float:
    """`-mean_i ln(p_i,actual)` in nats.

    A zero on the realised category returns `inf` rather than clipping to a
    small epsilon. Clipping would silently convert "the model called this
    impossible and it happened" -- the single most informative failure a
    probabilistic forecast can have -- into a large but finite number that
    averages away against the other fifteen subjects.
    """
    paired = _checked(forecasts, actual, categories)
    total = 0.0
    for row, observed in paired:
        p = row.get(observed, 0.0)
        if p <= 0.0:
            return math.inf
        total += math.log(p)
    return -total / len(paired)


def capacity_marginal_reference(
    capacities: Mapping[str, int], subjects: Sequence[str]
) -> dict[str, dict[str, float]]:
    """Every subject forecast the same `capacity / n` distribution.

    This is the team-level MARGINAL induced by the capacity-constrained random
    card, and that is the whole claim. It is NOT that null's joint: the null
    fills fixed capacities, so subjects' outcomes are dependent, while these
    rows are identical and independent. Scoring against it tests the stated
    marginals only.

    What it does reproduce exactly is the null's expected hit count,
    `n * sum(q^2)` -- 3.75 for TI 2026's `[1, 2, 5, 5, 2, 1]`.
    """
    total = sum(capacities.values())
    if total != len(subjects):
        raise ScoreInputError(
            f"capacities sum to {total} but there are {len(subjects)} subjects"
        )
    row = {category: count / total for category, count in capacities.items()}
    return {subject: dict(row) for subject in subjects}


def brier_skill_score(model: float, reference: float) -> float:
    """`1 - BS_model / BS_reference`. Positive means the model scored better."""
    if reference <= 0.0:
        raise ScoreInputError("reference Brier score is not positive; no skill ratio exists")
    return 1.0 - model / reference


def expected_hits(
    forecasts: Mapping[str, Mapping[str, float]], card: Mapping[str, str]
) -> float:
    """Sum of the forecast mass the card actually bet on.

    For the capacity-marginal reference under any coherent card this is
    `n * sum(q^2)`, which is where the registered 3.75 comes from.
    """
    return math.fsum(forecasts[subject].get(category, 0.0) for subject, category in card.items())
