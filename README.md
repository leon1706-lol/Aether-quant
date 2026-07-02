# Aether Quant

Aether Quant ist ein Trading-Projekt auf Basis von QuantConnect Lean, PyTorch und einer lokalen Visualisierungsschicht.
Das Ziel ist ein adaptives Modell, das auf Lean-Daten trainiert wird, im Backtest validiert werden kann, spaeter ueber Interactive Brokers im Paper Trading laeuft und seinen Zustand fuer ein Live-Dashboard bereitstellt.

## Aktueller Stand

Phase V2-0 ist gestartet. Phase 10 ist abgeschlossen, und die neue Fork baut auf dem bisherigen Aether-Quant-Grundgeruest auf:

- Grundstruktur fuer `backtests/`, `ml/` und `visualization/`
- Lean-Algorithmus in `main.py` mit Feature-Berechnung, JSON-Modell-Inferenz, Signal-Engine und Risk Controls
- Trainingspipeline in `train.py` mit Dateninventur, Feature-Berechnung, Splits und erstem PyTorch-Modell
- Ausbau des Dashboards in `dashboard.html` mit Scorecards, Asset-Heatmap und 3D-artiger Market-Scene
- Startkonfiguration in `config.json`
- Erste Runtime-Dateien fuer Modell- und Visualisierungszustand
- Grafana-freundliche Exportdateien unter `visualization/grafana/`
- erweitertes Daily-Multi-Asset-Universum mit Aktien, ETFs und drei Spot-Krypto-Coins
- Asset-Qualitaetslogik fuer trainierbare/tradbare Assets und Observation-only Assets
- Persistente Dateninventur in `ml/dataset_inventory.json`
- Persistente Dataset-Artefakte in `ml/datasets/`, `ml/dataset_manifest.json` und `ml/scaler.pkl`
- Modellartefakte in `ml/model.pt`, `ml/training_metrics.json` und `ml/model_weights.json`
- Strategie-Validierung in `backtests/strategy_report.json` und `backtests/equity_curves.csv`
- erste Unit-Tests fuer Feature Engineering, Asset-Qualitaet und Scaler-Verhalten
- V2-Architektur-Fundament mit MoE-, Regime-, Topology-, Experience-, Risk- und Monitoring-Modulen

## Projektstruktur

```text
aether-quant/
|-- docker-compose.yml
|-- development/
|   |-- v2_architecture.md
|   |-- infrastructure.md
|   |-- Changelog.md
|   |-- Problems.md
|-- lean.json
|-- config.json
|-- backtests/
|-- data/
|-- main.py
|-- train.py
|-- data_pipeline/
|-- moe/
|-- experts/
|-- regime/
|-- topology/
|-- experience/
|-- risk/
|-- monitoring/
|-- ml/
|   |-- model_weights.json
|-- visualization/
|   |-- state.json
|-- webui/
|   |-- src/
|-- requirements.txt
|-- README.md
|-- .gitignore
```

## Komponenten

- `lean.json`: Lean-Engine- und Brokerage-Konfiguration
- `config.json`: lokale Projektmetadaten fuer die spaetere Lean-Cloud-/CLI-Zuordnung
- `main.py`: Lean-Algorithmus fuer Backtest, Modell-Inferenz und spaeteres IB Paper Trading
- `train.py`: Trainings- und Artefaktpipeline fuer Dateninventur, Features, Splits, Scaler und Modelltraining
- `ml/model_weights.json`: Lean-lesbarer Export des trainierten Modells
- `ml/dataset_inventory.json`: Phase-1-Inventur fuer V1-Universum, Datenabdeckung und Fenster
- `ml/dataset_manifest.json`: Phase-2-/Phase-9-Zusammenfassung der gebauten Datensaetze inklusive Asset-Qualitaet
- `ml/scaler.pkl`: gespeicherter Feature-Scaler fuer spaetere Inferenz
- `ml/training_metrics.json`: Metriken, Verlauf und Qualitaet des ersten Modells
- `backtests/strategy_report.json`: Strategie-Report mit Return, Sharpe, Drawdown und Baseline-Vergleich
- `backtests/equity_curves.csv`: Equity-Curves fuer Validation und Backtest
- `visualization/state.json`: gemeinsamer Runtime-Zustand fuer Dashboard, Monitoring und Trading
- `visualization/scene.json`: Szenendaten fuer die lokale Markt-/Portfolio-Visualisierung
- `visualization/grafana/`: JSON- und CSV-Feeds fuer spaeteres Grafana-Monitoring
- `monitoring/api_server.py`: FastAPI-Server, der `visualization/state.json`, `visualization/scene.json` und die Grafana-Exporte als JSON-API unter `localhost:8000` bereitstellt
- `webui/`: React/Vite-Webui unter `localhost:3000` mit Overview-Seite (Scorecards, 3D-Marktszene, Asset-Heatmap, Signal-/Positionsboard) und Risk-Seite (Risk Core, Asset-Volatility-/Sizing-Tabelle) als einheitliche Ablösung der frueheren `dashboard.html` und `volatility_dashboard.html`
- `docker-compose.yml`: lokale Infrastruktur fuer Lean, Grafana, Redis und PostgreSQL
- `development/`: Entwicklungs-Dokumentation — `v2_architecture.md` (V2-Systemarchitektur mit Prozessfluss und Tech-Stack-Diagrammen), `infrastructure.md` (Docker-Compose-Startbefehle, Netzwerk- und Datenfluss-Runbook), `Changelog.md` (detaillierte Phase-Ergebnisse, siehe unten), `Problems.md` (gefundene Bugs mit Schweregrad und Status)
- `data_pipeline/`: V2-Vertrag fuer Lean-Datenquelle, Dataset-Manifest und spaetere MoE-Verbraucher
- `moe/`: Gating Network, Expert Routing und finale MoE-Signalzusammenfuehrung
- `experts/`: Bullish-, Bearish-, Sideways- und Volatility-Expert-Module
- `regime/`: Markt-Regime-Erkennung und spaetere LLM-Regime-Vektoren
- `topology/`: 3D-Marktstruktur, Asset-Cluster und Topology-Exports
- `experience/`: Observation-, Signal-, Trade- und Retraining-Historie
- `risk/`: dynamisches Position Sizing, Hebel-, Liquiditaets- und Market-Impact-Controls
- `monitoring/`: HTML-Volatility-Dashboard, Grafana-Feeds und spaetere Alerts

## Lokaler Start

1. Virtuelle Umgebung aktivieren.
2. Abhaengigkeiten installieren:

```powershell
pip install -r requirements.txt
```

Fuer lokale Entwicklung zusaetzlich:

```powershell
pip install -r requirements-dev.txt
```

3. Initiale Inventur nur aktualisieren:

```powershell
python train.py --init-only
```

4. Datensatz bauen und Modell trainieren:

```powershell
python train.py
```

Optional nur Dataset-Artefakte ohne Training erzeugen:

```powershell
python train.py --dataset-only
```

5. Webui lokal starten (zwei Prozesse):

```powershell
uvicorn monitoring.api_server:app --port 8000 --reload
```

```powershell
cd webui
npm install
npm run dev
```

Danach `http://localhost:3000` im Browser oeffnen.

## Runbook

Diese Befehle sind die kurzen Standardwege fuer den lokalen Alltag.

Virtuelle Umgebung aktivieren:

```powershell
.\.venv\Scripts\Activate.ps1
```

Training und Artefakte neu erzeugen:

```powershell
python train.py
```

Nur Dataset/Scaler/Manifest neu bauen:

```powershell
python train.py --dataset-only
```

Tests ausfuehren:

```powershell
pytest
```

Empfohlener kompletter Arbeitsablauf:

```powershell
python train.py
pytest
lean backtest .
lean report --backtest-results .\backtests\<BACKTEST_ORDNER>\<ERGEBNIS_ID>.json --report-destination .\backtests\<BACKTEST_ORDNER>\report.html --overwrite
python -m http.server 8000
git status
```

Lean-Backtest aus dem Projektordner starten:

```powershell
lean backtest .
```

Fertigen Backtest erkennen:

```powershell
Get-ChildItem .\backtests\<BACKTEST_ORDNER>\*-summary.json
```

Offiziellen Lean-HTML-Report erzeugen:

```powershell
lean report --backtest-results .\backtests\<BACKTEST_ORDNER>\<ERGEBNIS_ID>.json --report-destination .\backtests\<BACKTEST_ORDNER>\report.html --overwrite
```

Beispiel vom letzten erfolgreichen Lauf:

```powershell
lean report --backtest-results .\backtests\2026-05-07_15-05-06\1366365999.json --report-destination .\backtests\2026-05-07_15-05-06\report.html --overwrite
```

Webui lokal starten (API-Server und Frontend in zwei Terminals):

```powershell
uvicorn monitoring.api_server:app --port 8000 --reload
```

```powershell
cd webui
npm run dev
```

Danach:

```text
http://localhost:3000          (Overview)
http://localhost:3000/risk     (Risk)
```

Git-Status vor einem Commit pruefen:

```powershell
git status
```

## Phase-1- und Phase-9-Entscheidungen

Das erste V1-Universum war absichtlich klein und gemischt:

- `AAPL`
- `SPY`
- `QQQ`
- `BTCUSD`

Das aktuelle V2-Universum erweitert dies auf:

- `AAPL`
- `SPY`
- `QQQ`
- `IWM`
- `EEM`
- `BAC`
- `IBM`
- `BTCUSD`
- `ETHUSD`
- `LTCUSD`

Gemeinsame V1-Datenabdeckung:

- Start: `2014-12-01`
- Ende: `2018-08-13`
- Aufloesung: `Daily`

Erste Fenster:

- Training: `2014-12-01` bis `2017-06-30`
- Validierung: `2017-07-01` bis `2017-12-31`
- Backtest: `2018-01-01` bis `2018-08-13`

Erste Zieldefinition:

- Zieltyp: naechste Tagesrichtung
- Label: `1`, wenn die naechste Close-to-Close-Rendite positiv ist, sonst `0`

Erste Feature-Ideen:

- 1d-, 5d- und 20d-Renditen
- 5d- und 20d-Volatilitaet
- 5d- und 20d-Momentum
- Tagesrange und Open-Close-Range
- Volumenaenderung

Detaillierte Phase-Ergebnisse (Phase-2 bis Phase-10, Phase-V2-1 bis Phase-V2-15, Visualization-Unification) wurden nach development/Changelog.md verschoben, um dieses README kurz zu halten.

## V2 Infrastruktur-Entscheidung

JSONL wird nicht als Experience-Fallback verwendet. V2 nutzt stattdessen Redis als schnellen temporaeren Puffer und PostgreSQL als permanente Experience Database.

Der geplante Datenfluss:

1. Signal entsteht in Backtest, Observation Mode oder Live Loop.
2. Rohmetriken werden sofort nach Redis geschrieben, zum Beispiel per `XADD` Stream oder `LPUSH` Queue.
3. Ein separater Worker liest Redis entkoppelt per `XREAD` oder `BLPOP`.
4. Der Worker schreibt Events per Batch-Insert nach PostgreSQL.
5. Controlled Retraining liest spaeter nur aus PostgreSQL als Single Source of Truth.

## V2 Phasenplan Ab Jetzt

1. [x] V2-1: Fork & Architektur-Fundament
2. [x] V2-2: Lean-Datenpipeline V2
3. [x] V2-3: Dynamic Risk & Position Sizing
4. [x] V2-4: HTML Live Volatility Dashboard
5. [x] V2-5: Docker Compose Infrastruktur fuer Lean, Grafana, Redis und PostgreSQL
6. [x] V2-6: Regime Detection
7. [x] V2-7: Expert-Datasets fuer Bullish, Bearish, Sideways und Volatility
8. [x] V2-8: Experten-Modelle
9. [x] V2-8.5: Expert Model Stabilization & Quality Gates
10. [x] V2-9: Gating Network
11. [x] V2-10: Zentraler Markt-Analysator
12. [x] V2-11: 3D Topology Market Modeling
13. [x] V2-12: Market Impact & Liquidity Engine
14. [x] V2-13: Redis Experience Queue/Stream
15. [x] V2-14: PostgreSQL Persistence Worker
16. [x] V2-15: Observation Mode
17. [x] V2-16: Performance Trigger
18. [ ] V2-17: Controlled Retraining
19. [ ] V2-17.5: Non-deterministic Topology & Retrain-Trigger Upgrade (ersetzt die deterministischen V2-10/V2-11-Heuristiken durch datengetriebene Versionen, sobald V2-13/14/16/17 stehen)
20. [ ] V2-18: Grafana Monitoring Ausbau
21. [ ] V2-19: Telegram Alerts
22. [ ] V2-20: Lean Backtesting Integration
23. [ ] V2-21: Paper Trading Vorbereitung
24. [ ] V2-22: Live Deployment Struktur
25. [ ] V2-23.1: Datengetriebene Liquidity-Threshold-Kalibrierung — ersetzt statische Participations-Schwellenwerte durch kalibrierte Werte aus echten Fill-Daten, sobald V2-13/14 Experience-Pipeline und V2-16/17 Controlled Retraining stehen
26. [ ] V2-24: Finaler V2 Review

## Hinweise

- `ml/model.pt`, `.env` und `ib_config.py` bleiben lokal und werden nicht versioniert.
- Das Projektgeruest ist bewusst konservativ: Zuerst ein stabiler Kern, dann Online-Lernen und 3D-Simulation.
