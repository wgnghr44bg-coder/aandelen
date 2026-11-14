# Notes for Claude sessions (InvestMarket)

## Met de eigenaar
- Praat **simpel Nederlands**. Vraag altijd eerst toestemming voor alles wat geld kost.
- **Cijfers moeten kloppen.** Nooit verzonnen of geschatte data. Geen betrouwbaar cijfer? Toon een link naar een
  betrouwbare bron (bv. "Tarief op aanvraag" of "bekijk bij …"). Linken naar actuele bronnen mag altijd.
- Alles gratis en zonder API-sleutels (Yahoo via `yfinance`, ECB, Eurostat, CBS, Bitvavo, Wikipedia, Nasdaq,
  companiesmarketcap).
- **Portfolio moet gelijk lopen met de broker-apps** (IBKR, Saxo, Bitvavo). Verander de koersbron of slotkoers-regels
  niet zonder eerst te toetsen tegen een screenshot van de app van de eigenaar. **Niet doen:** de avondkoers
  (gettex/Düsseldorf) in de koersgeschiedenis `h` of buiten het avondvenster gebruiken — dat gaf op 14-11-2026 een
  fout van ± € 38 bij IBKR. Test: `tests/test_avond.py` (faalt als dit terugkomt).

## Hoe de site werkt
- Repo `wgnghr44bg-coder/aandelen`. Site = GitHub Pages (`main`, map `docs/`), één bestand `docs/index.html`.
  Verhoog `var BUILD="…"` in `index.html` bij elke wijziging aan de site (cache).
  De site ververst zelf elke 5 min (`autoLoad`), niet als de pagina verborgen is, een invoerveld focus heeft of `pfEdit` open is.
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
- Yahoo geeft soms een lege laatste dagrij (Close NaN) → `vul_lege_dag()` met de laatste 5-min-koers van die dag
  (`intraday_slot`, alleen voor die aandelen). Laat Yahoo de dag helemaal weg → `vul_aan()`: aandelen uit de vorige
  `data.json` (`pd` = datum + `price` per rij), WEBN/VALL/Bitcoin uit `markt_hist.json`. Yahoo wint als die de dag heeft.
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
- Portfolio (onder Meer, pane `portfolio`): alleen in localStorage (`pf`, v3: `{v:3,acc:[{id,n,ins,mb,md,kd,hele,fee,
  s:[{d,v,inl,pos:[{t,q,p0}]}],tx:[{d,k,t,q,b,f}]}]}`), nooit online. Meerdere posities per rekening: WEBN/VALL/Bitcoin
  (extras) en alle aandelen uit `rows` (koers in € via r.usd/eurusd = wisselkoers van nu; geschiedenis uit history.json).
  Kas = v − Σ q·p0. Transacties (koop/verkoop/storting/opname) via de rekening → nieuwe momentopname (`pfSnapAt`).
  `s` = momentopnamen. `ins` = maandelijkse aankoop (WEBN.DE/VALL.AS/BTC-EUR):
  `pfSim`: kas na invoer = v − q·p0; storting op dag `md` → kas; aankoop `kd` dagen later (ETF niet in weekend) tegen
  slotkoers, met `fee` per aankoop; `hele` = alleen hele stukken van het maandbedrag met ~2% marge (Saxo AutoInvest).
  Getoetst tegen echte aankopen okt 2026 (IBKR/Saxo/Bitvavo). Aankopen na laatste invoer = geschat, zo getoond.
  Eerdere standen (datum, waarde, inleg, aantal) via het bewerkformulier (`pfHistForm`) → groeigrafiek vanaf eerste stand.
  inleg(t) = inl + mb per maanddag `md` na d. Resultaat per periode (1D/1W/1M/YTD/1J/Alles) = Δwaarde − Δinleg.
  `pfMigrate` zet het oude v1-formaat en back-ups om (koppeling geraden uit de naam: WEBN/VALL/Bitcoin). Geen broker-API's: repo/site zijn openbaar
  (Bitvavo en IBKR blokkeren browser-CORS; zou via Actions-secrets + versleuteling moeten).
- Na een (geschatte) maandaankoop: melding bovenaan Portfolio (`pftodo`) → "✅ Bijwerken met je app" (`pfUpdForm`: alleen
  waarde + aantal, uitleg per broker via `pfWhere`; inleg blijft `pfInl`).
- Overzicht bovenaan: "Mijn portfolio" (`renderPfOv`), oogje verbergt bedragen (localStorage `pfhide`); alleen als er rekeningen zijn.
- WEBN 's avonds = midden bied/laat op gettex/Düsseldorf (`na_koers`), maar alleen op de handelsdag zelf tussen
  17:40 en 22:30 (`avond_venster`). Daarbuiten (nacht, weekend) en voor alle eerdere dagen: officiële Xetra-slotkoers.
  Getoetst 14-11-2026: IBKR-waarde € 8.306,52 = kas + 633,6984 × 13,094 (officiële slot); IBKR 'W&V vandaag' rekent
  vanaf de officiële slot van de vorige dag. De avondkoers wordt alleen bewaard (`WEBN.DE@avond`), niet gebruikt in `h`.
- Portfolio 1D (`pfRes`): vanaf de slot vóór de laatste beursdag van de hoofdbelegging (`pfLastDay`), dus in het
  weekend de verandering van vrijdag (zoals IBKR); Bitcoin: t.o.v. gisteren.
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
