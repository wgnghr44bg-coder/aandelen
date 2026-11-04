# Top 100 aandelen: wat is er gezakt?

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
