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
|-- docs/
|   |-- v2_architecture.md
|-- infrastructure/
|   |-- README.md
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
|-- dashboard.html
|-- volatility_dashboard.html
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
- `dashboard.html`: Browser-Dashboard fuer Portfolio-, Markt-, Risiko- und Modellstatus
- `volatility_dashboard.html`: V2 Live-Volatility-Dashboard fuer Positionsgroesse, Hebel und Volatilitaetsregime
- `docker-compose.yml`: lokale Infrastruktur fuer Lean, Grafana, Redis und PostgreSQL
- `infrastructure/`: Startbefehle, Netzwerk- und Datenfluss-Dokumentation fuer Docker Compose
- `docs/v2_architecture.md`: V2-Systemarchitektur mit Prozessfluss und Tech-Stack-Diagrammen
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

5. Dashboard lokal ausliefern:

```powershell
python -m http.server 8000
```

Danach `http://localhost:8000/dashboard.html` im Browser oeffnen.

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

Dashboard lokal starten:

```powershell
python -m http.server 8000
```

Danach:

```text
http://localhost:8000/dashboard.html
http://localhost:8000/volatility_dashboard.html
```

Grafana/CSV-Dateien lokal ausliefern:

```powershell
python -m http.server 8010
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

## Phase-2-Ergebnis

Die aktuelle Pipeline macht Folgendes:

- Lean-ZIP-Dateien fuer `AAPL`, `SPY`, `QQQ` und `BTCUSD` laden
- Preise normalisieren
- Assets pro Datenfenster laden, ohne sie auf die kleinste gemeinsame Schnittmenge zu reduzieren
- Features und Zielvariable berechnen
- Train-, Validation- und Backtest-Splits erzeugen
- den Scaler auf dem Trainingssplit fitten und speichern

## Phase-3-Ergebnis

Die aktuelle Trainingsstufe macht zusaetzlich Folgendes:

- ein robusteres MLP-Klassifikationsmodell in PyTorch trainieren
- Layer-Normalisierung und Dropout fuer stabileres Verhalten nutzen
- Asset-Kontext als zusaetzliche Modell-Eingabe verwenden
- Validierungsverlust fuer Early Stopping verwenden
- die Entscheidungsschwelle auf dem Validation-Split optimieren
- Train-, Validation- und Backtest-Metriken speichern
- einen binaren Checkpoint in `ml/model.pt` sichern
- einen JSON-Export fuer spaetere Lean-Inferenz vorbereiten

## Phase-4-Ergebnis

Die aktuelle Laufzeitstufe macht jetzt zusaetzlich Folgendes:

- laedt `model_weights.json`, `feature_schema.json`, `dataset_manifest.json` und `scaler_stats.json`
- berechnet dieselben Features wie das Training direkt in Lean
- fuehrt den exportierten MLP-Forward-Pass lokal aus
- erzeugt aus der Modellwahrscheinlichkeit echte `buy`-, `sell`- und `hold`-Signale
- schreibt Modellstatus, Schwellenwerte und Signalwahrscheinlichkeiten in `visualization/state.json`

## Phase-5-Ergebnis

Die aktuelle Validierungsstufe macht jetzt zusaetzlich Folgendes:

- berechnet Strategie-Returns aus den Modellwahrscheinlichkeiten
- vergleicht die Strategie gegen Buy-and-Hold
- exportiert Return, annualisierte Volatilitaet, Sharpe und Max Drawdown
- schreibt Equity-Curves fuer Validation und Backtest nach `backtests/equity_curves.csv`
- speichert einen Gesamtbericht in `backtests/strategy_report.json`

## Phase-6-Ergebnis

Die aktuelle Paper-Trading-Vorbereitung macht jetzt zusaetzlich Folgendes:

- trennt Lean-Runtime-Abhaengigkeiten von lokalen Dev-Abhaengigkeiten
- fuehrt den Algorithmus erfolgreich in der echten lokalen Lean-Docker-Laufzeit aus
- nutzt Risk Controls fuer Daily- und Total-Drawdown
- blockiert neue Trades bei Risk-Breach und liquidiert optional offene Positionen
- nutzt Mindest-Confidence und Cooldown zwischen Trades fuer konservativere Signal-Ausfuehrung

## Phase-8-Ergebnis

Die aktuelle Visualisierungsstufe macht jetzt zusaetzlich Folgendes:

- erweitert `visualization/state.json` um Dashboard-, Monitoring- und Szenendaten
- erzeugt `visualization/scene.json` als Grundlage fuer die Markt-/Portfolio-Buehne
- exportiert Grafana-freundliche Snapshots und CSV-Dateien unter `visualization/grafana/`
- zeigt im Dashboard Scorecards, Asset-Heatmap, Risk-Band, Positionen und eine 3D-artige Asset-Szene

## Phase-9-Ergebnis

Die aktuelle Multi-Asset-Stufe macht jetzt zusaetzlich Folgendes:

- erweitert das Universum auf Aktien, ETFs und drei Spot-Krypto-Coins
- leitet `ETHUSD`- und `LTCUSD`-Daily-Serien aus vorhandenen Coinbase-Minute-Daten ab
- nutzt eine flexiblere Trainingspipeline, die Assets nicht mehr auf die kleinste gemeinsame Schnittmenge reduziert
- bewertet jedes Asset nach Datenqualitaet, Trainingszeilen und Backtestzeilen
- trainiert Modell und Scaler nur auf ausreichend belastbaren Assets
- markiert zu kurze Reihen wie `ETHUSD` und `LTCUSD` automatisch als `observation_only`
- verhindert in Lean Trades auf Observation-only Assets, zeigt sie aber weiter in State, Dashboard und Szene
- begrenzt die Portfolio-Ausweitung mit maximalen aktiven Positionen sowie Equity- und Krypto-Exposure-Caps
- fuehrt einen erfolgreichen Lean-Backtest ueber das erweiterte Daily-Universum aus

## Phase-10-Ergebnis

Die aktuelle Stabilisierung macht jetzt zusaetzlich Folgendes:

- haelt grosse lokale Artefakte wie `data/`, `backtests/`, `ml/datasets/` und `.venv/` aus dem oeffentlichen Git-Repo heraus
- dokumentiert die wichtigsten lokalen Befehle fuer Training, Tests, Lean-Backtests, Lean-Reports und Dashboard
- nutzt strukturierte Laufzeitlogs in `train.py` fuer Dataset-Aufbau, Asset-Qualitaet und Trainingsfortschritt
- fuegt erste `pytest`-Tests fuer Feature Engineering, Asset-Quality-Entscheidungen und Scaler-Fitting hinzu
- fuegt Risk-Control-Tests fuer Drawdown-Locks, Positionslimits und Exposure-Caps hinzu
- prueft vor dem Training Datenpfade, Asset-Konfiguration und Zeitfenster mit klaren Fehlermeldungen
- prueft vor Lean-Inferenz, ob Modell-, Feature- und Scaler-Artefakte vorhanden sind

## Phase-V2-1-Ergebnis

Die neue V2-Fork macht jetzt zusaetzlich Folgendes:

- nutzt den bisherigen V1/Phase-10-Code als stabiles Grundgeruest
- legt die V2-Modulstruktur fuer MoE, Experten, Regime, Topology, Experience, Risk und Monitoring an
- dokumentiert den geplanten V2-Prozessfluss in `docs/v2_architecture.md`
- dokumentiert den geplanten Tech-Stack fuer Docker, Lean, PyTorch, PostgreSQL, Grafana, Telegram und HTML-Dashboard
- haelt Training und Backtesting weiterhin auf dem lokalen Lean `data/` Ordner als Hauptdatenquelle

## Phase-V2-2-Ergebnis

Die V2 Lean-Datenpipeline macht jetzt zusaetzlich Folgendes:

- legt `data_pipeline/` als stabile V2-Schicht ueber der bestehenden `train.py` Pipeline an
- definiert ein V2-Pipeline-Manifest fuer Datenquelle, Universum, Features, Zeitfenster und Asset-Qualitaet
- dokumentiert explizit, dass Training und Backtesting weiter ueber den lokalen Lean `data/` Ordner laufen
- bereitet saubere Anschlusspunkte fuer MoE-Experten, Regime Detection, Topology, Dynamic Risk und Volatility Dashboard vor
- fuegt Tests hinzu, die diesen Lean-Datenvertrag absichern

## Phase-V2-3-Ergebnis

Die V2 Dynamic-Risk- und Position-Sizing-Stufe macht jetzt zusaetzlich Folgendes:

- fuegt `risk/position_sizing.py` als testbare V2-Risikologik hinzu
- klassifiziert Volatilitaet in `low_volatility`, `normal_volatility` und `high_volatility`
- passt Ziel-Positionsgroessen an die aktuelle Rolling Volatility an
- reduziert Positionsgroessen in hoher Volatilitaet und erlaubt kontrollierte Erhoehung in ruhigen Marktphasen
- berechnet `base_target_weight`, dynamisches `target_weight`, annualisierte Volatilitaet und `leverage_factor`
- schreibt diese Werte in Runtime-State, Dashboard-Heatmap und `visualization/grafana/runtime_asset_metrics.csv`
- bereitet damit das HTML Live Volatility Dashboard vor

## Phase-V2-4-Ergebnis

Das HTML Live Volatility Dashboard macht jetzt zusaetzlich Folgendes:

- fuegt `volatility_dashboard.html` als eigene V2-Live-Ansicht hinzu
- liest automatisch `visualization/state.json`
- aktualisiert sich alle 5 Sekunden
- zeigt Portfolio, Risk Lock, Drawdown, Zielvolatilitaet und maximalen Hebelfaktor
- zeigt pro Asset Signal, Volatilitaetsregime, annualisierte Volatilitaet, Basisgewicht, dynamisches Zielgewicht, Hebelfaktor, Confidence und Sizing-Grund
- funktioniert im Backtest-/Observation-Modus ohne Broker-API-Key

## Phase-V2-6-Ergebnis

Die V2 Regime Detection macht jetzt zusaetzlich Folgendes:

- fuegt `regime/market_regime.py` als testbare quantitative Regime-Schicht hinzu
- erkennt `bullish`, `bearish` und `sideways` aus 5d/20d Momentum
- erkennt `low_volatility`, `normal_volatility` und `high_volatility` aus Rolling Volatility
- kombiniert Trend, Volatilitaet, Drawdown und optionale Korrelation zu `risk_on`, `risk_neutral` oder `risk_off`
- schreibt pro Asset einen `regime`-Block in den Lean Runtime-State
- exportiert Regime-Felder in die Runtime-Monitoring-CSV fuer Grafana

## Phase-V2-7-Ergebnis

Die V2 Expert-Dataset-Stufe macht jetzt zusaetzlich Folgendes:

- fuegt `experts/expert_datasets.py` als Slice-Schicht fuer spaetere Expertenmodelle hinzu
- nutzt die quantitative Regime Detection fuer Bullish-, Bearish-, Sideways- und Volatility-Slices
- filtert Expert-Trainingsdaten auf `training_eligible` Assets
- erzeugt beim Dataset-Build lokale Expert-CSV-Dateien unter `ml/expert_datasets/`
- schreibt `ml/expert_dataset_manifest.json` mit Row Counts, Split Counts, Tickern, Target Balance und Routing-Filtern
- haelt die generierten Expert-Artefakte aus Git heraus

## Phase-V2-8-Ergebnis

Die V2 Experten-Modell-Stufe macht jetzt zusaetzlich Folgendes:

- trainiert getrennte PyTorch-Modelle fuer `bullish`, `bearish`, `sideways` und `volatility`
- nutzt dieselbe MLP-Familie wie das Basismodell, aber mit regime-spezifischen Trainingsdaten
- fuegt `python train.py --experts-only` fuer reines Expert-Training hinzu
- aktualisiert bei normalem `python train.py` auch die Expert-Modelle
- schreibt lokale Expert-Gewichte und Metriken unter `ml/expert_models/<expert>/`
- schreibt eine Gesamtuebersicht nach `ml/expert_training_metrics.json`
- haelt alle generierten Expert-Modellartefakte aus Git heraus

## Phase-V2-8.5-Ergebnis

Die V2 Expert-Stabilisierung macht jetzt zusaetzlich Folgendes:

- nutzt fuer Experten kleinere Default-Netze mit staerkerem Dropout und hoeherem Weight Decay
- reduziert Expert-Training standardmaessig auf weniger Epochen und strengere Early-Stopping-Patience
- bewertet jeden Experten mit einem Quality-Gate gegen Validation, Backtest, MCC und Train/Backtest-Gap
- markiert Experten als `stable`, `watchlist` oder `disabled_for_gating`
- schreibt `gating_eligible_experts` und `disabled_for_gating_experts` in `ml/expert_training_metrics.json`
- verhindert damit, dass das spaetere Gating Network schwache oder overfittete Experten blind verwendet

## Phase-V2-9-Ergebnis

Das V2 Gating Network macht jetzt zusaetzlich Folgendes:

- fuegt `moe/gating.py` als erklaerbaren Manager fuer die Expert-Modelle hinzu
- gewichtet Experten nach Quality Gate, Regime-Passung und Backtest-/Validation-Stabilitaet
- nutzt `stable` und `watchlist` Experten, ignoriert aber `disabled_for_gating`
- laedt in `main.py` lokale Expert-JSON-Exports aus `ml/expert_models/<expert>/model_weights.json`
- kombiniert Basismodell-Wahrscheinlichkeit und Experten-Wahrscheinlichkeit zu einer finalen MoE-Wahrscheinlichkeit
- schreibt `moe_gating`, Expert-Wahrscheinlichkeiten, aktive Experten und Entscheidungstyp in Runtime-State und Grafana-CSV
- faellt automatisch auf das Basismodell zurueck, falls Expert-Artefakte fehlen

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
11. [ ] V2-10: Zentraler Markt-Analysator
12. [ ] V2-11: 3D Topology Market Modeling
13. [ ] V2-12: Market Impact & Liquidity Engine
14. [ ] V2-13: Redis Experience Queue/Stream
15. [ ] V2-14: PostgreSQL Persistence Worker
16. [ ] V2-15: Observation Mode
17. [ ] V2-16: Performance Trigger
18. [ ] V2-17: Controlled Retraining
19. [ ] V2-18: Grafana Monitoring Ausbau
20. [ ] V2-19: Telegram Alerts
21. [ ] V2-20: Lean Backtesting Integration
22. [ ] V2-21: Paper Trading Vorbereitung
23. [ ] V2-22: Live Deployment Struktur
24. [ ] V2-23: Finaler V2 Review

## Hinweise

- `ml/model.pt`, `.env` und `ib_config.py` bleiben lokal und werden nicht versioniert.
- Das Projektgeruest ist bewusst konservativ: Zuerst ein stabiler Kern, dann Online-Lernen und 3D-Simulation.
