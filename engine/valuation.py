"""Valuation (25%): multiples, vergeleken met normen per sector, de eigen historie en sectorgenoten.

Een lage P/E is niet automatisch goedkoop: daarom tellen ook PEG, P/FCF, EV-multiples,
de historische waardering en de vergelijking met sectorgenoten mee."""
from .sectors import DEFAULT_SECTOR_MULTIPLES, SECTOR_MULTIPLES, norms_for, weights_for
from .series import ser
from .util import at, div, geomean_ratio, median, score_category

RELEVANT_DIVIDEND = {"utility", "reit", "bank", "cons_def", "telecom", "cyclical"}


def enterprise_value(fin):
    mcap = fin["mcap"]
    debt, cash = at(ser(fin, "total_debt"), 0), at(ser(fin, "cash"), 0)
    if mcap is None or debt is None or cash is None:
        return None
    mi = at(ser(fin, "minority_interest"), 0) or 0.0
    return mcap + debt - cash + mi


def multiples(fin):
    """Huidige multiples. Negatieve noemer (verlies, negatieve FCF) -> None (apart afgehandeld)."""
    mcap, s = fin["mcap"], (lambda k: ser(fin, k))
    ev = enterprise_value(fin)

    def pos(a, b):
        return div(a, b) if (b is not None and b > 0) else None

    m = {
        "pe": fin["info"].get("trailing_pe") or pos(mcap, at(s("net_income"), 0)),
        "fpe": fin["info"].get("forward_pe"),
        "ps": pos(mcap, at(s("revenue"), 0)),
        "pb": pos(mcap, at(s("equity"), 0)),
        "pfcf": pos(mcap, at(s("fcf"), 0)),
        "ev_ebitda": pos(ev, at(s("ebitda"), 0)),
        "ev_ebit": pos(ev, at(s("ebit"), 0)),
        "p_ffo": pos(mcap, at(s("ffo"), 0)) if fin["profile"] == "reit" else None,
    }
    return m


def _hist_ratio(fin, den_key):
    """Huidige multiple / mediaan van eigen historische multiple (op boekjaareinde)."""
    den = ser(fin, den_key)
    cur = div(fin["mcap"], at(den, 0)) if (at(den, 0) or 0) > 0 else None
    hist = [div(fin["hist_mcap"][i], den[i]) for i in range(1, len(den))
            if i < len(fin["hist_mcap"]) and fin["hist_mcap"][i] and den[i] and den[i] > 0]
    if cur is None or len(hist) < 2:
        return None
    return cur / median(hist)


def values(fin, ctx=None):
    ctx = ctx or {}
    prof = fin["profile"]
    vals, forced, notes = {}, {}, []
    m = multiples(fin)
    s = lambda k: ser(fin, k)  # noqa: E731
    ni0, fcf0, ebitda0 = at(s("net_income"), 0), at(s("fcf"), 0), at(s("ebitda"), 0)

    vals.update({k: m[k] for k in ("pe", "fpe", "ps", "pb", "pfcf", "ev_ebitda", "ev_ebit", "p_ffo")})
    # Verlies / negatieve kasstroom: geen waarderingssteun -> score 0 (geen ontbrekende waarde)
    if vals["pe"] is None and ni0 is not None and ni0 <= 0:
        forced["pe"] = 0.0
        notes.append("verlieslatend: P/E niet zinvol, score 0")
    fe = fin["info"].get("forward_eps")
    if vals["fpe"] is None and fe is not None and fe <= 0:
        forced["fpe"] = 0.0
    if vals["pfcf"] is None and fcf0 is not None and fcf0 <= 0:
        forced["pfcf"] = 0.0
    if vals["ev_ebitda"] is None and ebitda0 is not None and ebitda0 <= 0:
        forced["ev_ebitda"] = 0.0

    # PEG = P/E / verwachte winstgroei (%); alleen bij positieve groei
    growth = median([fin["est"].get("fwd_eps"), ctx.get("eps3", {}).get(fin["ticker"])])
    pe_for_peg = vals["fpe"] or vals["pe"]
    if pe_for_peg and growth is not None:
        if growth > 0.01:
            vals["peg"] = pe_for_peg / (min(growth, 0.5) * 100)
        else:
            notes.append("PEG niet zinvol (geen winstgroei verwacht)")

    # Dividendrendement (alleen in sectoren waar dat relevant is)
    d0 = at(s("dividends_paid"), 0)
    if prof in RELEVANT_DIVIDEND and d0 is not None and fin["mcap"]:
        vals["div_yield"] = abs(d0) / fin["mcap"]

    # Bank: P/B t.o.v. gerechtvaardigde P/B = (ROE − g) / (r − g)
    if prof == "bank" and vals.get("pb"):
        roe = ctx.get("roe_avg", {}).get(fin["ticker"])
        r = ctx.get("cost_of_equity", {}).get(fin["ticker"])
        g = 0.025
        if roe is not None and r is not None and r > g and roe > g:
            vals["pb_just"] = vals["pb"] / ((roe - g) / (r - g))

    # Historische waardering
    hist_keys = {"bank": [("net_income",), ("equity",)], "reit": [("ffo",)]}.get(prof, [("net_income",), ("fcf",)])
    vals["hist_rel"] = geomean_ratio([_hist_ratio(fin, k[0]) for k in hist_keys])

    # Sectorvergelijking (mediaan van sectorgenoten in het universum)
    med = ctx.get("sector_medians", {}).get(prof, {})
    keys = SECTOR_MULTIPLES.get(prof, DEFAULT_SECTOR_MULTIPLES)
    ratios = [div(m.get(k), med.get(k)) for k in keys if m.get(k) and med.get(k)]
    vals["sector_rel"] = geomean_ratio(ratios)
    return vals, forced, notes


def evaluate(fin, ctx=None):
    prof = fin["profile"]
    vals, forced, notes = values(fin, ctx)
    res = score_category(vals, forced, weights_for(prof)["valuation"], norms_for(prof))
    res["notes"] = notes
    return res
