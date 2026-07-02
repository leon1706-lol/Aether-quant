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

## Phase-V2-10-Ergebnis

Der Zentrale Markt-Analysator macht jetzt zusaetzlich Folgendes:

- fuegt `analyzer/market_analyzer.py` als reine, deterministische Entscheidungsschicht hinzu, die Experten- (`moe_gating`), Regime-, Topology- (optional, bis V2-11) und Risiko-Ausgaben (Risk Lock, Position Sizing) zu einer finalen Kategorie zusammenfuehrt
- ersetzt die bisherige ad-hoc if/elif-Kette in `main.py.on_data()` durch einen Aufruf von `build_market_analysis_decision(...)`, ohne das tatsaechliche Order-Placement-Verhalten zu aendern: `_apply_signal` wird weiterhin nur bei der Kategorie `trade` ausgefuehrt
- klassifiziert jedes Asset pro Bar in genau eine von fuenf Kategorien: `observe`, `simulate`, `trade`, `reduce_risk`, `retrain_candidate`
- priorisiert Risikoeindaemmung vor Modell-Gesundheit vor Profit-Aktion vor Paper-Tracking vor reiner Beobachtung (portfolioweiter Trade Lock und Asset-Risk-Off-Regime schlagen immer `retrain_candidate` und `trade`)
- erkennt `retrain_candidate` ueber eine zustandslose Heuristik (keine aktiven Experten plus niedrige Regime-Confidence), da die zeitfensterbasierten Performance-Trigger erst in V2-16 folgen
- schreibt die volle Entscheidung inklusive `reasons`-Liste als `market_analysis`-Block in jedes Asset-Signal in `visualization/state.json`, automatisch sichtbar im Webui ueber die bestehende FastAPI-Pipeline
- fuegt `tests/test_market_analyzer.py` mit 13 Tests hinzu (alle fuenf Kategorien, Topology-Absenz, zwei Prioritaets-Tiebreaks)

## Phase-V2-11-Ergebnis

Das 3D Topology Market Modeling macht jetzt zusaetzlich Folgendes:

- fuegt `topology/market_topology.py` als reine, deterministische Cross-Asset-Schicht hinzu: paarweise Pearson-Korrelation aus Returns, Union-Find-Clustering ueber einen Korrelations-Schwellenwert, 3D-Koordinaten (aehnliche Assets nahe beieinander, hohe Volatilitaet trennt sich auf der z-Achse)
- berechnet Topology einmal pro Bar in `main.py` aus `self.symbol_windows` (Stand der vorherigen Bar, kein Lookahead) vor der Pro-Asset-Schleife, ohne diese umzustrukturieren
- schreibt `visualization/topology_state.json` und einen `state["topology"]`-Block, sowie pro Asset einen `topology`-Kontext (`cluster_id`, `correlation_strength`, `market_distance`, `topology_risk`) in `visualization/state.json`
- ersetzt die bisherige Orbit-Platzierung in `_build_scene_payload` durch echte Topology-Koordinaten und ergaenzt Korrelations-Links zwischen Assets in der bestehenden Overview-Szene
- **aendert echte Handelsentscheidungen**: `analyzer/market_analyzer.py` bekommt zwei neue, deterministische Prioritaetsstufen — ein Asset mit `topology_risk == "elevated"` wird zu `reduce_risk` gezwungen, ein isoliertes Asset (`topology_risk == "isolated"`, keine hinreichend korrelierten Peers) kann nicht mehr `trade` erreichen und faellt auf `simulate` zurueck
- fuegt einen neuen Webui-Tab `/topology` hinzu (eigene 3D-Szene mit Einfaerbung nach Action/Regime/Risk, plus lesbare Cluster-Liste) und einen `/api/topology`-Endpunkt in `monitoring/api_server.py`
- fuegt `tests/test_market_topology.py` (stabile Koordinaten, staerkere Links fuer korrelierte Assets, robust bei fehlenden/duennen Daten, Regime-Label-Aggregation) sowie vier neue Faelle in `tests/test_market_analyzer.py` hinzu
- dokumentiert in `V2-17.5` (siehe Phasenplan unten), dass diese deterministischen Regeln spaeter durch datengetriebene/gelernte Versionen ersetzt werden sollen, sobald die Experience-Pipeline (V2-13/14) und kontrolliertes Retraining (V2-16/17) stehen

## Phase-V2-12-Ergebnis

Die Market Impact & Liquidity Engine macht jetzt zusaetzlich Folgendes:

- fuegt `liquidity/market_liquidity.py` als reine, deterministische Per-Asset-Liquiditaetsschicht hinzu: schaetzt taeglich gehandeltes Dollar-Volumen (`DDV = close × volume`), Orderwert, Participations-Rate, Slippage und Round-Trip-Kosten ohne externe Daten
- klassifiziert jeden Asset-Order-Versuch in `normal`, `thin`, `high_impact` oder `blocked` und empfiehlt `allow`, `reduce_size`, `simulate_instead` oder `block`
- wendet bei `high_impact` automatisch eine konfigurierbare Groessenreduktion (`high_impact_size_factor=0.5`) an, bevor der Markt-Analysator entscheidet
- ergaenzt `analyzer/market_analyzer.py` um zwei neue deterministische Prioritaetsstufen: `liquidity_blocked` zwingt zu `simulate`, `liquidity_thin` zwingt ebenfalls zu `simulate` (unter den bestehenden Risk-Off- und Topology-Prioritaeten, aber ueber dem `trade`-Pfad)
- schreibt alle Liquidity-Felder (`daily_dollar_volume`, `participation_rate`, `estimated_slippage`, `spread_proxy`, `estimated_round_trip_cost`, `liquidity_risk`, `recommended_action`, `adjusted_target_weight`) als `liquidity`-Block in jedes Asset-Signal in `visualization/state.json`
- fuegt statische Bid-Ask-Spread-Proxies per Security-Type ein (Equity: 5 bps, Crypto: 20 bps), da echte Bid-Ask-Daten aus Daily-OHLCV nicht ableitbar sind
- belegt in Lean tatsaechliche Transaktionskosten per Asset: `ConstantPercentageFeeModel(0.0025)` fuer Crypto (25 bps Taker-Proxy) und `ConstantFeeModel(1.0)` fuer Equities ($1/Trade IB-Proxy)
- fuegt `webui/src/components/risk/LiquidityTable.tsx` als neue Liquiditaets-Panel auf der Risk-Seite hinzu: zeigt per Asset DDV, Orderwert, Participations-Rate, Slippage, Spread, Round-Trip-Kosten, Risk-Level und empfohlene Aktion mit farbigen Badges
- fuegt `Dockerfile` (Multi-Stage: Node.js Webui-Build → Python Laufzeit) und erweitertes `docker-compose.yml` (neuer `aether-quant`-Service auf Port 8000, Grafana auf Port 3001 statt 3000) hinzu, damit die Gesamtinfrastruktur konsistent startbar ist
- fuegt 9 neue Unit-Tests in `tests/test_market_liquidity.py` und 4 neue Faelle in `tests/test_market_analyzer.py` hinzu
- LTCUSD (nur 2 Tage Daten im Universum → DDV unter $100k Floor) trifft korrekt auf `blocked` und wird zu `simulate` gezwungen, ohne den uebrigen Entscheidungsbaum zu stoeren

## Phase-V2-13-Ergebnis

Die Redis Experience Queue macht jetzt zusaetzlich Folgendes:

- fuegt `experience/redis_queue.py` als neues Modul hinzu mit `build_experience_event()` (pure Funktion) und `ExperienceQueue` (fire-and-forget Redis Stream Publisher)
- schreibt nach jeder vollstaendigen Asset-Entscheidung (nach `signal_payload.update`) sofort ein JSON-Event per `XADD` in den Redis Stream `aether:experience`, begrenzt auf `maxlen=100000` Eintraege (approximativ)
- jedes Event enthaelt: `event_id` (UUID), `event_type`, `created_at` (ISO UTC), `mode` (`backtest`/`observation`/`paper`/`live`), `symbol`, `ticker`, `signal`, `action`, `execution_note`, `probability_up`, `confidence`, `target_weight`, `regime`, `moe_gating`, `topology`, `liquidity`, `market_analysis`, `portfolio` (mit `total_value`, `cash`, `current_drawdown`)
- schlaegt Redis Fehler still nieder: `ExperienceQueue.push()` gibt `False` zurueck und loggt eine WARNING, der Lean-Loop wird niemals blockiert oder unterbrochen
- laedt `redis_url` aus der Umgebungsvariablen `AETHER_REDIS_URL` (gesetzt in `docker-compose.yml` auf `redis://redis:6379/0`), faellt zurueck auf `redis://localhost:6379/0` fuer lokale Entwicklung
- konfigurierbar ueber `config.json phase_v2.experience` mit `enabled`, `redis_stream` und `maxlen`
- Redis-Import ist deferred (innerhalb von `ExperienceQueue.__init__`), damit der Code auch in Lean-Umgebungen ohne `redis`-Paket importierbar bleibt
- fuegt `redis>=5.0.0` zu `requirements.txt` und `fakeredis>=2.20.0` zu `requirements-dev.txt` hinzu
- fuegt `tests/test_experience_queue.py` mit 8 Tests hinzu (Pflichtfelder im Schema, disabled = sicheres No-Op, Redis nicht erreichbar = kein Crash, JSON-Serialisierung, konfigurierbarer Stream-Name, alle 4 Modes, Push schreibt in Stream, Event-ID eindeutig)
- Stop bei Redis: kein PostgreSQL in V2-13; V2-14 baut den Persistence Worker (`XREAD → INSERT INTO experience_events`)

## Phase-V2-14-Ergebnis

Der PostgreSQL Persistence Worker macht jetzt zusaetzlich Folgendes:

- fuegt `experience/postgres_worker.py` als eigenstaendigen, synchronen Worker hinzu, der `aether:experience` per `XREADGROUP` liest und Events dauerhaft in PostgreSQL speichert
- legt die Tabelle `experience_events` mit eingebettetem DDL an: `event_id` (UUID, UNIQUE), `created_at`, `ingested_at`, `mode`, `ticker`, `symbol`, `signal`, `action`, `confidence`, `target_weight`, `payload` (JSONB) plus 5 Indizes — kein Alembic, keine Migrationsdateien
- nutzt `ON CONFLICT (event_id) DO NOTHING` fuer sichere idempotente Wiederholung bei Redis-Wiederlieferung nach Worker-Absturz
- routet fehlerhafte JSON-Nachrichten in den Dead-Letter-Stream `aether:experience:deadletter` und quittiert sie sofort per `XACK`, ohne den Betrieb zu unterbrechen
- laesst Nachrichten bei PG-Fehler ungequittiert — sie bleiben pending und werden nach dem Redis Visibility-Timeout erneut geliefert
- implementiert exponentiellen Backoff (1→2→4→...→60 s) und automatischen PG-Reconnect in der `run()`-Schleife
- exportiert `event_to_row` (pure Funktion, kein I/O) und `PostgresWorker` aus `experience/__init__.py`
- fuegt `psycopg[binary]>=3.1` zu `requirements.txt` und `requirements-dev.txt` hinzu
- legt `requirements-worker.txt` als minimale Abhaengigkeitsliste fuer den Worker-Container an
- baut `Dockerfile.worker` als minimales `python:3.11-slim`-Image mit nur `redis` und `psycopg[binary]`
- fuegt den `experience-worker`-Service in `docker-compose.yml` hinzu (`depends_on: redis:healthy, postgres:healthy`, `restart: unless-stopped`)
- ergaenzt `config.json phase_v2.experience` um den `worker`-Sub-Block fuer Group, Consumer, Batch-Size, Dead-Letter-Stream und Backoff-Max
- fuegt 7 Tests in `tests/test_postgres_worker.py` hinzu: skalare Felder korrekt extrahiert, Payload vollstaendig, Batch-Persistierung, Duplikat-Idempotenz, Dead-Letter-Routing, PG-Fehler laesst Messages pending, leerer Stream gibt 0
- Stop bei PostgreSQL: V2-15 baut Observation Mode auf dem jetzt vorhandenen Experience-Trail auf

## Visualization-Unification-Ergebnis

Die Zusammenfuehrung der Visualisierung macht jetzt zusaetzlich Folgendes:

- ersetzt `dashboard.html` und `volatility_dashboard.html` durch eine einzige React/Vite-Webui unter `webui/` auf `http://localhost:3000`
- fuegt `monitoring/api_server.py` als FastAPI-JSON-API hinzu, die `visualization/state.json`, `visualization/scene.json` und die Grafana-Exporte unter `localhost:8000` bereitstellt, statt dass das Frontend Dateien direkt vom Dateisystem liest
- bildet die Overview-Seite (Scorecards, Asset-Heatmap, Signal-Board, Positionen, Strategy/Risk-Karten, Monitoring-Feeds) und die Risk-Seite (Risk Core, Asset-Volatility-/Sizing-Tabelle) 1:1 auf die bisherigen HTML-Dashboards ab
- rendert die Marktszene erstmals echt dreidimensional und drehbar mit `@react-three/fiber`/`@react-three/drei` statt der bisherigen 2D-Div-Annaeherung, als Grundlage fuer das spaetere V2-11 3D Topology Market Modeling
- behaelt das bestehende Polling-Muster bei (React Query, 5s Intervall) und aendert nichts an den Python-Schreibern von `state.json`/`scene.json`

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
16. [ ] V2-15: Observation Mode
17. [ ] V2-16: Performance Trigger
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
