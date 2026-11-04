"""Growth (20%): historische groei (3/5 jaar) én verwachte groei, plus consistentie.

Structurele winstgroei (omzet én winst groeien elk jaar) scoort hoger dan tijdelijke omzetgroei."""
from .sectors import norms_for, weights_for
from .series import ser, span_cagr, yoy
from .util import at, score_category


def _growth_or_collapse(values, yrs, vals, forced, key):
    """CAGR; is de reeks van winst naar verlies gegaan, dan score 0 (echte verslechtering)."""
    new, old = at(values, 0), at(values, yrs)
    if new is None or old is None:
        return
    g = span_cagr(values, yrs)
    if g is not None:
        vals[key] = g
    elif new <= 0 < old:
        forced[key] = 0.0
    # verlies -> winst: groei niet te berekenen, blijft ontbreken


def values(fin):
    vals, forced, notes = {}, {}, []
    rev, eps = ser(fin, "revenue"), ser(fin, "diluted_eps")
    if not any(x is not None for x in eps):
        eps = ser(fin, "net_income")
        notes.append("winst per aandeel ontbreekt: nettowinst gebruikt")
    _growth_or_collapse(rev, 3, vals, forced, "rev3")
    _growth_or_collapse(rev, 5, vals, forced, "rev5")
    _growth_or_collapse(eps, 3, vals, forced, "eps3")
    _growth_or_collapse(eps, 5, vals, forced, "eps5")
    _growth_or_collapse(ser(fin, "fcf"), 3, vals, forced, "fcf_g")
    _growth_or_collapse(ser(fin, "operating_income"), 3, vals, forced, "opinc_g")
    _growth_or_collapse(ser(fin, "equity"), 3, vals, forced, "bv_g")
    if fin["profile"] == "reit":
        _growth_or_collapse(ser(fin, "ffo"), 3, vals, forced, "ffo_g")
    divs = [None if d is None else abs(d) for d in ser(fin, "dividends_paid")]
    _growth_or_collapse(divs, 3, vals, forced, "div_g")
    vals["fwd_rev"] = fin["est"].get("fwd_rev")
    vals["fwd_eps"] = fin["est"].get("fwd_eps")
    if "rev5" not in vals and "rev5" not in forced:
        notes.append("5-jaarsgroei niet beschikbaar (bron levert ~4 boekjaren)")
    # Consistentie: aandeel jaren waarin omzet en winst(per aandeel) groeiden
    ups = [g for g in yoy(rev) + yoy(eps) if g is not None]
    if len(ups) >= 4:
        vals["consistency"] = sum(1 for g in ups if g > 0) / len(ups)
    return vals, forced, notes


def evaluate(fin, ctx=None):
    prof = fin["profile"]
    vals, forced, notes = values(fin)
    res = score_category(vals, forced, weights_for(prof)["growth"], norms_for(prof))
    res["notes"] = notes
    return res
