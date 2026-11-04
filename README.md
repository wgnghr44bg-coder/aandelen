# StockHunter

Een simpele website die de 100 grootste beursgenoteerde bedrijven (VS-genoteerd, inclusief ADR's) laat zien,
gesorteerd op hoeveel hun koers gezakt is. Handig om snel te zien welke grote bedrijven flink gedaald zijn.

**Geen financieel advies.** Bron: Yahoo Finance (via `yfinance`).

## Hoe het werkt

- `tickers.txt` – ongeveer 150 kandidaten. Het script kiest hieruit elke keer de top 100 op beurswaarde.
- `update.py` – haalt 5 jaar dagkoersen en bedrijfsgegevens op en schrijft `docs/data.json`.
- `docs/index.html` – de website (één bestand), die `data.json` laadt.
- `.github/workflows/update.yml` – draait elke werkdag om 22:45 UTC en commit `docs/data.json` als die veranderd is.
  Handmatig starten kan via *Actions → Koersen bijwerken → Run workflow*.

De site draait gratis op GitHub Pages (branch `main`, map `/docs`). Er is geen server en geen API-sleutel nodig.

## Lokaal draaien

```bash
pip install -r requirements.txt
python update.py
cd docs && python -m http.server 8000
# open http://localhost:8000
```

## Tickers aanpassen

Zet één ticker per regel in `tickers.txt` (Yahoo-notatie, bijvoorbeeld `BRK-B`). Regels met `#` worden genegeerd.

## Waarderingsengine (BUY / HOLD / SELL / NO RATING)

Op de site staat per aandeel alleen het advies. De volledige analyse draait op de achtergrond
(`engine/`) en wordt dagelijks intern opgeslagen in `analyse/analysis.json` (alle ratio's, scores,
DCF-aannames en de datum van de gebruikte cijfers).

- **Fundamental Score** = Financial Health 20% + Profitability 20% + Growth 20% + Valuation 25% +
  Competitive Advantage 15%, met eigen normen per sector (`engine/sectors.py`).
- **Intrinsieke waarde**: 5-jaars DCF op vrije kasstroom met terminal value (conservatief / neutraal /
  optimistisch). Banken/verzekeraars: residual income; nutsbedrijven en vastgoed: dividend discount.
- **Upside** = intrinsiek / koers − 1; **Margin of Safety** = (intrinsiek − koers) / intrinsiek.
- **BUY** alleen bij sterke fundamenten, aantrekkelijke waardering en ≥ 20% veiligheidsmarge;
  **SELL** bij structurele verslechtering of extreme overwaardering (niet bij alleen "duur");
  **NO RATING** bij ontbrekende, verouderde of onbetrouwbare data.
- Jaarcijfers worden max. 1× per week per aandeel opgehaald (cache), het advies elk uur herberekend.
- Tests: `python -m pytest -q`
