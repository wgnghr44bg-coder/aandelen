"""Ophalen en cachen van fundamentele data + aansturen van de waarderingsengine.

Cache (.cache/fundamentals.json, bewaard via de GitHub Actions-cache, niet in de repo):
  {ticker: {"info": {...}, "info_fetched": iso-tijd,
            "raw": {...jaarcijfers + verwachtingen...}, "raw_fetched": iso-tijd}}

- Info (naam, sector, beurswaarde, K/W) wordt max. 1× per dag per aandeel opgehaald.
- Jaarcijfers en verwachtingen max. 1× per week per aandeel, binnen een tijdsbudget per run.
- Elk uur wordt het advies opnieuw berekend met de actuele koers, zonder extra API-aanroepen.
"""
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

from engine import ENGINE_VERSION, analyze_universe
from engine.data import extract_info, extract_raw, normalize

ROOT = Path(__file__).parent
CACHE = ROOT / ".cache" / "fundamentals.json"
ANALYSIS = ROOT / "analyse" / "analysis.json"
INFO_MAX_AGE = timedelta(hours=23)
RAW_MAX_AGE = timedelta(days=7)
RAW_BUDGET_S = 540  # max. 9 minuten jaarcijfers ophalen per run
INFO_BUDGET = 250   # max. info-aanroepen per run (spreiden, zodat Yahoo ons niet blokkeert)

# Koersen in subeenheden: Londen noteert in pence (GBp), Johannesburg in cents (ZAc), Tel Aviv in agorot (ILA)
SUBUNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}


# Opkomende en frontiermarkten (MSCI-indeling): deze landen doen niet mee (alleen ontwikkelde landen).
EMERGING_COUNTRIES = {
    "China", "India", "Brazil", "Mexico", "Taiwan", "South Korea", "Korea", "Saudi Arabia", "Indonesia",
    "South Africa", "Turkey", "Argentina", "Uruguay", "Chile", "Colombia", "Peru", "Thailand", "Malaysia",
    "Philippines", "United Arab Emirates", "Qatar", "Kuwait", "Egypt", "Poland", "Greece", "Hungary",
    "Czech Republic", "Russia", "Vietnam", "Kazakhstan", "Nigeria", "Pakistan", "Macau",
}


def is_developed(info):
    """False als het land van vestiging een opkomende markt is. Onbekend land = toegestaan
    (de kandidatenlijst bevat al alleen ontwikkelde landen)."""
    return (info or {}).get("country") not in EMERGING_COUNTRIES


def free_float(info):
    """Aandeel vrij verhandelbare aandelen (zoals indexen als die achter WEBN wegen).
    Onbekend of onlogisch -> 1,0 (volledige beurswaarde)."""
    fl, sh = (info or {}).get("floatShares"), (info or {}).get("sharesOutstanding")
    try:
        r = float(fl) / float(sh)
    except (TypeError, ValueError, ZeroDivisionError):
        return 1.0
    return r if 0.05 <= r <= 1.0 else 1.0


def base_currency(cur):
    """(hoofdvaluta, aantal subeenheden per hoofdeenheid)."""
    return SUBUNITS.get(cur, (cur, 1.0))


def now():
    return datetime.now(timezone.utc)


def _age(ts):
    try:
        return now() - datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return timedelta(days=9999)


def load_cache():
    try:
        return json.loads(CACHE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, separators=(",", ":")))
    tmp.replace(CACHE)


def _retry(fn, label, tries=3):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            print(f"  {label} poging {i + 1} mislukt: {e}")
            time.sleep(2 * (i + 1))
    return None


def refresh(cache, tickers, info_only=()):
    """Werkt de cache bij: eerst ontbrekende/verouderde info (nodig voor de top 100), dan jaarcijfers."""
    n_info = 0
    # ontbrekende info eerst, daarna de oudste
    order = sorted(tickers, key=lambda t: (bool((cache.get(t) or {}).get("info")),
                                           (cache.get(t) or {}).get("info_fetched") or ""))
    # wereldbedrijven (alleen info nodig) zonder info eerst, de rest achteraan
    extra = [t for t in info_only if t not in tickers]
    order = [t for t in extra if not (cache.get(t) or {}).get("info")] + order + \
        [t for t in extra if (cache.get(t) or {}).get("info")]
    for t in order:
        c = cache.setdefault(t, {})
        if c.get("info") and "country" in c["info"] and "floatShares" in c["info"] \
                and _age(c.get("info_fetched")) < INFO_MAX_AGE:
            continue
        if n_info >= INFO_BUDGET:
            print(f"info-budget op ({INFO_BUDGET}); rest volgende run")
            break
        info = _retry(lambda: yf.Ticker(t).info or {}, f"info {t}")
        if info and info.get("marketCap"):
            c["info"] = extract_info(info)
            c["info_fetched"] = now().isoformat()
            n_info += 1
        time.sleep(0.3)
    if n_info:
        save_cache(cache)
    print(f"info bijgewerkt: {n_info}")

    todo = [t for t in tickers if cache.get(t, {}).get("info")
            and (not cache[t].get("raw") or _age(cache[t].get("raw_fetched")) >= RAW_MAX_AGE)]
    todo.sort(key=lambda t: (cache[t].get("raw") is not None, cache[t].get("raw_fetched") or ""))
    start, n_raw = time.time(), 0
    for t in todo:
        if time.time() - start > RAW_BUDGET_S:
            print(f"tijdsbudget jaarcijfers op; nog {len(todo) - n_raw} te gaan (volgende run)")
            break
        raw = _retry(lambda: extract_raw(yf.Ticker(t)), f"jaarcijfers {t}")
        if raw and raw.get("income"):
            cache[t]["raw"] = raw
            cache[t]["raw_fetched"] = now().isoformat()
        else:
            print(f"  jaarcijfers {t}: niet beschikbaar")
        n_raw += 1
        if n_raw % 10 == 0:
            save_cache(cache)
        time.sleep(0.5)
    save_cache(cache)
    print(f"jaarcijfers bijgewerkt: {n_raw}")


def market_data(cache):
    """Risicovrije rente (10-jaars VS, ^TNX) en wisselkoersen voor bedrijven die in een andere valuta
    rapporteren dan hun koers (ADR's). Eén download voor alles."""
    pairs = set()
    for c in cache.values():
        i = c.get("info") or {}
        cur = base_currency(i.get("currency"))[0]
        fcur = base_currency(i.get("financialCurrency") or i.get("currency"))[0]
        if cur and fcur and cur != fcur:
            pairs.add(f"{fcur}{cur}=X")      # jaarcijfers -> beursvaluta
        if cur and cur != "USD":
            pairs.add(f"{cur}USD=X")         # beursvaluta -> USD (rangschikking)
    symbols = ["^TNX"] + sorted(pairs)
    rf, fx = None, {}
    try:
        d = yf.download(symbols, period="10d", interval="1d", auto_adjust=False,
                        group_by="ticker", progress=False)
        for s in symbols:
            try:
                close = d[s]["Close"].dropna()
                if close.empty:
                    continue
                v = float(close.iloc[-1])
                if s == "^TNX":
                    rf = v / 100.0 if 0.5 < v < 15 else None
                else:
                    fx[s] = v
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        print(f"rente/valuta download mislukt: {e}")
    print(f"rente 10j: {rf}, wisselkoersen: {len(fx)}/{len(pairs)}")
    return rf, fx


def fx_rate(info, fx):
    """Wisselkoers van de valuta van de jaarcijfers naar de beursvaluta (incl. pence e.d.)."""
    if not info.get("currency"):
        return None
    cur, sub = base_currency(info["currency"])
    fcur = base_currency(info.get("financialCurrency") or info["currency"])[0]
    rate = 1.0 if cur == fcur else fx.get(f"{fcur}{cur}=X")
    return None if rate is None else rate * sub


def usd_rate(info, fx):
    """Wisselkoers van de beursvaluta naar USD (per eenheid waarin de koers noteert)."""
    if not info.get("currency"):
        return None
    cur, sub = base_currency(info["currency"])
    rate = 1.0 if cur == "USD" else fx.get(f"{cur}USD=X")
    return None if rate is None else rate / sub


def market_cap_quote(info, price):
    """Beurswaarde in de valuta van de koers. Bij pence e.d. via aantal aandelen × koers
    (Yahoo geeft de beurswaarde daar in de hoofdvaluta)."""
    p_info = info.get("currentPrice") or info.get("regularMarketPrice")
    if info.get("currency") in SUBUNITS:
        sh = info.get("sharesOutstanding")
        return sh * price if (sh and price) else None
    mc = info.get("marketCap")
    return mc * price / p_info if (mc and price and p_info) else mc


def _price_lookup(close):
    if close is None or close.empty:
        return None
    idx = pd.DatetimeIndex(close.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s = pd.Series(close.values, index=idx).sort_index()

    def on(d):
        part = s[s.index <= pd.Timestamp(d)]
        return float(part.iloc[-1]) if not part.empty else None
    return on


def run_engine(cache, prices, closes, asof, rf, fx):
    """prices: {ticker: huidige koers}, closes: {ticker: Series slotkoersen}.
    Geeft {ticker: analyse} voor alle aandelen met info (het hele universum, voor sectorvergelijking)."""
    fins = {}
    for t, price in prices.items():
        c = cache.get(t) or {}
        if not c.get("info"):
            continue
        raw_day = (c.get("raw_fetched") or "")[:10] or None
        fins[t] = normalize(t, c["info"], c.get("raw"), price, _price_lookup(closes.get(t)), asof,
                            fx_rate(c["info"], fx), rf, raw_day, (c.get("info_fetched") or "")[:10] or None)
    return analyze_universe(fins)


def write_analysis(results, asof):
    """Interne, volledige analyse (alle ratio's, scores, DCF-aannames, datums). Niet op de site."""
    ANALYSIS.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"engine_version": ENGINE_VERSION, "generated": now().isoformat(timespec="seconds"),
                         "price_date": str(asof)})]
    lines += [json.dumps(results[t], ensure_ascii=False, separators=(",", ":")) for t in sorted(results)]
    ANALYSIS.write_text("\n".join(lines) + "\n")
    counts = {}
    for r in results.values():
        counts[r["rating"]] = counts.get(r["rating"], 0) + 1
    print(f"analyse geschreven: {counts}")


def today():
    return date.today()
