"""Afgeleide reeksen per jaar (nieuwste eerst). Alle functies geven None waar data ontbreekt."""
from .util import at, div, num


def ser(fin, key):
    return fin["s"].get(key) or [None] * len(fin["years"])


def ratio_series(fin, a, b, positive_den=True):
    out = []
    for x, y in zip(ser(fin, a), ser(fin, b)):
        if y is None or (positive_den and y <= 0):
            out.append(None)
        else:
            out.append(div(x, y))
    return out


def roic_series(fin):
    """ROIC = EBIT × (1 − belasting) / (eigen vermogen + schuld − kas)."""
    out = []
    ebit, tax = ser(fin, "ebit"), ser(fin, "tax_rate")
    eq, debt, cash = ser(fin, "equity"), ser(fin, "total_debt"), ser(fin, "cash")
    for i in range(len(fin["years"])):
        e, t = num(ebit[i]), num(tax[i])
        if e is None or t is None or eq[i] is None or debt[i] is None or cash[i] is None:
            out.append(None)
            continue
        ic = eq[i] + debt[i] - cash[i]
        out.append(e * (1 - t) / ic if ic > 0 else None)
    return out


def roe_series(fin):
    return ratio_series(fin, "net_income", "equity")


def margin(fin, key):
    return ratio_series(fin, key, "revenue")


def yoy(values):
    """Groei per jaar: element i = groei van jaar i t.o.v. jaar i+1 (alleen bij positieve basis)."""
    out = []
    for i in range(len(values) - 1):
        a, b = num(values[i]), num(values[i + 1])
        out.append(None if (a is None or b is None or b <= 0) else a / b - 1)
    return out


def span_cagr(values, years):
    """CAGR over precies `years` jaar (element 0 t.o.v. element `years`)."""
    from .util import cagr
    return cagr(at(values, 0), at(values, years), years)
