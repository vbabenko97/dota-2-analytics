import math
import random


def map_win_prob(s_a: float, s_b: float) -> float:
    """Bradley-Terry on the logit scale: P(A wins one map against B)."""
    return 1.0 / (1.0 + math.exp(-(s_a - s_b)))


def series_win_prob(p_map: float, best_of: int = 3) -> float:
    """Closed-form series win probability assuming independent maps."""
    if best_of != 3:
        raise ValueError("only best-of-3 has a closed form here")
    return p_map**2 * (3.0 - 2.0 * p_map)


def simulate_series(
    s_a: float, s_b: float, rng: random.Random, best_of: int = 3
) -> tuple[int, int]:
    """Simulate maps until one side reaches the required win count.

    Maps are conditionally independent given strengths: the spec defaults the
    series shock to zero until historical residual dependence supports one.
    """
    need = best_of // 2 + 1
    p = map_win_prob(s_a, s_b)
    wins_a = wins_b = 0
    while wins_a < need and wins_b < need:
        if rng.random() < p:
            wins_a += 1
        else:
            wins_b += 1
    return wins_a, wins_b
