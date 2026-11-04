"""Buy / Hold / Sell Decision Engine.

Volgorde:
 1. NO RATING bij onvoldoende of verouderde data (betrouwbaarheid gaat voor alles).
 2. SELL bij structurele verslechtering, zwakke financiële gezondheid of extreme overwaardering.
    Overwaardering alléén is geen SELL: een sterk bedrijf boven zijn intrinsieke waarde wordt HOLD.
 3. NO RATING als de intrinsieke waarde niet betrouwbaar te berekenen is (en er geen SELL-reden is).
 4. BUY alleen als álle kwaliteitseisen, de waardering én de veiligheidsmarge (≥ 20%) kloppen.
 5. Anders HOLD.
"""
from .series import margin, roe_series, roic_series, ser
from .util import at, div, mean

BUY_MIN = {"fundamental": 65, "health": 55, "profitability": 55, "growth": 45, "valuation": 45, "moat": 40}
BUY_MIN_COVERAGE = 0.65
BUY_MIN_MOS = 0.20
BUY_MIN_CONSERVATIVE_UPSIDE = -0.10


def deterioration_flags(fin, cats):
    """Signalen van structurele (niet tijdelijke) verslechtering, op basis van meerjarige cijfers."""
    flags = []
    s = lambda k: ser(fin, k)  # noqa: E731
    roic = roic_series(fin)
    r0, r_old = at(roic, 0), mean(roic[1:])
    if r0 is not None and r_old and r_old > 0 and r0 < 0.6 * r_old and r0 < 0.10:
        flags.append("ROIC verslechtert structureel")
    roe = roe_series(fin)
    e0, e_old = at(roe, 0), mean(roe[1:])
    if fin["profile"] == "bank" and e0 is not None and e_old and e_old > 0 and e0 < 0.5 * e_old and e0 < 0.08:
        flags.append("ROE verslechtert structureel")
    fcf = s("fcf")
    if fin["profile"] not in ("bank", "utility", "reit"):
        f0, f_prev = at(fcf, 0), mean(fcf[1:3])
        if f0 is not None and f_prev is not None and f0 < 0 < f_prev:
            flags.append("vrije kasstroom negatief geworden")
        fm = margin(fin, "fcf")
        m0, m_old = at(fm, 0), mean(fm[1:])
        if m0 is not None and m_old and m_old > 0.04 and m0 < 0.5 * m_old:
            flags.append("vrije-kasstroommarge meer dan gehalveerd")
    om = margin(fin, "operating_income")
    o0, o_old = at(om, 0), mean(om[1:])
    if o0 is not None and o_old is not None and o0 < o_old - 0.05:
        flags.append("operationele marge daalt sterk")
    rev = s("revenue")
    if all(at(rev, i) is not None for i in range(3)) and rev[0] < rev[1] < rev[2]:
        flags.append("omzet krimpt al twee jaar")
    ni = s("net_income")
    if at(ni, 0) is not None and at(ni, 1) is not None and ni[0] < 0 < ni[1]:
        flags.append("omgeslagen naar verlies")
    debt, cash, ebitda = s("total_debt"), s("cash"), s("ebitda")

    def nde(i):
        if at(debt, i) is None or at(cash, i) is None or not at(ebitda, i) or ebitda[i] <= 0:
            return None
        return (debt[i] - cash[i]) / ebitda[i]
    n0, n2 = nde(0), nde(2)
    limit = 7.0 if fin["profile"] in ("utility", "reit") else 4.0
    if n0 is not None and n2 is not None and n0 > limit and n0 - n2 > 1.5:
        flags.append("schuld loopt snel op")
    ic = div(at(s("ebit"), 0), abs(at(s("interest_expense"), 0) or 0) or None)
    if fin["profile"] not in ("bank",) and ic is not None and ic < 2:
        flags.append("rentedekking zwak (< 2×)")
    fwd = fin["est"].get("fwd_eps")
    if fwd is not None and fwd < -0.10:
        flags.append("verwachte winst daalt > 10%")
    return flags


def decide(fin, cats, fundamental, dcf):
    reasons = []
    checks = {}
    if fin["issues"]:
        return {"rating": "NO RATING", "reasons": list(fin["issues"]), "flags": [], "checks": checks}
    missing = [c for c, v in cats.items() if v.get("score") is None]
    if missing or fundamental is None:
        return {"rating": "NO RATING", "flags": [], "checks": checks,
                "reasons": [f"onvoldoende data voor: {', '.join(missing)}"]}

    sc = {c: v["score"] for c, v in cats.items()}
    flags = deterioration_flags(fin, cats)
    neu = (dcf.get("scenarios") or {}).get("neutral") or {}
    opt = (dcf.get("scenarios") or {}).get("optimistic") or {}
    con = (dcf.get("scenarios") or {}).get("conservative") or {}

    # --- SELL
    # Extreme overwaardering is alleen een SELL-reden als het bedrijf niet uitzonderlijk sterk presteert:
    # een topbedrijf dat (te) duur is, is overgewaardeerd maar fundamenteel niet slecht -> HOLD.
    exceptional = sc["profitability"] >= 70 and sc["growth"] >= 60 and sc["health"] >= 50 and not flags
    extreme_over = (dcf.get("valid") and opt.get("upside") is not None and opt["upside"] < -0.50
                    and sc["valuation"] < 25 and not exceptional)
    if len(flags) >= 2 and fundamental < 50:
        reasons.append("structurele verslechtering: " + "; ".join(flags))
    if sc["health"] < 25:
        reasons.append("financiële gezondheid zeer zwak")
    if fundamental < 35:
        reasons.append("fundamentele kwaliteit zeer zwak")
    if extreme_over:
        reasons.append("extreem overgewaardeerd: zelfs optimistisch scenario > 50% onder de koers, "
                       "zonder uitzonderlijke kwaliteit/groei")
    if reasons:
        return {"rating": "SELL", "reasons": reasons, "flags": flags, "checks": checks}

    # --- NO RATING als intrinsieke waarde onbetrouwbaar is
    if not dcf.get("valid"):
        return {"rating": "NO RATING", "flags": flags, "checks": checks,
                "reasons": [f"intrinsieke waarde niet betrouwbaar: {dcf.get('reason')}"]}

    # --- BUY: alle eisen moeten kloppen
    checks = {
        "fundamental": fundamental >= BUY_MIN["fundamental"],
        **{c: sc[c] >= BUY_MIN[c] for c in ("health", "profitability", "growth", "valuation", "moat")},
        "coverage": all(v["coverage"] >= BUY_MIN_COVERAGE for v in cats.values()),
        "margin_of_safety": (neu.get("margin_of_safety") or -1) >= BUY_MIN_MOS,
        "conservative_scenario": (con.get("upside") is not None and con["upside"] >= BUY_MIN_CONSERVATIVE_UPSIDE),
        "no_deterioration": not flags,
        "forward_outlook": (fin["est"].get("fwd_eps") is None or fin["est"]["fwd_eps"] >= 0),
        "sector_valuation": _sector_ok(cats),
        "positive_growth": _growth_positive(cats),
    }
    if all(checks.values()):
        return {"rating": "BUY", "flags": flags, "checks": checks,
                "reasons": [f"sterke fundamenten ({fundamental:.0f}/100) en veiligheidsmarge "
                            f"{neu['margin_of_safety']:.0%}"]}

    failed = [k for k, ok in checks.items() if not ok]
    return {"rating": "HOLD", "flags": flags, "checks": checks,
            "reasons": ["niet alle koopvoorwaarden: " + ", ".join(failed)]}


def _sector_ok(cats):
    m = cats["valuation"]["metrics"].get("sector_rel")
    return m is None or m["score"] is None or m["score"] >= 35


def _growth_positive(cats):
    g = cats["growth"]["metrics"]
    rev = (g.get("rev3") or {}).get("value")
    eps = (g.get("eps3") or {}).get("value")
    fwd = (g.get("fwd_eps") or {}).get("value")
    if rev is None or rev <= 0:
        return False
    return (eps is not None and eps > 0) or (fwd is not None and fwd > 0)
