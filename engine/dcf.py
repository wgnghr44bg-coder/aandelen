"""Intrinsieke waarde: DCF op vrije kasstroom (5 jaar + terminal value), met drie scenario's.

Formules (zoals gevraagd):
  PV             = FCF_t / (1 + r)^t
  Terminal Value = FCF_5 × (1 + g_T) / (r − g_T)
  EV             = Σ PV(FCF) + PV(TV)
  Equity         = EV − netto schuld (− minderheidsbelangen)
  Intrinsiek/aandeel = Equity / diluted shares

Voor sectoren waar een FCF-DCF economisch niet past, hetzelfde 5-jaars + terminal-raamwerk op de
kasstroom naar aandeelhouders:
  - nutsbedrijven en vastgoed: dividend discount (FCF structureel negatief door investeringen)
  - banken/verzekeraars:       residual income (geen zinvolle vrije kasstroom of netto schuld)

Aannames:
  - disconteringsvoet: CAPM (r_f + Blume-gecorrigeerde β × 4,5% marktpremie), voor FCF-DCF gewogen tot WACC
  - terminal groei 2,0 / 2,5 / 3,0% (conservatief / neutraal / optimistisch), lange-termijn nominale
    groei van ontwikkelde economieën; altijd minimaal 3%-punt onder de disconteringsvoet
  - groei jaar 1 = mediaan van historische FCF-groei, omzetgroei en analistenverwachtingen,
    begrensd; daalt lineair naar halverwege de terminal groei in jaar 5
  - stock-based compensation telt als kosten: conservatief 100%, neutraal 50%, optimistisch 0%
  - groei nooit hoger dan de analistenverwachting (indien beschikbaar)
  - vrije kasstroom max. 1,5× de gemiddelde winst (kasstroomkwaliteit)
  - landenrisicopremie voor bedrijven die in de valuta van een opkomende markt rapporteren
"""
from .sectors import CYCLICAL, MODEL
from .series import roe_series, ser, span_cagr
from .util import at, avail, clamp, div, mean, median, num, rnd

ERP = 0.045  # impliciete aandelenrisicopremie (Damodaran ~4,3–4,6%)

# Landenrisicopremie op basis van de rapportagevaluta (benadering van Damodaran's country risk premiums).
# Ontwikkelde markten: 0. Opkomende markten: extra opslag op de disconteringsvoet.
COUNTRY_RISK = {"CNY": 0.010, "HKD": 0.008, "INR": 0.020, "BRL": 0.030, "MXN": 0.025, "IDR": 0.022,
                "ZAR": 0.035, "TRY": 0.045, "ARS": 0.080, "KRW": 0.006, "TWD": 0.006, "SAR": 0.009,
                "AED": 0.008, "QAR": 0.008, "THB": 0.015, "MYR": 0.012, "PHP": 0.020, "CLP": 0.010,
                "COP": 0.025, "PLN": 0.008}
MAX_FCF_TO_EARNINGS = 1.5  # vrije kasstroom hoger dan 1,5× de gemiddelde winst = begrensd
DEFAULT_RF = 0.0425
YEARS = 5

SCENARIOS = {
    "conservative": {"dg": -0.04, "dr": 0.01, "tg": 0.020, "sbc": 1.0, "roe_fade": 1.0},
    "neutral": {"dg": 0.0, "dr": 0.0, "tg": 0.025, "sbc": 0.5, "roe_fade": 0.5},
    "optimistic": {"dg": 0.03, "dr": -0.01, "tg": 0.030, "sbc": 0.0, "roe_fade": 0.0},
}


def cost_of_equity(fin, notes=None):
    rf = num(fin.get("rf"))
    if rf is None:
        rf = DEFAULT_RF
        if notes is not None:
            notes.append(f"risicovrije rente onbekend: {DEFAULT_RF:.2%} aangenomen")
    beta = num(fin.get("beta"))
    if beta is None:
        beta = 1.0
        if notes is not None:
            notes.append("bèta onbekend: 1,0 aangenomen")
    # Blume-correctie: bèta's neigen op termijn naar 1 (0,67 × β + 0,33)
    adj = clamp(0.67 * beta + 0.33, 0.8, 1.6)
    crp = COUNTRY_RISK.get(fin.get("fin_currency"), 0.0)
    if crp and notes is not None:
        notes.append(f"landenrisicopremie {crp:.1%} ({fin.get('fin_currency')})")
    return max(rf + adj * ERP + crp, 0.07), rf, adj


def wacc(fin, re, notes):
    debt, mcap = at(ser(fin, "total_debt"), 0), fin.get("mcap")
    ie, tax = at(ser(fin, "interest_expense"), 0), at(ser(fin, "tax_rate"), 0)
    if not debt or not mcap or debt <= 0:
        return re
    rd = clamp(abs(ie) / debt, 0.02, 0.10) if ie else 0.05
    t = tax if tax is not None else 0.21
    if ie is None or tax is None:
        notes.append("rente of belasting onbekend: kostenvoet schuld 5% / belasting 21% aangenomen")
    w = (mcap * re + debt * rd * (1 - t)) / (mcap + debt)
    return max(w, 0.07)


def _fade(g1, tg, t):
    """Groei daalt lineair van g1 (jaar 1) naar halverwege g1 en de terminal groei (jaar 5);
    daarna geldt de terminal groei."""
    end = (g1 + tg) / 2
    return g1 + (end - g1) * (t - 1) / (YEARS - 1)


def _growth_start(cands, forward=()):
    """Mediaan van alle groei-inputs, maar nooit hoger dan wat analisten verwachten (als die er zijn):
    historische groei wordt niet zomaar doorgetrokken bij een bedrijf dat afremt."""
    v = [clamp(c, -0.10, 0.30) for c in avail(cands)]
    g = median(v)
    fwd = avail(forward)
    if g is not None and fwd:
        g = min(g, max(fwd))
    return g, len(v)


def _per_share(fin, equity):
    price, mcap = fin.get("price"), fin.get("mcap")
    if equity is None or not price or not mcap:
        return None, None, None, None
    if fin.get("shares_ok") and fin.get("diluted_shares"):
        ips = equity / fin["diluted_shares"]
        method = "diluted shares"
    else:
        ips = price * equity / mcap
        method = "beurswaarde-verhouding"
    upside = (ips / price - 1) if price else None
    mos = (ips - price) / ips if ips and ips > 0 else None
    return ips, upside, mos, method


def _scenario_result(fin, equity, extra):
    ips, upside, mos, method = _per_share(fin, equity)
    out = {"equity_value": rnd(equity, 0), "intrinsic_per_share": rnd(ips, 2),
           "upside": rnd(upside), "margin_of_safety": rnd(mos), "per_share_method": method}
    out.update(extra)
    return out


def _fcf_model(fin, sc, notes):
    s = lambda k: ser(fin, k)  # noqa: E731
    fcf, sbc = s("fcf"), s("sbc")
    f0 = at(fcf, 0)
    recent = avail(fcf[:3])
    if f0 is None or len(recent) < 2:
        return None, "te weinig kasstroomdata"
    if f0 <= 0 or mean(recent) <= 0:
        return None, "negatieve vrije kasstroom: DCF niet betrouwbaar"
    if fin["profile"] in CYCLICAL:
        base = mean(fcf[:4])
        basis = "gemiddelde FCF (cyclisch genormaliseerd)"
    else:
        w = [0.5, 0.3, 0.2]
        pairs = [(fcf[i], w[i]) for i in range(min(3, len(fcf))) if fcf[i] is not None]
        base = sum(v * ww for v, ww in pairs) / sum(ww for _, ww in pairs)
        basis = "gewogen FCF laatste 3 jaar (50/30/20)"
    # Kasstroomkwaliteit: is de vrije kasstroom structureel veel hoger dan de winst (bv. klantgeld bij
    # betaal-/fintechbedrijven of tijdelijk werkkapitaal), dan begrenzen op 1,5× de gemiddelde winst.
    ni_avg = mean(s("net_income")[:3])
    if ni_avg is not None and ni_avg > 0 and base > MAX_FCF_TO_EARNINGS * ni_avg:
        notes.append(f"vrije kasstroom {base / ni_avg:.1f}× de winst: begrensd op {MAX_FCF_TO_EARNINGS}×")
        base = MAX_FCF_TO_EARNINGS * ni_avg
        basis += f", begrensd op {MAX_FCF_TO_EARNINGS}× gemiddelde winst"
    sbc0 = at(sbc, 0)
    if sbc0 is None:
        sbc0 = 0.0
    base -= sc["sbc"] * abs(sbc0)
    if base <= 0:
        return None, "kasstroom na SBC niet positief"

    debt, cash = at(s("total_debt"), 0), at(s("cash"), 0)
    if debt is None or cash is None:
        return None, "schuld of kaspositie ontbreekt"
    mi = at(s("minority_interest"), 0) or 0.0
    if (fin.get("industry") or "").startswith("Financial Data & Stock Exchanges"):
        # Beurzen/clearinghuizen: de kas op de balans is grotendeels onderpand van clearingleden,
        # geen eigen vrij geld. Daarom niet aftrekken van de schuld.
        cash = 0.0
        notes.append("beurs/clearinghuis: kas = onderpand van klanten, niet meegeteld")

    re, rf, beta = cost_of_equity(fin, notes)
    r = max(wacc(fin, re, notes) + sc["dr"], 0.07)
    tg = min(sc["tg"], r - 0.03)
    fwd = [fin["est"].get("fwd_rev"), fin["est"].get("fwd_eps")]
    g1, n = _growth_start([span_cagr(fcf, 3), span_cagr(s("revenue"), 3)] + fwd, fwd)
    if g1 is None:
        return None, "geen groeigegevens voor prognose"
    g1 = clamp(clamp(g1, -0.05, 0.25) + sc["dg"], -0.08, 0.30)

    flows, pv, f = [], 0.0, base
    for t in range(1, YEARS + 1):
        g = _fade(g1, tg, t)
        f *= 1 + g
        flows.append(round(f, 0))
        pv += f / (1 + r) ** t
    tv = f * (1 + tg) / (r - tg)
    pv_tv = tv / (1 + r) ** YEARS
    ev = pv + pv_tv
    equity = ev - (debt - cash) - mi
    return _scenario_result(fin, equity, {
        "model": "DCF (vrije kasstroom)", "discount_rate": rnd(r), "terminal_growth": rnd(tg),
        "growth_y1": rnd(g1), "growth_inputs": n, "base_fcf": rnd(base, 0), "fcf_basis": basis,
        "sbc_deducted": rnd(sc["sbc"] * abs(sbc0), 0), "forecast_fcf": flows,
        "pv_forecast": rnd(pv, 0), "terminal_value": rnd(tv, 0), "pv_terminal": rnd(pv_tv, 0),
        "terminal_share": rnd(div(pv_tv, ev)), "enterprise_value": rnd(ev, 0),
        "net_debt": rnd(debt - cash, 0), "minority_interest": rnd(mi, 0),
        "cost_of_equity": rnd(re), "risk_free": rnd(rf), "beta": rnd(beta),
    }), None


def _ddm_model(fin, sc, notes):
    s = lambda k: ser(fin, k)  # noqa: E731
    divs = [None if d is None else abs(d) for d in s("dividends_paid")]
    d0 = at(divs, 0)
    if d0 is None or d0 <= 0 or len([d for d in divs if d]) < 3:
        return None, "te weinig dividendhistorie voor dividendmodel"
    re, rf, beta = cost_of_equity(fin, notes)
    r = max(re + sc["dr"], 0.07)
    tg = min(sc["tg"], r - 0.03)
    eps = s("ffo") if fin["profile"] == "reit" else s("diluted_eps")
    g1, n = _growth_start([span_cagr(divs, 3), span_cagr(eps, 3), fin["est"].get("fwd_eps")],
                          [fin["est"].get("fwd_eps")])
    if g1 is None:
        return None, "geen groeigegevens voor prognose"
    g1 = clamp(clamp(g1, 0.0, 0.07) + sc["dg"] * 0.5, -0.02, 0.09)
    flows, pv, d = [], 0.0, d0
    for t in range(1, YEARS + 1):
        g = _fade(g1, tg, t)
        d *= 1 + g
        flows.append(round(d, 0))
        pv += d / (1 + r) ** t
    tv = d * (1 + tg) / (r - tg)
    pv_tv = tv / (1 + r) ** YEARS
    equity = pv + pv_tv
    return _scenario_result(fin, equity, {
        "model": "Dividend discount", "discount_rate": rnd(r), "terminal_growth": rnd(tg),
        "growth_y1": rnd(g1), "growth_inputs": n, "base_dividends": rnd(d0, 0), "forecast": flows,
        "pv_forecast": rnd(pv, 0), "terminal_value": rnd(tv, 0), "pv_terminal": rnd(pv_tv, 0),
        "terminal_share": rnd(div(pv_tv, equity)), "risk_free": rnd(rf), "beta": rnd(beta),
    }), None


def _ri_model(fin, sc, notes):
    s = lambda k: ser(fin, k)  # noqa: E731
    bv0 = at(s("equity"), 0)
    roes = avail(roe_series(fin)[:3])
    ni0, d0 = at(s("net_income"), 0), at(s("dividends_paid"), 0)
    if bv0 is None or bv0 <= 0 or len(roes) < 3:
        return None, "te weinig gegevens voor residual-incomemodel"
    if ni0 is None or ni0 <= 0:
        return None, "verlieslatend: residual-incomemodel niet betrouwbaar"
    roe_avg = clamp(mean(roes), -0.10, 0.35)
    payout = clamp(abs(d0) / ni0, 0.0, 1.0) if d0 is not None else None
    if payout is None:
        notes.append("dividend onbekend: winstinhouding 60% aangenomen")
        payout = 0.4
    re, rf, beta = cost_of_equity(fin, notes)
    r = max(re + sc["dr"], 0.07)
    tg = min(sc["tg"], r - 0.03)
    target = r + (roe_avg - r) * (1 - sc["roe_fade"])
    bv, pv, ri, path = bv0, 0.0, 0.0, []
    for t in range(1, YEARS + 1):
        roe_t = roe_avg + (target - roe_avg) * t / YEARS
        ri = (roe_t - r) * bv
        pv += ri / (1 + r) ** t
        bv *= 1 + roe_t * (1 - payout)
        path.append(round(roe_t, 4))
    tv = ri * (1 + tg) / (r - tg)
    pv_tv = tv / (1 + r) ** YEARS
    equity = bv0 + pv + pv_tv
    return _scenario_result(fin, equity, {
        "model": "Residual income", "discount_rate": rnd(r), "terminal_growth": rnd(tg),
        "book_value": rnd(bv0, 0), "roe_avg": rnd(roe_avg), "roe_path": path, "payout": rnd(payout),
        "pv_residual": rnd(pv, 0), "terminal_value": rnd(tv, 0), "pv_terminal": rnd(pv_tv, 0),
        "risk_free": rnd(rf), "beta": rnd(beta),
    }), None


def is_investment_company(fin):
    """Beleggings-/participatiemaatschappij (bv. 3i, investment trusts): de balans bestaat vrijwel geheel uit
    eigen vermogen en de 'omzet' is vooral waardestijging van de deelnemingen (nettomarge ~100%).
    Banken (eigen vermogen/activa ~5-10%) en vermogensbeheerders (~30-40%) vallen hier niet onder."""
    eq, assets = at(ser(fin, "equity"), 0), at(ser(fin, "total_assets"), 0)
    ni, rev = at(ser(fin, "net_income"), 0), at(ser(fin, "revenue"), 0)
    if not (eq and assets and ni and rev) or eq <= 0 or assets <= 0 or rev <= 0:
        return False
    return eq / assets >= 0.80 and ni / rev >= 0.70


def _nav_model(fin, sc, notes):
    """Intrinsieke waarde = netto vermogenswaarde (NAV, het eigen vermogen tegen reële waarde).
    Geen groei of toekomstige waardestijgingen aangenomen: die zijn bij een participatiemaatschappij
    al in de NAV verwerkt en niet als vaste 'winst' door te trekken. Alle scenario's gelijk."""
    nav = at(ser(fin, "equity"), 0)
    if nav is None or nav <= 0:
        return None, "netto vermogenswaarde (NAV) onbekend"
    if not notes:
        notes.append("participatiemaatschappij: waarde = netto vermogenswaarde (NAV), geen winstextrapolatie")
    return _scenario_result(fin, nav, {"model": "Netto vermogenswaarde (NAV)", "book_value": rnd(nav, 0)}), None


def run(fin):
    """Berekent alle drie scenario's. `valid` = neutraal scenario betrouwbaar en positief."""
    notes = []
    model = MODEL.get(fin["profile"], "fcf")
    if model == "ri" and is_investment_company(fin):
        model = "nav"
    fn = {"fcf": _fcf_model, "ddm": _ddm_model, "ri": _ri_model, "nav": _nav_model}[model]
    out = {"model": model, "scenarios": {}, "valid": False, "reason": None, "notes": notes}
    for name, sc in SCENARIOS.items():
        res, why = fn(fin, sc, notes if name == "neutral" else [])
        out["scenarios"][name] = res
        if name == "neutral" and res is None:
            out["reason"] = why
    neu = out["scenarios"]["neutral"]
    if neu is not None:
        if neu["equity_value"] is None or neu["equity_value"] <= 0:
            out["reason"] = "negatieve intrinsieke waarde (schuld groter dan bedrijfswaarde)"
        elif neu["upside"] is None:
            out["reason"] = "koers of beurswaarde ontbreekt"
        else:
            out["valid"] = True
            if (neu.get("terminal_share") or 0) > 0.85 and model == "fcf":
                notes.append("terminal value > 85% van de waarde: uitkomst gevoelig voor aannames")
    return out
