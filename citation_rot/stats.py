"""Small statistics helpers."""
import math


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes in n trials, as (low, high) fractions."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - r) / d), min(1.0, (c + r) / d))


def pct(x):
    return f"{100 * x:.1f}%"


def rate_cell(k, n):
    if n == 0:
        return "n/a"
    lo, hi = wilson(k, n)
    return f"{pct(k / n)} ({pct(lo)} to {pct(hi)})"
