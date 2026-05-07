# Aether Quant

Aether Quant ist ein Trading-Projekt auf Basis von QuantConnect Lean, PyTorch und einer lokalen Visualisierungsschicht.
Das Ziel ist ein adaptives Modell, das auf Lean-Daten trainiert wird, im Backtest validiert werden kann, spaeter ueber Interactive Brokers im Paper Trading laeuft und seinen Zustand fuer ein Live-Dashboard bereitstellt.

## Aktueller Stand

Phase 10 ist gestartet. Phase 9 ist sauber abgeschlossen und das erste Multi-Asset-V2-Universum ist abgesichert:

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

## Projektstruktur

```text
aether-quant/
|-- lean.json
|-- config.json
|-- backtests/
|-- data/
|-- main.py
|-- train.py
|-- ml/
|   |-- model_weights.json
|-- visualization/
|   |-- state.json
|-- dashboard.html
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
- prueft vor dem Training Datenpfade, Asset-Konfiguration und Zeitfenster mit klaren Fehlermeldungen
- prueft vor Lean-Inferenz, ob Modell-, Feature- und Scaler-Artefakte vorhanden sind

## Naechste technische Phasen

- Phase 10: Stabilisierung weiter ausbauen
- Phase 7: Kontrolliertes Online-Lernen auf stabilerer Beobachtungsbasis

## Hinweise

- `ml/model.pt`, `.env` und `ib_config.py` bleiben lokal und werden nicht versioniert.
- Das Projektgeruest ist bewusst konservativ: Zuerst ein stabiler Kern, dann Online-Lernen und 3D-Simulation.
