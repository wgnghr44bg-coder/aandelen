# Notes for Claude sessions (InvestMarket)

## Met de eigenaar
- Praat **simpel Nederlands**. Vraag altijd eerst toestemming voor alles wat geld kost.
- **Cijfers moeten kloppen.** Nooit verzonnen of geschatte data. Geen betrouwbaar cijfer? Toon een link naar een
  betrouwbare bron (bv. "Tarief op aanvraag" of "bekijk bij …"). Linken naar actuele bronnen mag altijd.
- Alles gratis en zonder API-sleutels (Yahoo via `yfinance`, ECB, Eurostat, CBS, Bitvavo, Wikipedia, Nasdaq,
  companiesmarketcap).

## Hoe de site werkt
- Repo `wgnghr44bg-coder/aandelen`. Site = GitHub Pages (`main`, map `docs/`), één bestand `docs/index.html`.
  Verhoog `var BUILD="…"` in `index.html` bij elke wijziging aan de site (cache).
- **Updates**: `.github/workflows/update.yml` draait `update.py`. cron-job.org start deze workflow elke 30 min
  (:00/:30, workflow_dispatch met de PAT van de eigenaar; die moet de eigenaar zelf op tijd vernieuwen).
  `concurrency: cancel-in-progress` → een handmatige run vlak voor :00/:30 wordt afgebroken.
  Handmatig volledige run: workflow_dispatch met input `volledig: "true"`.
- **Branch `live`**: `data.json`, `history.json`, `grond_hist.json`, `intra.json` worden elke run geforceerd naar
  branch `live` gepusht (één commit, houdt de repo klein). De site leest die via raw.githubusercontent.com/…/live/.
  Op `main` alleen bij een volledige run. Controleren: `git fetch origin live && git show origin/live:data.json`.
- Andere workflows: `audit.yml` (dagelijkse controle), `vastgoedrentes.yml` (Playwright, rentes box 3 geldverstrekkers).
- Tests: `python -m pytest -q` (draaien ook in de workflow; geen echte netwerkcalls in tests).

## Aandelenlijsten (update.py → `main()`)
- **Wereld** = top 100 beursbedrijven van companiesmarketcap.com (`cmc_top`, CSV `?download=csv`; terugval `cmc.json`).
  OTC-symbolen omzetten via `CMC_TICKER`; bedrijf dat ook in AEX/Nasdaq 100 staat → die notering (bv. ASML.AS).
  Beurswaarde van de top 100 = die van companiesmarketcap.
- **S&P 500** compleet (`sp500_tickers`, datasets-CSV → `sp500.txt` + GICS-sectoren `sp500_sectoren.json`).
- **Nasdaq 100** compleet (Nasdaq-API, Wikipedia als reserve → `nasdaq100.json`), **AEX** compleet (Wikipedia → `aex.json`).
- `bereken()` geeft ook `jaren` = rendement per volledig kalenderjaar (slot laatste beursdag vorig jaar → dat jaar);
  gebruikt in "Stijgers & dalers per index" (knoppen 1D/1W/1M/YTD/1J + keuzelijst Jaar).
- Alle leden = rijen in `data.json` met vlaggen `w`/`sp`/`nq`/`aex`; rang op beurswaarde. Lijsten volgen vanzelf de bronnen.
- Bekend: IHC.AE (Abu Dhabi) heeft geen gratis koers → ontbreekt in Wereld (99/100).
- Filters op de site: `CAPS` in `index.html` (lijsten + groottes); sectoren komen uit de rijen.

## Waarderingsengine (`engine/`)
- BUY/HOLD/SELL/NO RATING in `engine/decision.py` (BUY alleen als álle eisen kloppen, veiligheidsmarge ≥ 20%).
  Volledige analyse intern in `analyse/analysis.json` (JSON-lines). Beleggingsmaatschappijen → NAV-model (`dcf.py`).
- **Bij elke BUY** zet `engine/uitleg.py` (`waarom()`) een uitleg in gewone taal in `data.json` (`why.why` en
  `why.watch`). Op de site: blok "✅ Waarom een BUY?" + "⚠️ Let op" (`whyBox` in `index.html`). Alleen echte
  berekende cijfers gebruiken.

## Overige tabs
- Menu onderaan (5): Overzicht, Aandelen, Sectoren, **Economie** (= panes rentes+inflatie+vastgoed onder elkaar,
  `showTab("rentes")` scrolt ernaartoe) en **Meer** (watchlist, grondstoffen, grootste). Zie `showTab`/`navOf`.
- Overzicht (dashboard): bovenaan compact **Marktontwikkeling = gemiddelde van WEBN, VALL en Bitcoin** (periode
  1D–1Y, stuurt ook de tegels), WEBN/VALL/Bitcoin, indexen Nasdaq/S&P 500/AEX, BUY/HOLD/SELL, Rente & Economie,
  Vastgoed, Grondstoffen (tik = grafiek 1D–5J), Sectoren (balkjes), grootste assets, en onderaan stijgers/dalers
  per index met sectorknoppen en AI-knop (`ai.txt`). Nieuws staat onder Economie (pane `nieuws`).
- Grondstoffen met koersen binnen de dag (1D/1W): `INTRA_GROND` in update.py = `GI` in index.html (goud, zilver,
  Brent, aardgas) → komen in `intra.json`.
- Nieuws: `nieuws.py` (RSS NOS Economie + NU.nl Economie, alleen koppen + link; terugval = vorige koppen) → `nieuws`.
- Rentes/Inflatie/Vastgoed: `macro.py` (ECB, Eurostat, CBS). Vastgoed box 3: `vastgoedrentes.py` (alleen
  gepubliceerde tarieven, anders "Tarief op aanvraag"). Grondstoffen: `grondstoffen.py` (bandbreedte-controle, anders link).

## Werkwijze
- Wijzig → `python -m pytest -q` → commit (Nederlandse boodschap) → push naar `main` → wacht op de volgende run
  (of start er een) → controleer `origin/live:data.json` en eventueel de job-log via de GitHub-tools.
- Site visueel testen: Playwright (`chromium.launch()`), `docs/` lokaal serveren en raw.githubusercontent blokkeren
  zodat de lokale `docs/data.json` geladen wordt.
- Deze sessie-omgeving kan Yahoo niet bereiken; companiesmarketcap.com alleen als die host in de netwerkinstellingen
  staat. Echte data controleer je via de workflow-run.
