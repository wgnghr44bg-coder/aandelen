"""Uitleg in gewone taal bij een BUY: waarom het rekenmodel dit aandeel koopwaardig vindt, en waar je op moet letten.

Alles komt rechtstreeks uit de berekende cijfers van de engine (niets verzonnen). Ontbreekt een cijfer, dan
wordt dat punt overgeslagen.
"""

VALUTA = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CHF": "CHF ", "CNY": "CN¥", "HKD": "HK$", "CAD": "C$"}


def _pct(x, dec=0):
    return f"{x * 100:.{dec}f}%".replace(".", ",")


def _num(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


def _geld(x, cur):
    s = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{VALUTA.get(cur, (cur or '') + ' ')}{s}"


def _m(a, cat, key):
    m = (((a.get("categories") or {}).get(cat) or {}).get("metrics") or {}).get(key) or {}
    return m.get("value")


def waarom(a):
    """{"why": [...], "watch": [...]} voor een BUY-analyse; None voor andere ratings."""
    if not a or a.get("rating") != "BUY":
        return None
    why, watch = [], []
    cats = a.get("categories") or {}
    sc = {k: (v or {}).get("score") for k, v in cats.items()}
    data = a.get("data") or {}
    cur = data.get("currency")
    koers = data.get("price")

    # 1. Waardering en intrinsieke waarde
    sc_dcf = ((a.get("dcf") or {}).get("scenarios") or {})
    neu, con = sc_dcf.get("neutral") or {}, sc_dcf.get("conservative") or {}
    if neu.get("intrinsic_per_share") and koers:
        t = (f"Berekende waarde {_geld(neu['intrinsic_per_share'], cur)} per aandeel tegen een koers van "
             f"{_geld(koers, cur)}: veiligheidsmarge {_pct(neu.get('margin_of_safety') or 0)}")
        if con.get("intrinsic_per_share"):
            t += f" (voorzichtig scenario: {_geld(con['intrinsic_per_share'], cur)})"
        why.append(t + ".")
    pe, fpe, pfcf = _m(a, "valuation", "pe"), _m(a, "valuation", "fpe"), _m(a, "valuation", "pfcf")
    delen = []
    if pe:
        delen.append(f"koers/winst {_num(pe)}")
    if fpe:
        delen.append(f"verwachte koers/winst {_num(fpe)}")
    if pfcf:
        delen.append(f"koers/vrije kasstroom {_num(pfcf)}")
    rel = _m(a, "valuation", "sector_rel")
    if delen:
        t = "Waardering: " + ", ".join(delen)
        if rel and rel < 0.9:
            t += f"; ongeveer {_pct(1 - rel)} goedkoper dan vergelijkbare bedrijven"
        why.append(t + ".")
    hist = _m(a, "valuation", "hist_rel")
    if hist and hist < 0.9:
        why.append(f"Goedkoper dan zijn eigen gemiddelde van de afgelopen jaren (±{_pct(1 - hist)} lager).")

    # 2. Winstgevendheid
    delen = []
    for key, lab in (("roic", "rendement op geïnvesteerd kapitaal"), ("roe", "rendement op eigen vermogen"),
                     ("om", "bedrijfsmarge"), ("fcfm", "vrije-kasstroommarge")):
        v = _m(a, "profitability", key)
        if v is not None and len(delen) < 3:
            delen.append(f"{lab} {_pct(v)}")
    if delen:
        why.append("Winstgevendheid: " + ", ".join(delen) + ".")

    # 3. Groei
    delen = []
    for key, lab in (("rev3", "omzet"), ("eps3", "winst per aandeel"), ("fcf_g", "vrije kasstroom")):
        v = _m(a, "growth", key)
        if v is not None:
            delen.append(f"{lab} +{_pct(v)}" if v >= 0 else f"{lab} {_pct(v)}")
    if delen:
        t = "Groei per jaar (laatste 3 jaar): " + ", ".join(delen)
        fwd = _m(a, "growth", "fwd_eps")
        if fwd is not None:
            t += f"; analisten verwachten {'+' if fwd >= 0 else ''}{_pct(fwd)} winstgroei komend jaar"
        why.append(t + ".")

    # 4. Financiële gezondheid
    nde, de = _m(a, "health", "nd_ebitda"), _m(a, "health", "de")
    if nde is not None and nde < 0:
        why.append("Sterke balans: meer geld in kas dan schulden" + (f" (schuld/eigen vermogen {_num(de, 2)})" if de is not None else "") + ".")
    elif nde is not None:
        why.append(f"Gezonde balans: netto schuld {_num(nde)}× de jaarlijkse bedrijfswinst (EBITDA).")

    fs = a.get("fundamental_score")
    if fs is not None:
        why.append(f"Totaalscore kwaliteit {fs:.0f}/100 en alle koopvoorwaarden van het model kloppen.")

    # Let op: zwakste punten
    if sc.get("moat") is not None and sc["moat"] < 60:
        watch.append(f"Concurrentievoordeel (moat) is beperkt ({sc['moat']:.0f}/100).")
    if (_m(a, "moat", "rev_stab") or 0) > 0.25:
        watch.append("De omzet schommelt sterk van jaar tot jaar.")
    pricing = _m(a, "moat", "pricing")
    if pricing is not None and pricing < -0.05:
        watch.append("De brutomarge is de laatste jaren gedaald.")
    for n in (a.get("dcf") or {}).get("notes") or []:
        if "landenrisico" in n:
            watch.append("Extra landenrisico (bijv. politiek of toezicht) is meegerekend, maar blijft een risico.")
    cur_fin = data.get("financial_currency")
    if cur_fin and cur and cur_fin != cur:
        watch.append(f"Cijfers in {cur_fin}, koers in {cur}: wisselkoersen beïnvloeden het rendement.")
    watch.append("Dit is een rekenmodel op basis van openbare cijfers, geen persoonlijk advies.")
    return {"why": why, "watch": watch}
