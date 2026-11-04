"""Profitability (20%): rendementen en marges, met nadruk op structureel niveau (3–5 jaar)."""
from .sectors import norms_for, weights_for
from .series import margin, ratio_series, roe_series, roic_series, ser
from .util import at, mean, score_category


def level(series):
    """Structureel niveau: half het laatste jaar, half het gemiddelde over alle beschikbare jaren."""
    last, avg = at(series, 0), mean(series)
    if last is None or avg is None:
        return None
    return 0.5 * last + 0.5 * avg


def trend(series):
    """Laatste jaar t.o.v. het gemiddelde van de eerdere jaren (procentpunten)."""
    last, older = at(series, 0), mean(series[1:])
    if last is None or older is None or len([x for x in series[1:] if x is not None]) < 2:
        return None
    return last - older


def values(fin):
    vals, forced, notes = {}, {}, []
    roic, roe = roic_series(fin), roe_series(fin)
    roa = ratio_series(fin, "net_income", "total_assets")
    vals["roic"] = level(roic)
    vals["roe"] = level(roe)
    if vals["roe"] is None and at(ser(fin, "equity"), 0) is not None and at(ser(fin, "equity"), 0) <= 0:
        notes.append("negatief eigen vermogen: ROE niet zinvol")
    vals["roa"] = level(roa)
    vals["gm"] = level(margin(fin, "gross_profit"))
    vals["om"] = level(margin(fin, "operating_income"))
    vals["nm"] = level(margin(fin, "net_income"))
    vals["fcfm"] = level(margin(fin, "fcf"))
    vals["roic_trend"] = trend(roic)
    vals["roe_trend"] = trend(roe)
    if fin["profile"] == "reit":
        vals["ffo_margin"] = level(margin(fin, "ffo"))
    return vals, forced, notes


def evaluate(fin, ctx=None):
    prof = fin["profile"]
    vals, forced, notes = values(fin)
    res = score_category(vals, forced, weights_for(prof)["profitability"], norms_for(prof))
    res["notes"] = notes
    return res
