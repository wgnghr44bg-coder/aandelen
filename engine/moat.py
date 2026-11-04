"""Competitive Advantage (15%): stabiliteit van marges en rendementen, prijszettingsmacht,
omzetstabiliteit en marktpositie.

Merksterkte en kwalitatieve 'moat'-oordelen zijn niet als onderbouwde data beschikbaar en worden
daarom niet verzonnen: ze tellen niet mee."""
from .sectors import norms_for, weights_for
from .series import margin, roe_series, roic_series, ser, yoy
from .util import at, avail, mean, score_category, stdev


def values(fin, ctx=None):
    ctx = ctx or {}
    vals, forced = {}, {}
    notes = ["merksterkte/kwalitatieve moat: geen onderbouwde data, niet meegeteld"]
    gm, om, nm = margin(fin, "gross_profit"), margin(fin, "operating_income"), margin(fin, "net_income")
    roic, roe = roic_series(fin), roe_series(fin)
    vals["gm_level"] = mean(gm)
    vals["gm_stab"] = stdev(gm)
    vals["om_stab"] = stdev(om)
    vals["nm_stab"] = stdev(nm)
    r = avail(roic)
    vals["roic_min"] = min(r) if len(r) >= 3 else None
    vals["roic_stab"] = stdev(roic)
    e = avail(roe)
    vals["roe_min"] = min(e) if len(e) >= 3 else None
    vals["roe_stab"] = stdev(roe)
    g = yoy(ser(fin, "revenue"))
    vals["rev_stab"] = stdev(g)
    known = avail(g)
    vals["rev_decl"] = sum(1 for x in known if x < 0) if len(known) >= 3 else None
    # Prijszettingsmacht: brutomarge stabiel of stijgend over de periode
    gms = avail(gm)
    if len(gms) >= 3 and at(gm, 0) is not None:
        vals["pricing"] = at(gm, 0) - gms[-1]
    if fin["profile"] == "reit":
        vals["ffo_stab"] = stdev(margin(fin, "ffo"))
    vals["market_pos"] = ctx.get("revenue_rank", {}).get(fin["ticker"])
    return vals, forced, notes


def evaluate(fin, ctx=None):
    prof = fin["profile"]
    vals, forced, notes = values(fin, ctx)
    res = score_category(vals, forced, weights_for(prof)["moat"], norms_for(prof))
    res["notes"] = notes
    return res
