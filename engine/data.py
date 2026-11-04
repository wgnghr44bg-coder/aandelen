"""Financial Data Processing.

1. `extract_raw(ticker_obj)` haalt jaarcijfers + verwachtingen op uit een yfinance.Ticker en maakt er
   een JSON-veilige dict van (voor de cache).
2. `normalize(...)` zet die ruwe data om naar één consistente structuur:
   - jaren op één lijn (nieuwste eerst), max. 5 jaar
   - alle geldbedragen omgerekend naar de valuta van de beurskoers (belangrijk voor ADR's)
   - datum van de gebruikte cijfers en een lijst met datakwaliteitsproblemen
Ontbrekende waarden blijven None; ze worden nooit als 0 ingevuld.
"""
from datetime import date, datetime

from .sectors import profile_for
from .util import div, num

MAX_YEARS = 5
MAX_STATEMENT_AGE_DAYS = 480      # jaarcijfers ouder dan ~16 maanden = verouderd
MAX_FUNDAMENTALS_AGE_DAYS = 21    # cache van fundamentele data mag max. 3 weken oud zijn
MAX_PRICE_AGE_DAYS = 6            # koers ouder dan 6 dagen = verouderd
MIN_YEARS = 3                     # minimaal 3 jaar historie

INFO_FIELDS = (
    "shortName", "longName", "sector", "industry", "marketCap", "currentPrice", "regularMarketPrice",
    "trailingPE", "forwardPE", "trailingEps", "forwardEps", "beta", "currency", "financialCurrency",
    "sharesOutstanding", "mostRecentQuarter", "lastFiscalYearEnd",
)

# Rijnamen in yfinance (met terugvalopties)
ROWS = {
    "income": {
        "revenue": ["Total Revenue", "Operating Revenue"],
        "cogs": ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
        "gross_profit": ["Gross Profit"],
        "operating_income": ["Operating Income", "Total Operating Income As Reported"],
        "ebit": ["EBIT"],
        "ebitda": ["EBITDA", "Normalized EBITDA"],
        "net_income": ["Net Income Common Stockholders", "Net Income", "Net Income Continuous Operations"],
        "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
        "diluted_eps": ["Diluted EPS"],
        "diluted_shares": ["Diluted Average Shares"],
        "tax_rate": ["Tax Rate For Calcs"],
        "pretax_income": ["Pretax Income"],
        "tax_provision": ["Tax Provision"],
        "da_income": ["Reconciled Depreciation"],
    },
    "balance": {
        "total_debt": ["Total Debt"],
        "cash": ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"],
        "equity": ["Stockholders Equity", "Common Stock Equity"],
        "total_assets": ["Total Assets"],
        "current_assets": ["Current Assets"],
        "current_liabilities": ["Current Liabilities"],
        "inventory": ["Inventory"],
        "minority_interest": ["Minority Interest"],
    },
    "cashflow": {
        "ocf": ["Operating Cash Flow"],
        "capex": ["Capital Expenditure"],
        "fcf": ["Free Cash Flow"],
        "sbc": ["Stock Based Compensation"],
        "dividends_paid": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
        "da": ["Depreciation And Amortization", "Depreciation Amortization Depletion"],
    },
}
NOT_MONETARY = {"diluted_eps", "diluted_shares", "tax_rate"}


# ---------------------------------------------------------------- ophalen (yfinance -> JSON)

def _frame_to_json(df):
    if df is None or getattr(df, "empty", True):
        return None
    cols = list(df.columns)
    dates = [str(getattr(c, "date", lambda: c)()) for c in cols]
    wanted = {name for rows in ROWS.values() for opts in rows.values() for name in opts}
    rows = {}
    for idx in df.index:
        if idx in wanted:
            rows[str(idx)] = [num(v) for v in df.loc[idx].tolist()]
    return {"dates": dates, "rows": rows}


def _estimate_growth(df):
    out = {}
    if df is None or getattr(df, "empty", True) or "growth" not in df.columns:
        return out
    for period in ("0y", "+1y"):
        if period in df.index:
            out[period] = num(df.loc[period, "growth"])
    return out


def extract_info(info):
    return {k: info.get(k) for k in INFO_FIELDS if info.get(k) is not None}


def extract_raw(tk):
    """Haalt jaarcijfers en analistenverwachtingen op voor één yfinance.Ticker."""
    raw = {"income": None, "balance": None, "cashflow": None, "estimates": {}}
    raw["income"] = _frame_to_json(tk.income_stmt)
    raw["balance"] = _frame_to_json(tk.balance_sheet)
    raw["cashflow"] = _frame_to_json(tk.cashflow)
    for key, attr in (("revenue", "revenue_estimate"), ("eps", "earnings_estimate")):
        try:
            raw["estimates"][key] = _estimate_growth(getattr(tk, attr))
        except Exception:  # noqa: BLE001 – verwachtingen zijn optioneel
            raw["estimates"][key] = {}
    return raw


# ---------------------------------------------------------------- normaliseren

def _d(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _pick(stmt, options):
    if not stmt:
        return None
    for name in options:
        if name in stmt["rows"]:
            return stmt["rows"][name]
    return None


def _align(stmt, master_dates, options, tol_days=45):
    """Waarden van een rij op de master-jaardatums (dichtstbijzijnde kolom binnen tol_days)."""
    row = _pick(stmt, options)
    if row is None:
        return None
    cols = [_d(x) for x in stmt["dates"]]
    out = []
    for md in master_dates:
        best, best_gap = None, None
        for i, cd in enumerate(cols):
            if cd is None or i >= len(row):
                continue
            gap = abs((cd - md).days)
            if gap <= tol_days and (best_gap is None or gap < best_gap):
                best, best_gap = row[i], gap
        out.append(num(best))
    return out


def normalize(ticker, info, raw, price, price_on, asof, fx, rf, fetched=None, info_fetched=None):
    """Bouwt de genormaliseerde financiële structuur voor de engine.

    info      : gecachte Yahoo-info (dict)
    raw       : uitvoer van extract_raw (of None)
    price     : huidige koers (beursvaluta)
    price_on  : functie(date) -> slotkoers op/voor die datum (voor historische waardering), of None
    asof      : datum van de koers (date)
    fx        : wisselkoers financiële valuta -> beursvaluta (1.0 als gelijk), None = onbekend
    rf        : risicovrije rente (fractie), bv. 10-jaars Amerikaanse staatsrente
    """
    issues, notes = [], []
    info = info or {}
    sector, industry = info.get("sector"), info.get("industry")
    prof = profile_for(sector, industry, ticker)
    cur = info.get("currency")
    fin_cur = info.get("financialCurrency") or cur
    price = num(price)

    price_info = num(info.get("currentPrice")) or num(info.get("regularMarketPrice"))
    mcap_info = num(info.get("marketCap"))
    mcap = mcap_info * price / price_info if (mcap_info and price and price_info) else None
    if cur in ("GBp", "GBX", "ZAc", "ILA"):
        # koers in subeenheden (pence/cents): beurswaarde in dezelfde eenheid via aantal aandelen
        sh_out = num(info.get("sharesOutstanding"))
        mcap = sh_out * price if (sh_out and price) else None
    scale = price / price_info if (price and price_info) else None

    fin = {
        "ticker": ticker, "sector": sector, "industry": industry, "profile": prof,
        "price": price, "mcap": mcap, "currency": cur, "fin_currency": fin_cur, "fx": fx,
        "beta": num(info.get("beta")), "rf": rf,
        "years": [], "s": {}, "est": {}, "info": {}, "hist_mcap": [],
        "dates": {"price": str(asof) if asof else None, "fundamentals_fetched": fetched,
                  "info_fetched": info_fetched, "statements": None},
        "issues": issues, "notes": notes,
    }

    if price is None:
        issues.append("koers ontbreekt")
    if mcap is None:
        issues.append("beurswaarde ontbreekt")
    if fx is None:
        issues.append(f"wisselkoers {fin_cur}->{cur} ontbreekt")
    if not raw or not raw.get("income"):
        issues.append("jaarcijfers ontbreken")
        return fin

    inc = raw["income"]
    rev_row = _pick(inc, ROWS["income"]["revenue"])
    dates = [_d(x) for x in inc["dates"]]
    # alleen jaren met omzet, nieuwste eerst, max. 5
    years = [(d, i) for i, d in enumerate(dates)
             if d and rev_row and i < len(rev_row) and num(rev_row[i]) is not None]
    years.sort(key=lambda x: x[0], reverse=True)
    years = years[:MAX_YEARS]
    master = [d for d, _ in years]
    fin["years"] = [str(d) for d in master]
    if len(master) < MIN_YEARS:
        issues.append(f"te weinig historie ({len(master)} jaar, minimaal {MIN_YEARS})")
    if not master:
        return fin

    fin["dates"]["statements"] = str(master[0])
    if asof and (asof - master[0]).days > MAX_STATEMENT_AGE_DAYS:
        issues.append(f"jaarcijfers verouderd (laatste boekjaar {master[0]})")
    if asof and fetched and _d(fetched) and (asof - _d(fetched)).days > MAX_FUNDAMENTALS_AGE_DAYS:
        issues.append(f"fundamentele data verouderd (opgehaald {fetched})")
    if asof and (date.today() - asof).days > MAX_PRICE_AGE_DAYS:
        issues.append(f"koers verouderd ({asof})")

    stmts = {"income": inc, "balance": raw.get("balance"), "cashflow": raw.get("cashflow")}
    s = {}
    for part, rows in ROWS.items():
        for key, opts in rows.items():
            vals = _align(stmts[part], master, opts)
            if vals is not None and key not in NOT_MONETARY and fx is not None:
                vals = [None if v is None else v * fx for v in vals]
            s[key] = vals

    n = len(master)
    none = [None] * n

    def g(k):
        return s.get(k) or none

    # Afgeleide reeksen (alleen als de bronnen er zijn)
    if s.get("gross_profit") is None and s.get("cogs") and s.get("revenue"):
        s["gross_profit"] = [None if (r is None or c is None) else r - c for r, c in zip(g("revenue"), g("cogs"))]
    if s.get("fcf") is None and s.get("ocf") and s.get("capex"):
        s["fcf"] = [None if (o is None or c is None) else o + c for o, c in zip(g("ocf"), g("capex"))]
    if s.get("ebit") is None and s.get("pretax_income") and s.get("interest_expense"):
        s["ebit"] = [None if (p is None or i is None) else p + i
                     for p, i in zip(g("pretax_income"), g("interest_expense"))]
    if s.get("da") is None and s.get("da_income"):
        s["da"] = s["da_income"]
    if s.get("ebitda") is None and s.get("ebit") and s.get("da"):
        s["ebitda"] = [None if (e is None or d is None) else e + abs(d) for e, d in zip(g("ebit"), g("da"))]
    # Effectieve belastingvoet per jaar (Yahoo), anders provision/pretax; begrensd 0–40%
    tax = []
    for i in range(n):
        t = num(g("tax_rate")[i])
        if t is None:
            t = div(g("tax_provision")[i], g("pretax_income")[i])
        tax.append(None if t is None else max(0.0, min(0.40, t)))
    s["tax_rate"] = tax
    # Schuld: rij volledig afwezig terwijl de balans er wel is = bedrijf zonder rentedragende schuld
    debt_row = s.get("total_debt")
    if (debt_row is None or all(v is None for v in debt_row)) and stmts["balance"] and \
            any(v is not None for v in (s.get("total_assets") or [])):
        s["total_debt"] = [0.0] * n
        notes.append("geen schuldpost op de balans: schuldvrij")
    # Inventaris: rij volledig afwezig = bedrijf zonder voorraad (bv. software) -> 0 is hier correct.
    if s.get("inventory") is None and stmts["balance"]:
        s["inventory"] = [0.0] * n
        notes.append("geen voorraadpost: quick ratio = current ratio")
    # FFO-benadering voor vastgoed: nettowinst + afschrijvingen (verkoopwinsten niet beschikbaar)
    if prof == "reit":
        s["ffo"] = [None if (ni is None or d is None) else ni + abs(d) for ni, d in zip(g("net_income"), g("da"))]
        notes.append("FFO benaderd als nettowinst + afschrijvingen; NAV niet beschikbaar")
    if prof == "bank":
        notes.append("CET1 en kredietkwaliteit niet beschikbaar via de bron; eigen vermogen/activa als buffermaat")

    for k in list(s):
        if s[k] is None:
            s[k] = none
    fin["s"] = s

    # Historische beurswaarde per boekjaareinde (voor historische waardering)
    sh = g("diluted_shares")
    hist = []
    for i, d in enumerate(master):
        p_then = price_on(d) if price_on else None
        ratio = div(sh[i], sh[0]) if (sh[i] and sh[0]) else 1.0
        hist.append(None if (p_then is None or mcap is None or not price) else mcap * (p_then / price) * ratio)
    fin["hist_mcap"] = hist
    if price_on is None:
        notes.append("geen koershistorie voor historische waardering")

    # Diluted shares: alleen bruikbaar als koers en cijfers dezelfde valuta hebben en het aantal klopt
    implied = div(mcap, price)
    sh0 = num(sh[0]) if sh else None
    fin["shares_ok"] = bool(sh0 and implied and fin_cur == cur and abs(implied / sh0 - 1) < 0.25)
    fin["diluted_shares"] = sh0
    if not fin["shares_ok"]:
        notes.append("intrinsieke waarde per aandeel via beurswaarde-verhouding (ADR/aandelenklassen/valuta)")

    # Verwachtingen (forward) en trailing multiples, geschaald naar de huidige koers
    est = raw.get("estimates") or {}
    rev_est, eps_est = est.get("revenue") or {}, est.get("eps") or {}
    fwd_rev = num(rev_est.get("+1y")) if num(rev_est.get("+1y")) is not None else num(rev_est.get("0y"))
    fwd_eps = num(eps_est.get("+1y")) if num(eps_est.get("+1y")) is not None else num(eps_est.get("0y"))
    if fwd_eps is None:
        fe, te = num(info.get("forwardEps")), num(info.get("trailingEps"))
        if fe and te and te > 0:
            fwd_eps = fe / te - 1
            notes.append("verwachte winstgroei via forwardEps/trailingEps")
    fin["est"] = {"fwd_rev": fwd_rev, "fwd_eps": fwd_eps}
    tpe, fpe = num(info.get("trailingPE")), num(info.get("forwardPE"))
    fin["info"] = {
        "trailing_pe": tpe * scale if (tpe and scale) else None,
        "forward_pe": fpe * scale if (fpe and scale) else None,
        "trailing_eps": num(info.get("trailingEps")),
        "forward_eps": num(info.get("forwardEps")),
    }
    return fin
