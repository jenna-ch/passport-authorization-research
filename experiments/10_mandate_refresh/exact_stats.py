# exact_stats.py — Clopper-Pearson intervals and the two-sided Fisher exact
# test, computed from the log-gamma function so no third-party dependency is
# needed. Validated against published reference values at the bottom.

import math


def _lgamma(n):
    return math.lgamma(n)


def _log_choose(n, k):
    if k < 0 or k > n:
        return float("-inf")
    return _lgamma(n + 1) - _lgamma(k + 1) - _lgamma(n - k + 1)


def _betacf(a, b, x, itmax=400, eps=3e-16):
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < 1e-300:
        d = 1e-300
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-300:
            d = 1e-300
        c = 1.0 + aa / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def betainc(a, b, x):
    """regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = _lgamma(a + b) - _lgamma(a) - _lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbeta + b * math.log(1.0 - x) + a * math.log(x)) \
        * _betacf(b, a, 1.0 - x) / b


def _beta_ppf(p, a, b):
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if betainc(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def clopper_pearson(k, n, alpha=0.05):
    """exact binomial confidence interval."""
    if n == 0:
        return (None, None)
    lo = 0.0 if k == 0 else _beta_ppf(alpha / 2.0, k, n - k + 1)
    hi = 1.0 if k == n else _beta_ppf(1.0 - alpha / 2.0, k + 1, n - k)
    return (lo, hi)


def _hyper_logpmf(k, a, b, c, d):
    """log P(X = k) for the 2x2 table with the observed margins."""
    n = a + b + c + d
    r1, c1 = a + b, a + c
    return (_log_choose(c1, k) + _log_choose(n - c1, r1 - k)
            - _log_choose(n, r1))


def fisher_exact_two_sided(a, b, c, d):
    """two-sided Fisher exact p, by the total-probability (sum of tables no
    more probable than observed) convention."""
    n = a + b + c + d
    r1, c1 = a + b, a + c
    lo, hi = max(0, r1 - (n - c1)), min(r1, c1)
    obs = _hyper_logpmf(a, a, b, c, d)
    tol = 1e-7
    p = 0.0
    for k in range(lo, hi + 1):
        lp = _hyper_logpmf(k, a, b, c, d)
        if lp <= obs + tol:
            p += math.exp(lp)
    return min(1.0, p)


if __name__ == "__main__":
    # ---- validation against published values
    lo, hi = clopper_pearson(0, 16)
    assert abs(lo - 0.0) < 1e-9 and abs(hi - 0.2059) < 5e-4, (lo, hi)
    lo, hi = clopper_pearson(3, 16)
    assert abs(lo - 0.0403) < 5e-4 and abs(hi - 0.4564) < 5e-4, (lo, hi)
    lo, hi = clopper_pearson(1, 10)
    assert abs(lo - 0.0025) < 5e-4 and abs(hi - 0.4450) < 5e-4, (lo, hi)
    # Fisher: the classic tea-tasting table
    assert abs(fisher_exact_two_sided(3, 1, 1, 3) - 0.4857) < 5e-4
    # a null table
    assert abs(fisher_exact_two_sided(0, 16, 0, 16) - 1.0) < 1e-12
    # a non-null table, checked against an INDEPENDENT direct enumeration
    # with exact integer binomials rather than against a remembered figure
    def _direct(a, b, c, d):
        from math import comb
        n, r1, c1 = a + b + c + d, a + b, a + c
        tot = comb(n, r1)
        ps = {k: comb(c1, k) * comb(n - c1, r1 - k) / tot
              for k in range(max(0, r1 - (n - c1)), min(r1, c1) + 1)}
        return sum(v for v in ps.values() if v <= ps[a] * (1 + 1e-7))
    for tbl in ((10, 6, 2, 14), (3, 13, 0, 16), (1, 15, 0, 16),
                (16, 0, 8, 8), (5, 11, 2, 14)):
        assert abs(fisher_exact_two_sided(*tbl) - _direct(*tbl)) < 1e-9, tbl
    assert abs(fisher_exact_two_sided(10, 6, 2, 14) - 0.0091470) < 5e-7
    print("exact_stats: all reference validations pass")
