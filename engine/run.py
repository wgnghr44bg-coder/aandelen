"""Analyseert het hele universum: eerst per aandeel de basisgegevens, dan sectorvergelijking,
daarna de scores, de intrinsieke waarde en het advies."""
from . import dcf as dcf_mod
from . import growth, health, moat, profitability, valuation
from .decision import decide
from .scoring import fundamental_score
from .series import roe_series, ser, span_cagr
from .util import avail, mean, median, rnd

MIN_PEERS = 4


def build_context(fins):
    ctx = {"sector_medians": {}, "revenue_rank": {}, "eps3": {}, "roe_avg": {}, "cost_of_equity": {}}
    by_prof = {}
    for t, f in fins.items():
        by_prof.setdefault(f["profile"], []).append(t)
        if f["years"]:
            ctx["eps3"][t] = span_cagr(ser(f, "diluted_eps"), 3)
            r = avail(roe_series(f)[:3])
            ctx["roe_avg"][t] = mean(r) if len(r) >= 3 else None
            ctx["cost_of_equity"][t] = dcf_mod.cost_of_equity(f)[0]
    for prof, ts in by_prof.items():
        mults = {t: valuation.multiples(fins[t]) for t in ts if not fins[t]["issues"]}
        med = {}
        for k in ("pe", "ev_ebitda", "pfcf", "pb", "p_ffo"):
            vals = [m[k] for m in mults.values() if m.get(k) and m[k] > 0]
            if len(vals) >= MIN_PEERS:
                med[k] = median(vals)
        ctx["sector_medians"][prof] = med
        revs = sorted((f["s"].get("revenue") or [None])[0] or 0 for f in (fins[t] for t in ts)
                      if f["s"].get("revenue") and f["s"]["revenue"][0])
        if len(revs) >= MIN_PEERS:
            for t in ts:
                r0 = (fins[t]["s"].get("revenue") or [None])[0]
                if r0:
                    ctx["revenue_rank"][t] = sum(1 for x in revs if x <= r0) / len(revs)
    return ctx


def analyze(fin, ctx):
    cats = {
        "health": health.evaluate(fin, ctx),
        "profitability": profitability.evaluate(fin, ctx),
        "growth": growth.evaluate(fin, ctx),
        "valuation": valuation.evaluate(fin, ctx),
        "moat": moat.evaluate(fin, ctx),
    }
    fundamental = fundamental_score(cats)
    d = dcf_mod.run(fin) if not fin["issues"] else {"valid": False, "reason": "datakwaliteit", "scenarios": {}}
    dec = decide(fin, cats, fundamental, d)
    return {
        "ticker": fin["ticker"], "profile": fin["profile"], "rating": dec["rating"],
        "reasons": dec["reasons"], "flags": dec.get("flags", []), "checks": dec.get("checks", {}),
        "fundamental_score": fundamental,
        "categories": cats, "dcf": d,
        "data": {"dates": fin["dates"], "years": fin["years"], "currency": fin["currency"],
                 "financial_currency": fin["fin_currency"], "fx": rnd(fin["fx"], 6),
                 "issues": fin["issues"], "notes": fin["notes"], "price": fin["price"],
                 "market_cap": rnd(fin["mcap"], 0)},
    }


def analyze_universe(fins):
    """fins: {ticker: genormaliseerde data}. Geeft {ticker: volledige analyse}."""
    ctx = build_context(fins)
    return {t: analyze(f, ctx) for t, f in sorted(fins.items())}
