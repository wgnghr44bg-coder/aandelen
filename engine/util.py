"""Kleine, veilige rekenhulpen. Ontbrekende waarden zijn altijd None, nooit 0."""
import math
import statistics


def num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def div(a, b):
    a, b = num(a), num(b)
    if a is None or b is None or b == 0:
        return None
    return a / b


def cagr(new, old, years):
    new, old = num(new), num(old)
    if new is None or old is None or years <= 0 or new <= 0 or old <= 0:
        return None
    return (new / old) ** (1.0 / years) - 1


def lin(x, bad, good):
    """Score 0–100: `bad` geeft 0, `good` geeft 100, lineair ertussen (werkt in beide richtingen)."""
    x = num(x)
    if x is None or good == bad:
        return None
    t = (x - bad) / (good - bad)
    return round(max(0.0, min(1.0, t)) * 100, 2)


def avail(xs):
    return [num(x) for x in (xs or []) if num(x) is not None]


def mean(xs):
    v = avail(xs)
    return sum(v) / len(v) if v else None


def median(xs):
    v = avail(xs)
    return statistics.median(v) if v else None


def stdev(xs, min_n=3):
    v = avail(xs)
    return statistics.pstdev(v) if len(v) >= min_n else None


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def at(lst, i):
    if lst is None or i < 0 or i >= len(lst):
        return None
    return num(lst[i])


def rnd(x, d=4):
    x = num(x)
    return None if x is None else round(x, d)


def geomean_ratio(ratios):
    v = [r for r in avail(ratios) if r > 0]
    if not v:
        return None
    return math.exp(sum(math.log(r) for r in v) / len(v))


def score_category(vals, forced, weights, norms, min_cov=0.5):
    """Gewogen categoriescore.

    vals:   {metric: waarde}  (None = ontbreekt)
    forced: {metric: score}   (expliciete score bij bijzondere gevallen, bv. verlies -> 0)
    Ontbrekende metrics tellen niet mee en verlagen de dekking (coverage). Is de dekking
    lager dan min_cov, dan is de categoriescore None (onvoldoende data)."""
    total = sum(w for w in weights.values() if w > 0)
    got = acc = 0.0
    detail = {}
    for m, w in weights.items():
        if w <= 0:
            continue
        if forced.get(m) is not None:
            s = forced[m]
        else:
            v = vals.get(m)
            s = None if v is None else lin(v, *norms[m])
        detail[m] = {"value": rnd(vals.get(m)), "score": s, "weight": w}
        if s is not None:
            got += w
            acc += s * w
    cov = got / total if total else 0.0
    score = round(acc / got, 2) if got and cov >= min_cov else None
    return {"score": score, "coverage": round(cov, 3), "metrics": detail}
