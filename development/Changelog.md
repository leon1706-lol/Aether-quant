# Changelog

Detaillierte Phase-Ergebnisse fuer Aether Quant, verschoben aus `README.md`
(siehe dort fuer aktuellen Stand, Projektstruktur und Runbook). Neueste
Eintraege unten, chronologisch nach Phase geordnet.

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
- dokumentiert den geplanten V2-Prozessfluss in `development/v2_architecture.md`
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
- dokumentiert in `V2-17.5` (siehe Phasenplan im README), dass diese deterministischen Regeln spaeter durch datengetriebene/gelernte Versionen ersetzt werden sollen, sobald die Experience-Pipeline (V2-13/14) und kontrolliertes Retraining (V2-16/17) stehen

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

## Phase-V2-15-Ergebnis

Observation Mode macht jetzt zusaetzlich Folgendes:

- fuegt `phase_v2.runtime` mit `mode` (`backtest`/`observation`/`paper`/`live`, committed Default `"backtest"` — unveraendertes Verhalten von `lean backtest .`) und `allow_live_orders` (Default `false`) zu `config.json` hinzu
- legt das neue, Lean-freie Paket `execution/order_gate.py` an: `resolve_runtime_mode` (Fallback auf `"observation"` bei fehlendem/unbekanntem Wert), `resolve_order_permission` (Wahrheitstabelle: `backtest` immer erlaubt, `observation` **niemals** erlaubt — unabhaengig von allen anderen Flags, `paper`/`live` nur mit `allow_live_orders` + Broker-Konfiguration + bei `live` zusaetzlich gesundem Risk-Lock) und `simulate_fill` (reine Fill-Preis-/Mengen-Mathematik)
- fuegt eine einzige Gate-Methode `_apply_signal`/`_refresh_risk_state` in `main.py` hinzu (`_order_permission()`), die an allen drei realen Order-Stellen (`SetHoldings`, `Liquidate` pro Symbol, portfolioweites `Liquidate` bei Drawdown-Bruch) entscheidet: echte Order oder Simulation
- legt `experience/simulated_portfolio.py` (`SimulatedPortfolioState`) an: verwaltet Fake-Cash/Holdings/Equity-Kurve/Drawdown/Exposure/Turnover komplett im Speicher, ruehrt niemals `self.Portfolio` oder Broker-Aufrufe an; `snapshot()` ist eine Obermenge des bisherigen `portfolio={...}`-Dicts, daher **keine Signaturaenderung** an `build_experience_event`, `event_to_row` oder dem Postgres-DDL noetig (`mode VARCHAR(20)` hat `observation`/`paper`/`live` schon unterstuetzt)
- macht `self._experience_mode` (vorher hart auf `"backtest"` codiert) abhaengig vom neuen `runtime_mode`
- macht Cooldown-, Max-Position- und Exposure-Cap-Pruefungen sowie die Drawdown-/Risk-Lock-Berechnung modusbewusst: wenn echte Orders blockiert sind, zaehlen diese Checks gegen das simulierte statt das reale (in blockierten Modi dauerhaft leere) Portfolio — sonst waeren Risikoregeln in Observation Mode wirkungslos
- legt `experience/observation_metrics.py` an: reine Funktionen (`count_observations`, `signal_distribution`, `action_distribution`, `rejected_by_reason`, `simulated_win_loss`, `simulated_sharpe`, `simulated_max_drawdown`, `compute_observation_summary`) auf einer einzigen `list[dict]`-Form, identisch nutzbar fuer In-Memory-Logs und Postgres-JSONB-Rows; `rejected_by_reason` liest die bereits vorhandene `reasons`-Liste aus `analyzer/market_analyzer.py` — kein neues Schema-Feld noetig
- schreibt neue Dashboard-Exporte `visualization/grafana/observation_summary.json` und `visualization/grafana/observation_equity_curve.csv`, eingebettet zusaetzlich als `state["observation"]` in `visualization/state.json`; deutlich als "SIMULATED - NOT REAL TRADES" markiert
- ergaenzt `monitoring/api_server.py` um `/api/grafana/observation-summary` und `/api/grafana/observation-equity-curve`
- fuegt das Webui-Panel `webui/src/components/monitoring/ObservationPanel.tsx` hinzu (Datentabellen-Stil, kein neues Chart-Package), eingebunden in `webui/src/pages/Overview.tsx`
- fuegt 33 neue Tests hinzu (80 → 113 gesamt): `tests/test_order_gate.py` (10, inkl. der sicherheitskritischen `test_observation_mode_never_allows_orders_even_if_flags_true`), `tests/test_simulated_portfolio.py` (9), `tests/test_observation_metrics.py` (14) — `main.py` bleibt bewusst ohne eigene Unit-Tests (Import erfordert `AlgorithmImports`/Lean, was keine der 13 bisherigen Testdateien tut); die Sicherheitsgarantie ist vollstaendig auf Ebene von `order_gate`/`simulated_portfolio` bewiesen
- manuell verifiziert per echtem `lean backtest .`-Lauf mit `mode="observation"` (2014-2018, BTCUSD/ETHUSD/LTCUSD): Lean-eigene Statistik zeigt `"Total Orders": "0"` und `"End Equity": "100000"` (unveraendert) ueber den gesamten Lauf — das reale Portfolio wurde nie angefasst — waehrend das Observation-Panel im Webui echte simulierte Aktivitaet zeigte (Drawdown, Turnover, einen simulierten Risk-Lock-Breach bei -12%)
- Stop: `phase_v2.runtime.mode` wird nur beim Start gelesen, kein Hot-Reload waehrend eines laufenden Runs
- Nach Abschluss zwei Bugs beim Docker-Review gefunden und behoben — siehe `development/Problems.md`: `Dockerfile.worker` kopierte `execution/` nicht (ModuleNotFoundError), `requirements-worker.txt` fehlte `numpy` (ModuleNotFoundError, Crash-Loop im laufenden Container)

## Phase-V2-16-Ergebnis

Performance Triggers macht jetzt zusaetzlich Folgendes:

- legt das neue, Lean-freie Paket `performance/triggers.py` an: 8 Trigger-Funktionen (`observation_count_trigger`, `drawdown_trigger`, `sharpe_degradation_trigger`, `win_rate_trigger`, `confidence_decay_trigger`, `regime_shift_trigger`, `liquidity_warning_trigger`, `risk_lock_trigger`) plus `evaluate_all_triggers()` als Aggregator — reine Funktionen auf derselben `list[dict]`-Form wie `experience/observation_metrics.py` (V2-15), inkl. Wiederverwendung von `simulated_sharpe`/`simulated_max_drawdown` statt Neuimplementierung
- jeder Trigger liefert ein strukturiertes Event: `trigger_id`, `created_at`, `trigger_type`, `severity` (`info`/`warning`/`critical` nach Breach-Ratio-Regel), `mode`, `scope` (`portfolio` oder Ticker), `metric_value`, `threshold`, `message`, `recommended_action`, `retrain_candidate`
- `liquidity_warning_trigger` zaehlt bewusst nur `block`/`reduce_size` als Ablehnung — `simulate_instead` (Observation-Mode-Routing) wird explizit ausgeschlossen, damit Observation Mode nicht faelschlich wie eine Liquiditaetskrise aussieht
- `risk_lock_trigger` feuert sowohl beim Aktivierungs-Uebergang (`warning`) als auch bei anhaltender Sperre ueber `max_consecutive_locked_events` (`critical`, immer `retrain_candidate=True`) — dafuer bekommt der `portfolio`-Block in `main.py` zusaetzlich `trade_lock_active`/`trade_lock_reason` (rein additiv, keine Schema-/DDL-Aenderung noetig)
- ergaenzt `config.json phase_v2.performance_triggers` mit den 7 vom Nutzer vorgegebenen Schwellenwerten plus 5 weiteren (Confidence-Decay/-Instabilitaet, Risk-Lock-Dauer, Rolling-Window, Suppression-Minuten)
- legt `performance/postgres_triggers.py` an: eingebettetes DDL fuer eine **eigene** Tabelle `performance_triggers` (nicht `experience_events` mit neuem `event_type`, damit Grafana/Phase 17 sauber darauf zugreifen koennen) plus `performance_trigger_watermark` fuer den Fortschritt, `ON CONFLICT (trigger_id) DO NOTHING` plus explizite Suppression-Window-Pruefung gegen Duplikat-Spam bei anhaltenden Breaches
- legt `performance/trigger_worker.py` als eigenstaendigen Worker an (`python -m performance.trigger_worker`, `--once`-Flag wie `postgres_worker.py`), der `experience_events` per Watermark abgrast und Trigger dauerhaft persistiert — bewusst **nicht** synchron in `main.py`/Lean, weil der asynchrone Redis→Worker-Pfad zum Zeitpunkt einer Mid-Backtest-Abfrage noch nicht aufgeholt haben koennte (gleiches Entkopplungsprinzip wie V2-13/14)
- `main.py` bekommt zusaetzlich eine schnelle, rein In-Memory-Ansicht (`_build_performance_triggers_view()`, ueber `_observation_event_log`) fuer `state["performance_triggers"]` und `visualization/grafana/performance_triggers.json` — explizit als nicht-dauerhaft markiert (`source: "in_memory_current_run"`), die Postgres-Tabelle bleibt die einzige Quelle fuer Phase 17
- neuer Service `performance-trigger-worker` in `docker-compose.yml` (nur von `postgres` abhaengig, kein Redis; mountet `config.json` read-only, da die Schwellenwerte Strategie- statt Infra-Konfiguration sind) sowie `Dockerfile.trigger_worker` und `requirements-trigger-worker.txt`
- ergaenzt `monitoring/api_server.py` um `/api/grafana/performance-triggers`
- fuegt das Webui-Panel `PerformanceTriggersPanel.tsx` hinzu (Retrain-Kandidat-Banner, Schweregrad-Verteilung, letzter Trigger, Trigger-Typ-Aufschluesselung) und platziert es zusammen mit `ObservationPanel` ganz oben in der rechten Spalte, damit es bei vielen Assets nicht durch ein wachsendes Signal-Board nach unten verdraengt wird
- fuegt 37 neue Tests hinzu (113 → 150 gesamt): `tests/test_triggers.py` (24), `tests/test_postgres_triggers.py` (11), `tests/test_trigger_worker.py` (2)
- Nebenbei: Dokumentation neu organisiert — `docs/v2_architecture.md` und `infrastructure/README.md` nach `development/` verschoben (als `v2_architecture.md`/`infrastructure.md`), neue `development/Changelog.md` (dieser Datei) und `development/Problems.md` angelegt; Webui bekommt ein durchgaengiges Schwarz/Orange/Weiss-Theme mit orangem Hover-Glow auf allen Panels
- Stop: Phase 16 retrained nichts — `retrain_candidate` ist nur ein Flag fuer V2-17, keine automatischen Modell-Gewichts-Aenderungen

## Visualization-Unification-Ergebnis

Die Zusammenfuehrung der Visualisierung macht jetzt zusaetzlich Folgendes:

- ersetzt `dashboard.html` und `volatility_dashboard.html` durch eine einzige React/Vite-Webui unter `webui/` auf `http://localhost:3000`
- fuegt `monitoring/api_server.py` als FastAPI-JSON-API hinzu, die `visualization/state.json`, `visualization/scene.json` und die Grafana-Exporte unter `localhost:8000` bereitstellt, statt dass das Frontend Dateien direkt vom Dateisystem liest
- bildet die Overview-Seite (Scorecards, Asset-Heatmap, Signal-Board, Positionen, Strategy/Risk-Karten, Monitoring-Feeds) und die Risk-Seite (Risk Core, Asset-Volatility-/Sizing-Tabelle) 1:1 auf die bisherigen HTML-Dashboards ab
- rendert die Marktszene erstmals echt dreidimensional und drehbar mit `@react-three/fiber`/`@react-three/drei` statt der bisherigen 2D-Div-Annaeherung, als Grundlage fuer das spaetere V2-11 3D Topology Market Modeling
- behaelt das bestehende Polling-Muster bei (React Query, 5s Intervall) und aendert nichts an den Python-Schreibern von `state.json`/`scene.json`

## Phase-V2-17-Ergebnis

Controlled Retraining schliesst die Phase-16-Schleife und macht jetzt Folgendes:

- legt das neue Paket `retraining/` an, in derselben pure/IO/Worker-Aufteilung wie `performance/` (V2-16): `planning.py` (rein, Trigger-Auswahl/Cooldown/Mindestbeobachtungen), `postgres_registry.py` (eingebettetes DDL fuer `model_versions` und `retraining_events`), `validation_gate.py` (rein, Kandidat-vs-Aktiv-Vergleich statt `assess_expert_quality`s Fixschwellen), `backtest_gate.py`/`lean_backtest.py` (Backtest-Vergleich plus optionaler, bestmoeglicher Lean-Lauf), `vault_commands.py`/`vault_client.py` (reiner `av`-Kommandobauer plus Subprocess-Wrapper, faengt fehlendes `av`-Binary immer ab), `artifacts.py` (Hashing/Kopieren/Wiederherstellen von Kandidat-Artefakten), `status_export.py` (schreibt `visualization/grafana/retraining_status.json`), `orchestrator.py` (CLI-Subcommands `plan`/`train`/`validate`/`backtest`/`commit`/`promote`/`rollback`/`status`), `worker.py` (`RetrainingWorker`, kontinuierlich per `phase_v2.retraining.enabled` an-/abschaltbar)
- `train.py` bekommt einen vierten Modus `--candidate --version-id <uuid>`: `train_model()`/`write_model_export()`/die Scaler-Schreiblogik (neu extrahiert als `write_scaler_artifacts()`) nehmen jetzt optionale Pfad-Kwargs, mit Default = den bisherigen aktiven `ml/`/`backtests/`-Konstanten, sodass kein bestehender Aufrufer sein Verhalten aendert; der Kandidat-Zweig schreibt ausschliesslich nach `ml/versions/<version_id>/` und beruehrt nie die aktiven Pfade
- `model_versions` trackt `status` (`active`/`candidate`/`rejected`/`promoted`/`rolled_back`/`archived`), `git_commit`, `aether_vault_commit`, Artefaktpfade/-hashes, Trainings-/Validierungs-/Backtest-Fenster und Metriken; ein partieller Unique-Index erzwingt auf DB-Ebene genau ein `active`-Modell
- `retraining_events` trackt `retraining_id`, `source_trigger_id`, `status` (`planned`/`running`/`validated`/`rejected`/`promoted`/`failed`), `reason`, `candidate_version_id`, Metriken und Notizen — der volle Audit-Trail pro Retraining-Versuch
- Promotion kopiert bewusst mehr Dateien als in der urspruenglichen Spezifikation (`model_weights.json`, `scaler.pkl`, `training_metrics.json`) genannt: zusaetzlich `feature_schema.json` und `scaler_stats.json`, weil `main.py`s `_validate_runtime_artifacts()` genau diese beiden zusaetzlich zwingend braucht — ohne sie wuerde eine Promotion den Lean-Loader leise brechen
- Promotion verlangt hart einen vorhandenen `aether_vault_commit` (`phase_v2.retraining.promotion.require_vault_commit`) — ohne erfolgreichen Aether-Vault-Commit gibt es keine Uebernahme
- Rollback verifiziert SHA-256-Hashes gegen `model_versions.artifact_hashes`, bevor irgendeine Datei aktiviert wird; bei fehlenden lokalen `ml/versions/<id>/`-Dateien faellt es auf einen `av checkout <commit>` zurueck, bevor der Wiederherstellungsversuch wiederholt wird
- Aether-Vault (`C:\Users\Blackhead\Desktop\aether-vault`, ein separates Schwesterprojekt) wird ausschliesslich als externer `av`-Subprocess aufgerufen — dessen Quellcode wird nirgends gelesen oder importiert; `run_av_command()` faengt ein fehlendes `av`-Binary/Timeout immer ab und markiert den `retraining_event` als `failed`, ohne die Pipeline abstuerzen zu lassen
- `RetrainingWorker` ist bewusst **kein** unbedingt automatisch-promotender Daemon: `phase_v2.retraining.worker.auto_promote` ist standardmaessig `false`, sodass der Worker nach einem erfolgreichen Vault-Commit anhaelt (`status=validated`) und die eigentliche Modell-Uebernahme eine manuelle `python -m retraining.orchestrator promote --version-id <id>` bleibt — "kein unkontrolliertes Live-Lernen" bleibt damit auch bei aktivem Worker gewahrt
- neuer Service `retraining-worker` in `docker-compose.yml`; im Unterschied zu `experience-worker`/`performance-trigger-worker`s Minimal-Images braucht dieser Worker den vollen Trainings-Stack (`torch`, `pandas`, `scikit-learn`, `joblib`), weil `orchestrator.py`s `train()`-Schritt `train.py` per Subprocess aufruft — `Dockerfile.retraining_worker` kopiert entsprechend zusaetzlich `experts/`, `regime/` und `train.py`
- ergaenzt `config.json phase_v2.retraining` (Cooldown, Mindestbeobachtungen, Tageslimit, Validation-/Backtest-Gate-Schwellenwerte, Vault-/Promotion-/Worker-Konfiguration)
- ergaenzt `monitoring/api_server.py` um `/api/grafana/retraining-status`; `/api/state` mergt `retraining_status.json` serverseitig dazu, weil `main.py` (anders als bei `performance_triggers`) keine In-Memory-Annaeherung liefern kann — es haelt nie eine eigene Postgres-Verbindung
- fuegt das Webui-Panel `RetrainingStatusPanel.tsx` hinzu (aktive/Kandidat-Version, Validierungsstatus, Vault-Commit-Kurzhash, letzter Trigger, Rollback-Verfuegbarkeit), platziert direkt unter `PerformanceTriggersPanel`
- fuegt 90 neue Tests hinzu (150 → 244 gesamt), je Quelldatei eine Testdatei nach bestehender Konvention

## Phase-V2-17.5-Ergebnis

Non-Deterministic Topology & Retrain-Trigger Upgrade macht jetzt zusaetzlich Folgendes:

- Sicherheitsregel zuerst: "nicht-deterministisch" heisst probabilistisches Scoring (Confidence/Uncertainty), nicht zufaellige Trades — jede Order durchlaeuft weiterhin unveraendert Risk Engine, Liquidity Engine, Order Gate, Observation Mode und die V2-17-Gates; `analyzer/market_analyzer.py` wird **nicht** angefasst und liest weiterhin nur `topology_risk`/`state` aus der deterministischen Schicht
- legt `topology/learned_topology.py` an: reines Python (kein numpy/sklearn zur Laufzeit, wie `market_topology.py`/`regime/`/`liquidity/`), `apply_learned_topology(...)` legt eine probabilistische Ueberlagerung auf die bestehende deterministische Topologie — nie ein Ersatz. Pro Knoten: `cluster_probs` (Softmax ueber Abstaende zu trainierten Prototypen), `topology_confidence`, `topology_uncertainty` (normalisierte Entropie), `stress_score` (Neuheits-Signal), `neighbor_shift_score` (Jaccard-Drift der gelernten Nachbarmenge), `topology_disagreement`, begrenzte x/y/z-Offsets (nie eine volle Ersatz-Einbettung) und `topology_source` (`deterministic`/`learned`/`hybrid`/`fallback`). Faellt bei fehlendem/unsicherem Modell pro Knoten (und im schlimmsten Fall komplett) auf die deterministische Position zurueck — nie ein Absturz
- neues Root-Skript `train_topology.py` (numpy/scikit-learn erlaubt, laeuft nie im Lean-Container): liest `experience_events` ueber das wiederverwendete `performance.postgres_triggers.fetch_recent_events()`, leitet ein `win`/`loss`/`neutral`-Ergebnis-Label pro Ticker aus `portfolio.last_realized_pnl` her (Open-Trade-Span rueckwirkend markiert), baut Feature-Vektoren und fittet `sklearn.cluster.KMeans`-Prototypen ueber z-skalierte Features. Schreibt `topology_model.json`/`topology_training_metrics.json`/`topology_feature_schema.json` ausschliesslich nach `ml/versions/<version_id>/`; bei zu wenig Trainingsdaten Exit-Code 0 (uebersprungen, kein Fehler)
- `retraining/orchestrator.py` bekommt `train_topology()`: ein zweiter, unabhaengig fehlschlagbarer Subprocess zwischen `train` und `validate` — ein Fehlschlag wird als Notiz auf `retraining_events` geloggt und lehnt den Kandidaten **nie** ab. `retraining/artifacts.py` bekommt `OPTIONAL_TOPOLOGY_FILES` (bewusst **nicht** in `REQUIRED_CANDIDATE_FILES`, damit `validate()` nie wegen fehlender Topologie-Artefakte ablehnt), aber in `ACTIVE_ARTIFACT_FILES`/`ALL_TRACKED_FILES` — der ganze `ml/versions/<id>/`-Ordner wird bereits per `av add` committet, Topologie-Artefakte werden also automatisch mitgenommen. `RetrainingWorker` ruft `train_topology()` an derselben Stelle auf; `auto_promote` bleibt standardmaessig `false`
- `performance/triggers.py` bekommt 5 neue Trigger: `topology_uncertainty_trigger`, `topology_regime_mismatch_trigger`, `cluster_drift_trigger`, `model_topology_disagreement_trigger` (alle mit Persistenz-Schutz: Fenster-Durchschnitt **und** Mindestanteil einzeln brechender Bars, damit ein einzelner Ausreisser nie feuert) sowie `trigger_frequency_spike` (Meta-Trigger ueber Trigger-*Zeilen*, nicht Events — Rate-Anstieg gegen eigene Baseline). `evaluate_all_triggers()` bekommt ein optionales `recent_triggers`-Argument, abwaertskompatibel
- behebt die V2-16-Einschraenkung: `performance/trigger_worker.py`s `run_once()` schiebt den Watermark weiterhin nur ueber den inkrementellen Batch vor (billige Leerlauf-Polls), wertet Trigger aber jetzt ueber ein echtes Rolling-Window aus `fetch_recent_events()` aus — die letzten `rolling_window_events` Beobachtungen, begrenzt auf `rolling_window_days` Tage oder seit dem letzten Retraining (`fetch_last_retraining_at()`), je nachdem was juenger ist
- `retraining/planning.py::select_candidate_trigger()` waehlt jetzt nach Prioritaets-Score statt nur nach Zeitstempel: Schweregrad + Trigger-Typ-Gewicht + Bonus wenn Regime-Shift und ein Topologie-Trigger gemeinsam auftreten (nur fuer diese Typen, nicht fuer unbeteiligte Kandidaten) + gedeckelter Wiederholungs-Bonus. Ein einzelnes schwaches Topologie-Event erreicht diese Auswahl gar nicht erst — das erledigen bereits die Persistenz-Schutzmechanismen in `performance/triggers.py`
- ergaenzt `config.json` um `phase_v2.topology_learning` (Modell-Schwellenwerte plus `training`-Unterblock), neue Schwellenwerte/Fenstergroessen in `phase_v2.performance_triggers`, `phase_v2.retraining.topology_training` sowie die drei neuen Dateinamen in `phase_v2.retraining.promotion.active_artifact_files`
- `main.py` laedt `ml/topology_model.json`/`ml/topology_feature_schema.json` optional (fehlende Datei ⇒ `None`, kein harter Fehler, wie bei den MoE-Experten-Exports) und ruft `apply_learned_topology()` nach dem bestehenden `build_market_topology()`-Aufruf auf; Liquiditaets-/Regime-Risk-Score-Inputs sind zwangslaeufig einen Bar verzoegert (dieselbe bestehende Einschraenkung wie bei `latest_regime_by_symbol`)
- Webui: `state.ts` bekommt die neuen Topologie-Felder, `TopologyScene3D.tsx` zeigt `topology_source`/`topology_confidence` im Tooltip und dimmt Fallback-Knoten leicht, neues Panel `TopologyLearningPanel.tsx` (Deterministic/Learned/Hybrid/Fallback-Badge, aggregierte Confidence-/Uncertainty-/Stress-/Mismatch-Statistik) auf der Topology-Seite
- `Dockerfile.retraining_worker` kopiert zusaetzlich `topology/` und `train_topology.py` — `requirements-retraining-worker.txt` hatte numpy/scikit-learn/psycopg bereits seit V2-17, keine neuen Abhaengigkeiten noetig
- fuegt 69 neue Tests hinzu (244 → 313 gesamt): `tests/test_learned_topology.py` (18), Erweiterungen von `tests/test_triggers.py`/`test_trigger_worker.py`/`test_postgres_triggers.py`, `tests/test_retraining_planning.py`, `tests/test_train_topology.py` (10, neu), `tests/test_retraining_artifacts.py`, `tests/test_retraining_orchestrator.py`, `tests/test_retraining_worker.py`
- Nebenbei: Docker-Host-Ports neu gemappt, damit ein lokaler Aether-Quant-Stack nie mit dem separaten Aether-Vault-Compose-Stack kollidiert (dieser bindet unabhaengig Host 8000/3000/5432/6379) — `aether-quant` 8000→8001, Redis 6379→6380, PostgreSQL 5432→5433, lokaler Vite-Dev-Server 3000→3002, Grafana bleibt bei 3001; lokaler, nicht containerisierter `uvicorn` zieht ebenfalls auf 8001 um

## Phase-V2-18-Ergebnis

Grafana entfernt, natives React-Tracing-Dashboard:

- Grafanas einzige Aufgabe war, die bereits als JSON/CSV ueber `monitoring/api_server.py`s `/api/grafana/*`-Routen servierten Exporte (`equity_curves.csv`, `asset_performance.csv`, `observation_equity_curve.csv`, `runtime_metrics_snapshot.json`) darzustellen — kein eigener Rechenpfad, also auch kein Backend-Change noetig, nur ein neuer Konsument
- `docker-compose.yml`: `grafana`-Service, `grafana-data`-Volume und `AETHER_GRAFANA_URL`-Env auf dem `lean`-Service entfernt; der Stack besteht jetzt aus Redis, PostgreSQL, `aether-quant` und den drei Workern
- neue Webui-Seite `TracingPage.tsx` unter `/tracing` (Nav-Eintrag in `AppShell.tsx`) mit vier Panels unter `src/components/tracing/`: `MetricsSnapshotPanel.tsx` (Stat-Tiles aus dem Runtime-Metrics-Snapshot), `AssetPerformancePanel.tsx` (divergierende Sharpe-Balken je Ticker, blau/rot nach Vorzeichen, plus Tabellen-Ansicht), `BacktestEquityPanel.tsx` (Ticker-Dropdown, Strategie- vs. Buy-and-Hold-Cumulative-Return-Linienchart) und `ObservationEquityPanel.tsx` (simulierte Equity/Cash-Linienchart plus Drawdown-Chart, client-seitig auf ~400 Punkte downgesampelt gegen die mehreren tausend Bars des Observation-Mode-Exports)
- zwei neue, abhaengigkeitsfreie SVG-Chart-Primitives statt einer Charting-Library: `LineChart.tsx` (Crosshair+Tooltip, Legende ab zwei Serien, dezente Gridlines, nie zwei Y-Achsen) und `DivergingBarChart.tsx`, beide von mehreren Panels wiederverwendet
- `src/api/client.ts`/`hooks.ts` bekommen `fetchMetricsSnapshot`/`fetchEquityCurves`/`fetchAssetPerformance`/`fetchObservationEquityCurve` und die passenden `useX()`-Hooks (15s Refresh, nur von der Tracing-Seite selbst aufgerufen, nicht global wie `useRuntimeState()`); neue Typen in `src/types/tracing.ts`
- bewusst NICHT umbenannt: der Ordner `visualization/grafana/`, `retraining/status_export.py`, `performance/postgres_triggers.py` und die `/api/grafana/*`-Routennamen — nur der Konsument hat gewechselt, ein Rename waere reines Umbenennungsrisiko ohne Nutzerwert gewesen
- Doku aktualisiert: `README.md`, `development/v2_architecture.md` (inkl. neuem Abschnitt "Remove Grafana, React Tracing Dashboard (V2-18)" und aktualisierter Port-Tabelle ohne Grafana-Zeile), `webui/README.md`

## Phase-V2-19-Ergebnis

Telegram Alerts macht jetzt zusaetzlich Folgendes:

- legt das neue, Lean-freie Paket `notifications/` an, in derselben pure/IO/Worker-Aufteilung wie `performance/` (V2-16) und `retraining/` (V2-17): `telegram_alerts.py` (rein — `should_alert_trigger()`, `format_trigger_alert()`, `format_session_summary_alert()`, rendert nur bereits berechnete Felder, berechnet nichts neu), `postgres_telegram.py` (eingebettetes DDL fuer `telegram_alert_watermark`, ein Row pro Kanal `"triggers"`/`"session_summary"`, plus `fetch_session_summaries_since()` als defensiver, nie werfender Read auf `experience_events`), `telegram_client.py` (injizierbarer Telegram-Bot-API-Wrapper, `send_message()` wirft nie, deferred `import requests`), `telegram_worker.py` (`TelegramWorker`, `python -m notifications.telegram_worker [--once]`)
- **Trigger-Kanal**: pollt die bereits durchgehend laufende `performance_triggers`-Tabelle (V2-16) direkt ueber `performance.postgres_triggers.fetch_triggers_since()` — keine eigene Trigger-Erkennung. Da jede Trigger-Art (nicht nur `drawdown_trigger`) ab `phase_v2.telegram.min_severity_for_trigger_alert` gemeldet wird, kommen Risk-Lock-Aktivierung, Regime-Shifts, Liquiditaets-Ablehnungen, Sharpe-/Win-Rate-/Confidence-Verschlechterung und alle fuenf Topologie-Trigger ohne zusaetzliche Instrumentierung mit
- **Session-Summary-Kanal**: `main.py` bekommt drei additive Aenderungen — `self._session_events: list[dict]` sammelt die Events der laufenden Session (parallel zu `self._observation_event_log`); in der bestehenden Session-Rollover-Verzweigung von `_refresh_risk_state()` (der Datums-Wechsel-Check, der bereits `session_start_equity` zuruecksetzt) wird jetzt **vor** dem Reset, und abgesichert gegen den allerersten Bar, ein neues `experience.redis_queue.build_session_summary_event()`-Event (`event_type="session_summary"`) ueber die bestehende `ExperienceQueue` gepusht — dieselbe Redis→`experience-worker`→Postgres-Pipeline wie jedes andere Event, kein neuer Transport noetig
- `build_session_summary_event()` (`experience/redis_queue.py`, exportiert aus `experience/__init__.py`) berechnet selbst nur `session_return`; alle uebrigen Statistiken kommen unveraendert aus dem bereits vorhandenen `experience.observation_metrics.compute_observation_summary()`
- **Notwendiger, nicht-additiver Fix**: `experience/postgres_worker.py::event_to_row()` indizierte bisher `event["ticker"]`/`["symbol"]`/`["signal"]`/`["action"]` direkt. Ein `session_summary`-Event hat keines dieser Felder (Portfolio-Ebene, nicht Asset-Ebene) — ohne den Fix waere `KeyError` geflogen, das Event still in den Dead-Letter-Stream geroutet worden, und `fetch_session_summaries_since()` haette fuer immer `[]` zurueckgegeben, ohne dass irgendwo ein Fehler sichtbar geworden waere. Fix: `.get(key, "")`-Defaults (rueckwaertskompatibel, da `experience_events`-Spalten `VARCHAR NOT NULL` ohne Unique-Constraint sind), `action` faellt auf `event_type` zurueck
- `Dockerfile.telegram_worker` kopiert `execution/`, `experience/`, `performance/`, `notifications/` — `execution/` ist noetig, weil das Importieren von `performance.postgres_triggers` `performance/__init__.py` → `.triggers` → `experience.observation_metrics` → (via `experience/__init__.py`) `.simulated_portfolio` → `execution.order_gate` transitiv initialisiert; dieselbe Lektion wie `development/Problems.md` #1/#2, hier proaktiv angewendet statt erst nach einem kaputten Build entdeckt. `requirements-telegram-worker.txt` enthaelt aus demselben Grund `numpy`
- neuer Service `telegram-worker` in `docker-compose.yml`, haengt nur von `postgres` ab (kein Redis — der Worker ruehrt den Experience-Stream nie an); neue `.env.compose.example` (die `.gitignore`-Ausnahme dafuer existierte bereits, die Datei selbst nicht) dokumentiert `AETHER_TELEGRAM_BOT_TOKEN`/`AETHER_TELEGRAM_CHAT_ID`
- ergaenzt `config.json phase_v2.telegram` (`enabled`, `min_severity_for_trigger_alert`, `session_summary_enabled`, `worker.{poll_interval_seconds,batch_size,backoff_max}`)
- fuegt 24 neue Tests hinzu (Telegram-Teil) plus 7 Erweiterungen bestehender Testdateien: `tests/test_telegram_alerts.py` (4), `tests/test_postgres_telegram.py` (7), `tests/test_telegram_client.py` (7), `tests/test_telegram_worker.py` (6), Erweiterung von `tests/test_experience_queue.py` (5, `build_session_summary_event`) und `tests/test_postgres_worker.py` (2, `event_to_row` mit `session_summary`-Events) — zusammen mit V2-19.5s 20 neuen Tests: 313 → 364 gesamt
- `tests/README.md`s Testzahl war bereits seit V2-17.5/V2-18 stale ("244 tests as of V2-17", tatsaechlich 313) — in diesem Zug korrigiert
- Stop: kein Retry/Backoff ueber das Noetigste hinaus fuer den eigentlichen Telegram-API-Call, kein Webui-Panel fuer Alert-Historie — beides bewusst nicht Teil von V2-19

## Phase-V2-19.5-Ergebnis

Yahoo Finance Historical Data Backfill (ergaenzende Anfrage neben V2-19, kein Punkt im urspruenglichen nummerierten Plan) macht jetzt Folgendes:

- legt `data_pipeline/yfinance_backfill.py` als **manuelles Offline-Skript** an — laeuft nie aus `train.py`/`main.py`/einem Docker-Worker heraus, keine Netzwerkzugriffe waehrend Training oder Backtest (gleicher Status wie `train_topology.py`: "laeuft nie im Lean-Container")
- fuellt Luecken in duennen lokalen Lean-Zips, allen voran `ETHUSD`/`LTCUSD` (nur wenige verstreute Tage echter Coinbase-Minutendaten, siehe `train.py::ensure_derived_crypto_daily_series()` und den Phase-9-Eintrag oben) — deshalb bisher `observation_only` nach `train.py::build_asset_quality()`s Zeilen-Schwellenwerten
- neuer, optionaler `"backfill"`-Unterblock pro Asset in `config.json phase1.universe.assets[]` (`source`, `symbol`, `backfill_from`, `backfill_to`) — bewusst ein neuer Schluessel statt Wiederverwendung von `aggregation: "daily_from_minute_trade"`, da dieser Wert bereits `train.py`s eigene Coinbase-Aggregation bei jedem Lauf ausloest und dieser Pfad manuell bleiben muss
- reine Funktionen (`yahoo_symbol_for`, `detect_gap`, `scale_for_lean`, `rows_to_lean_csv`, `write_lean_zip`) spiegeln `train.py::ensure_derived_crypto_daily_series()`s exaktes Lean-Zip-Schreibmuster (`ZipFile(pfad, "w")`, Member-Name `f"{ticker.lower()}.csv"`, Zeilenformat `f"{date:%Y%m%d} 00:00,{o},{h},{l},{c},{v}"`), mit einer Ergaenzung: `scale_for_lean()` wendet die x10000-Ganzzahl-Konvention fuer Aktien an (Yahoo liefert echte Dollar-Floats), Krypto bleibt unskaliert
- `fetch_yahoo_ohlcv()` ist die einzige Funktion, die `yfinance` importiert, deferred innerhalb der Funktion (spiegelt `experience/redis_queue.py`s deferred `import redis`) — `data_pipeline` zu importieren erfordert `yfinance` nie zwingend
- zwei unabhaengige Sicherheitsgrenzen, beide mit explizitem manuellem Schritt: (1) Schreiben/Mergen von Zip-Dateien nur mit `--apply` (Default: Dry Run, nur Report); (2) `config.json`s `available_from`/`available_to` werden **nie** automatisch geaendert, auch nicht mit `--apply` — `train.py::build_asset_quality()` zaehlt Zeilen nur innerhalb der konfigurierten Fenster, das Skript gibt nur die vorgeschlagenen neuen Werte auf der Konsole aus
- `write_lean_zip()`s Merge laesst bestehende echte Lean-Zeilen bei ueberlappenden Daten immer gewinnen; Yahoo-Daten fuellen nur echte Luecken
- `yfinance` ist eine reine Dev-Abhaengigkeit (`requirements/requirements-dev.txt`), nie in `requirements.txt`/`requirements-runtime.txt`
- fuegt `tests/test_yfinance_backfill.py` mit 20 Tests hinzu (alle mit injiziertem `fetch_fn`-Stub — `yfinance` wird in der gesamten Testdatei kein einziges Mal importiert)
- Stop: kein automatisches Nachziehen von `available_from`/`available_to`, kein Docker-Worker — bewusst ein manuelles Offline-Skript, gleicher Status wie `train_topology.py`

## Phase-V2-23.1-Ergebnis

Data-Driven Liquidity Threshold Calibration — geschlossen, aber anders als urspruenglich geplant:

- der urspruengliche Plan war, `spread_proxy` aus echten historischen Fill-/Slippage-Daten zu kalibrieren, sobald die Experience-Pipeline (V2-13/14) genug Historie angesammelt hat. Eine tiefere Pruefung in dieser Session zeigte: diese Grundannahme hatte keine Datenbasis — Lean-Backtests setzen nie ein `SlippageModel` (nur ein `InteractiveBrokersFeeModel`, das eine Transaktionsgebuehr, keine Preis-Impact-Slippage ist), und `experience/simulated_portfolio.py`s `enter_long()` ruft `execution.order_gate.simulate_fill(...)` immer mit dem Default `slippage_bps=0.0` auf — es wurde also noch nie irgendwo eine realisierte Spread-/Slippage-Beobachtung geloggt, aus der man haette kalibrieren koennen
- statt neue Fill-Telemetrie-Infrastruktur als Voraussetzung zu bauen, wurde stattdessen der **Corwin & Schultz (2012) High-Low-Spread-Schaetzer** implementiert: eine publizierte, geschlossene Formel, die den Bid-Ask-Spread allein aus aufeinanderfolgenden Tages-High/Low-Ranges schaetzt — Daten, die ohnehin jede Bar in `main.py::self.symbol_windows` gesammelt werden
- `liquidity/market_liquidity.py::estimate_high_low_spread(highs, lows)` (rein, kein I/O): berechnet pro aufeinanderfolgendem 2-Bar-Fenster einen Schaetzwert nach der Corwin-Schultz-Formel (`beta`, `gamma`, `alpha`, dann `spread = 2*(e^alpha-1)/(1+e^alpha)`), klippt negative Einzelfenster-Schaetzungen auf `0.0` (ein bekanntes, dokumentiertes Artefakt der Methode bei geringer Volatilitaet, kein Bug) und mittelt ueber alle Fenster; gibt `None` zurueck bei weniger als 2 gueltigen Bars
- `build_liquidity_decision(...)` bekommt einen neuen optionalen `dynamic_spread`-Parameter — ersetzt `TYPICAL_SPREAD_BY_TYPE.get(security_type, ...)` als primaeren Pfad; die statische Lookup-Tabelle bleibt nur als Fallback fuer die ersten Bars eines Laufs (`phase_v2.liquidity.spread_estimation.min_bars`, Default 2) oder wenn der Schaetzer keinen gueltigen Wert liefert
- `main.py` liest an der Liquiditaets-Aufrufstelle `highs`/`lows` aus `self.symbol_windows[symbol]` (bereits jede Bar befuellt, keine neue State-Verwaltung noetig) und uebergibt das Ergebnis als `dynamic_spread`
- ergaenzt `config.json phase_v2.liquidity.spread_estimation` (`enabled`, `min_bars`)
- fuegt 10 neue Tests zu `tests/test_market_liquidity.py` hinzu: eine unabhaengig nachgerechnete Referenz-Berechnung, Nullspread bei flachen Preisen, Monotonie (schmalerer Range -> kleinerer Spread), Mittelwertbildung ueber mehrere Fenster, `None` bei zu wenig/inkonsistenten Bars, Ueberspringen ungueltiger Fenster, sowie `dynamic_spread`-Override/Fallback-Verhalten in `build_liquidity_decision`
- Stop: kein Ruecklauf auf echte Fill-Daten-Kalibrierung — dafuer muesste zuerst ein `SlippageModel`/echte Fill-Telemetrie eingefuehrt werden, was bewusst nicht Teil dieser Phase ist

## Phase-V2-23.2-Ergebnis

Static-Config-Wiring + totes `average_correlation`-Feature (ergaenzend, gefunden bei einem Static-vs-Dynamic-Architektur-Audit dieser Session):

- `config.json` bekommt drei zuvor fehlende `phase_v2`-Bloecke (`dynamic_risk`, `regime_detection`, `gating_network`), die `main.py` bereits seit V2-3/V2-6/V2-9 liest (`self.phase_v2.get("dynamic_risk", {})` etc.) — ohne diese Bloecke fiel jeder einzelne Wert (Ziel-Volatilitaet, Regime-Schwellenwerte, Gating-Baseline-Gewicht) still und für immer auf den Python-Hardcoded-Default zurueck, ohne dass es je konfigurierbar war. Rein additiv: die neuen Werte entsprechen exakt den bisherigen Defaults, keine Verhaltensaenderung
- `regime/market_regime.py::build_market_regime_vector()`s `average_correlation`-Parameter existierte bereits seit V2-6, wurde aber nie mit einem echten Wert gefuettert — `main.py` rief `_build_regime_payload()` immer ohne diesen Parameter auf, sodass der korrelationsgesteuerte risk_off-Zweig in `classify_risk_regime()` in der Praxis unerreichbar war. Fix: `main.py::_build_regime_payload()` bekommt einen neuen `average_correlation`-Parameter, der an der Aufrufstelle mit `topology_payload["correlation_strength"]` befuellt wird — dem bereits von `topology/market_topology.py` pro Asset berechneten mittleren Peer-Korrelationswert innerhalb des eigenen Clusters, verfuegbar, weil `_build_topology_payload()` bereits einmal pro Bar vor der Pro-Asset-Schleife laeuft. Keine Aenderung in `regime/market_regime.py` oder `topology/market_topology.py` selbst noetig — reine `main.py`-Verdrahtung eines bereits echten Wertes in einen bereits echten Parameter
- fuegt 1 neuen Test zu `tests/test_market_regime.py` hinzu: bestaetigt, dass `average_correlation` durchgereicht wird und `risk_score`/`reasons` tatsaechlich beeinflusst
- Stop: `main.py` bleibt bewusst ohne eigene Unit-Tests (Import erfordert `AlgorithmImports`/Lean) — die Verdrahtung ist bis zur main.py-Grenze getestet, nicht end-to-end in Lean

## Phase-V2-23.3-Ergebnis

Echtes Topology-Embedding (ergaenzend, gleicher Audit):

- `topology/market_topology.py`s bisherige 3D-Koordinaten-Platzierung war rein kosmetisch: Cluster-Zentroiden wurden per `index -> angle` auf einer festen Ellipse platziert, Mitglieder innerhalb eines Clusters ebenfalls per `member_index -> angle` — nur der Radius war datengetrieben (Marktdistanz), die Richtung nie. Zwei stark korrelierte Cluster konnten so auf gegenueberliegenden Seiten der Szene landen
- ersetzt durch `_stress_majorize_2d(...)`: SMACOF (Scaling by MAjorizing a COmplicated Function), ein iterativer Stress-Majorisierungs-Algorithmus (klassischer Guttman-Transform), der ueber die vollstaendige paarweise Korrelations-Distanz-Matrix aller berechtigten Symbole laeuft (nicht nur innerhalb eines Clusters) — Position im Raum spiegelt jetzt tatsaechlich Korrelationsdistanz wider, nicht nur Cluster-Zugehoerigkeit
- bewusst SMACOF statt klassischem MDS gewaehlt: keine Eigenwertzerlegung noetig (nur gewichtete Positions-Mittelwertbildung pro Iteration), bleibt dadurch reines Python ohne numpy/scipy — dieselbe Begruendung, aus der `topology/learned_topology.py` schon numpy-frei bleibt
- deterministisch geseedet aus dem bisherigen kosmetischen Layout (nicht zufaellig) — `test_stable_coordinates_are_deterministic` besteht unveraendert weiter
- `_rescale_positions_to_bounds(...)` skaliert das Ergebnis isometrisch (ein einzelner Skalierungsfaktor, kein unabhaengiges Achsen-Stretching, das die zu erhaltenden Distanzen verzerren wuerde) zurueck in die bestehenden `NEUTRAL_DIMENSIONS` `[0,100]x[0,100]`-Grenzen — `webui/src/components/topology/TopologyScene3D.tsx` brauchte keine Aenderung, da es bereits ueber `topology.dimensions` normalisiert
- die z-Achse (Volatilitaets-Encoding) bleibt unveraendert — bewusst eine separate, bedeutungsvolle Kodierung, kein Teil des raeumlichen Embeddings
- `build_market_topology(...)` bekommt einen neuen `embedding_iterations`-Parameter (Default 100), `config.json phase_v2.topology.embedding_iterations` ergaenzt, `main.py` reicht ihn durch
- fuegt 3 neue Tests zu `tests/test_market_topology.py` hinzu: korrelierte Assets sind jetzt raeumlich naeher beieinander als unkorrelierte (staerkere Aussage als der bisherige reine Cluster-ID-Vergleich), Koordinaten bleiben innerhalb der Grenzen, `embedding_iterations` beeinflusst das Layout tatsaechlich (kein ignorierter Config-Wert)
- Stop: kein 3D-Embedding (z bleibt Volatilitaets-Encoding, nicht Teil der Distanzerhaltung) — bewusst, da z bereits eine etablierte, separate Bedeutung traegt

## Test Suite

313 → 378 Tests gesamt nach diesem Audit-getriebenen Durchlauf (14 neu: 10 Liquidity, 1 Regime, 3 Topology). `tests/README.md` aktualisiert.

## Phase-V2-20-Ergebnis

Lean Backtesting Integration macht jetzt zusaetzlich Folgendes:

- beantwortet die offene Frage, ob ein normaler `lean backtest .`-Lauf bereits
  das gesamte ML-System durchlaeuft (Basismodell, alle 4 Experten, MoE-Gating,
  Regime, Topologie), mit **Ja** — durch Nachverfolgung von `main.py::on_data`:
  `_run_model` (Basismodell), `_run_expert_models` (alle 4 Experten ueber
  denselben `_run_exported_model`-Interpreter), `build_gating_decision`
  (MoE-Gating), `_build_topology_payload` (deterministische + gelernte
  Topologie, einmal pro Bar vor der Symbol-Schleife) und
  `build_market_regime_vector` (Regime) laufen alle unveraendert seit
  V2-9/V2-11/V2-12 pro Bar und pro Symbol — V2-20 hat daher keine
  Laufzeit-Logik umgebaut, sondern die bestehende Abdeckung nachgewiesen
- fuegt `tests/test_lean_backtest_ml_coverage.py` hinzu: ein echter
  Integrationstest, der `lean backtest .` per Subprocess ausfuehrt und danach
  `visualization/state.json` darauf prueft, dass mindestens ein voll
  ausgewertetes Signal alle 4 Expertennamen in `expert_probabilities`, 4
  gewichtete Eintraege in `moe_gating.weights`, ein gesetztes
  `regime.trend_regime` und ein gesetztes `liquidity.liquidity_risk` zeigt,
  sowie dass `state["topology"]["nodes"]` nicht leer ist — schliesst damit die
  in `development/Problems.md` #8 dokumentierte Luecke, dass `main.py` bisher
  keine eigenen Tests hatte
- der neue Test uebernimmt `retraining/lean_backtest.py`s Konvention
  (optionale Abhaengigkeit, Skip statt Fail, wenn Lean-CLI fehlt), ergaenzt
  aber eine Absicherung: auf Maschinen mit installiertem `elan` (Lean 4, der
  Theorembeweiser) zeigt ein blosses `lean` auf `PATH` auf das **falsche**
  Programm (Namenskollision); `_find_quantconnect_lean_binary()` prueft die
  `--version`-Ausgabe und bevorzugt das Projekt-eigene `.venv/Scripts/lean.exe`,
  damit der Test sauber uebersprungen statt mit einer verwirrenden Fehlermeldung
  abgebrochen wird
- fuegt die neue Webui-Seite `/neural-network` hinzu (Nav-Eintrag zwischen
  Topology und Tracing): eine interaktive 3D-Ansicht aller 5 real trainierten
  neuronalen Netze (Basismodell + 4 Experten) nebeneinander in einer
  gemeinsamen Kamera/Orbit-Szene, plus eine live aktualisierte Statistik-Box
  (Layer/Node/Edge-Anzahl je Netz, Quality-Status, letzte Aenderung) — siehe
  Neural Network Visualization Contract (V2-20) in `v2_architecture.md` fuer
  das vollstaendige Datenschema und die bewusst ausgeschlossenen Nicht-Netze
  (MoE-Gating, gelernte Topologie-Prototypen)
- neues Backend-Modul `monitoring/neural_network_state.py`
  (`build_neural_network_state()`, reine Funktion) und neue Route
  `GET /api/neural-network`, beide nach demselben Read-only-Reshape-Muster
  wie `/api/topology`

## Phase-V2-21-Ergebnis

Paper Trading Vorbereitung — schliesst die Luecke, dass `broker_config_present`
bisher ein No-op war (`bool(self.paper_brokerage)`, ein String, der per
Default nie leer ist), ohne echtes IBKR-Paper-Konto anzulegen:

- neues, reines Modul `execution/paper_readiness.py`: `evaluate_paper_broker_config()`
  verlangt drei Bestaetigungen (`brokerage` gesetzt, `live_data_provider_configured`,
  `manual_review_confirmed` — letzteres ersetzt den alten toten
  `phase6.paper_trading.ready_for_live_paper`-Stub) und
  `evaluate_observation_readiness()` uebersetzt 4 der 5 Punkte aus
  `development/infrastructure.md`s "Bereit fuer Paper Trading?"-Checkliste in
  Code (Mindest-Beobachtungszahl, `simulated_sharpe`-Untergrenze,
  `simulated_max_drawdown`-Untergrenze, kein dominanter `rejected_by_reason`)
  — der 5. Punkt (manuelle Durchsicht der Trade-Historie) bleibt bewusst eine
  menschliche Entscheidung
- Zielarchitektur ist Lean's eingebaute `PaperBrokerage` (`lean.json`s bereits
  vorhandenes `live-paper`-Environment, keine echten Broker-Credentials
  noetig) statt eines echten IBKR-Paper-Kontos — Nutzerentscheidung fuer diese
  Phase
- `execution/paper_readiness_io.py` (IO): `read_paper_trading_config()` liest
  `phase_v2.paper_trading` frisch von der Platte (gleiches Muster wie
  `risk/manual_override.py`); `fetch_observation_mode_events()` ist die erste
  `mode='observation'`-gefilterte Experience-Events-Query (die bestehenden
  `fetch_recent_events()`/`fetch_events_since()` filtern nicht nach `mode`)
- neues Offline-Report-Modul `execution/paper_readiness_report.py`
  (`build_paper_readiness_view()`, Muster identisch zu
  `retraining/status_export.py`): schreibt
  `visualization/grafana/paper_readiness_report.json`; neuer CLI-Befehl
  `aq paper-readiness` (`aq_cli.py`) als menschlich ausgeloestes Gate vor dem
  Umschalten von `phase_v2.runtime.mode` auf `"paper"`
- `main.py`: `phase6.paper_trading` komplett entfernt (`self.paper_brokerage`/
  `self.ready_for_live_paper` waren nur ein No-op); neue
  `self.phase_v2_paper_trading`, neue `_recompute_broker_config()`-Methode
  (aufgerufen einmal in `initialize()` und einmal pro Session-Rollover in
  `_refresh_risk_state()`, gleiches "frisch von der Platte, kein Neustart
  noetig"-Prinzip wie beim Manual-Trade-Lock-Override), `_order_permission()`
  liest jetzt `self._broker_config_present` statt des alten No-op-Checks
- `monitoring/api_server.py`: `paper_readiness_report.json` wird sowohl in
  `/api/state` (unter `state["paper_readiness"]`, gleiches Muster wie
  `retraining_status`) als auch als eigene Route
  `GET /api/grafana/paper-readiness` bereitgestellt
- neues Webui-Panel `PaperReadinessPanel.tsx` (gleiche Struktur wie
  `RetrainingStatusPanel.tsx`), in `Overview.tsx` neben dem Retraining-Status-
  Panel platziert; neuer `PaperReadiness`-Typ in `types/state.ts`
- neuer Docker-Compose-Service `lean-live` (Profil `lean-live`, nie Teil von
  `--all`/`--lean`): laesst `lean live deploy . --environment
  ${LEAN_LIVE_ENVIRONMENT:-live-paper}` dauerhaft laufen (`restart:
  unless-stopped`), im Unterschied zum bestehenden `lean`-Service, der nur
  `sleep infinity` fuer Ad-hoc-`lean backtest .`-Laeufe bereitstellt
- `config.json` bekommt `phase_v2.paper_trading` (Default: alles blockierend,
  `live_data_provider_configured`/`manual_review_confirmed` beide `false`)
- neue Tests: `tests/test_paper_readiness.py`, `tests/test_paper_readiness_io.py`,
  `tests/test_paper_readiness_report.py`, plus `test_paper_readiness_wraps_the_report_module`
  in `tests/test_aq_cli.py`
- Stop: kein echter Broker/keine echten Live-Marktdaten in dieser Session
  konfiguriert oder getestet — `lean live deploy`s genaue CLI-Flags sind nicht
  gegen eine installierte Lean-CLI verifiziert, das Runbook in
  `development/infrastructure.md` weist explizit darauf hin, vor dem
  produktiven Einsatz `lean live deploy --help` zu pruefen

## Phase-V2-22-Ergebnis

Live Deployment Struktur — rein strukturell: macht den spaeteren Wechsel von
Paper zu echtem Live-Trading zu einer Config-/Credential-Aenderung, kein
Code-Umbau. Keine echten Broker-Credentials oder Live-Trades in dieser Phase
konfiguriert oder getestet.

- neues Credential-Handling: `.env.live.example` (neue `.gitignore`-Ausnahme
  `!.env.live.example`, analog zu `.env.compose.example`), reines
  `execution/live_credentials.py` (`credentials_present()`,
  `describe_missing_fields()`) und IO-Modul
  `execution/live_credentials_io.py::load_live_credentials()` — versucht
  zuerst `ib_config.py` (Repo-Root, gitignored, bisher nur geplant), faellt
  sonst auf `AETHER_IB_*`-Umgebungsvariablen zurueck. Reine Preflight-
  Validierung — verdrahtet Lean selbst nicht; Lean liest `ib-account`/
  `ib-user-name`/`ib-password` weiterhin direkt aus `lean.json`, das bleibt
  ein manueller Schritt (siehe neues Runbook unten)
- `execution/paper_readiness.py` bekommt `evaluate_live_broker_config()`
  (verlangt zusaetzlich zum bestandenen Paper-Check echte Credentials) und
  `evaluate_live_risk_posture()` (Sicherheits-Deckel: `max_daily_drawdown_pct`/
  `max_total_drawdown_pct` duerfen `phase_v2.live.max_allowed_*_drawdown_pct`
  nicht ueberschreiten, `liquidate_on_risk_breach` muss `true` sein) — dieselbe
  Entscheidungstabelle wie fuer `paper`, nur mit zusaetzlichen Bedingungen,
  daher ein Beleg dafuer, dass der Wechsel paper->live tatsaechlich nur eine
  Konfigurationsfrage ist
- `main.py`: `self._live_credentials` wird einmal in `initialize()` geladen
  (Umgebungsvariablen/`ib_config.py` aendern sich nicht waehrend eines Laufs,
  anders als `config.json`); `_recompute_broker_config()` reicht
  `credentials_present(...)` sowie den aktuellen Risk-/Live-Config-Zustand an
  `evaluate_broker_config()` durch
- `config.json` bekommt `phase_v2.live` (`max_allowed_daily_drawdown_pct: 0.05`,
  `max_allowed_total_drawdown_pct: 0.15`)
- Auto-Promote-Sicherheitsnetz: neues, winziges IO-Modul
  `execution/runtime_config_io.py::read_runtime_mode()` (gleiches Muster wie
  `risk/manual_override.py`); `retraining/worker.py::run_once()` erzwingt
  manuelle Promotion (`auto_promote` wird fuer diesen Zyklus auf `False`
  gesetzt, mit Warn-Log), sobald `phase_v2.runtime.mode == "live"` UND
  `phase_v2.retraining.worker.auto_promote_blocked_in_live_mode` (Default
  `true`) — volle Autonomie ist unproblematisch, solange noch kein echtes
  Live-Trading existiert, aber ein Modellwechsel soll nie unbeaufsichtigt live
  gehen, sobald echte Orders moeglich sind
- neuer Trigger `live_order_permission_blocked_trigger` in
  `performance/triggers.py`: feuert `critical`, wenn `mode == "live"`, aber
  juengste `execution_note`s weiterhin `simulated_*` sind (Order-Gate
  blockiert stillschweigend, was eine echte Order sein sollte — Hinweis auf
  falsch konfigurierte Credentials/Flag/Risk-Lock). Bewusst **nicht**
  retrain-faehig (`_NON_RETRAIN_TRIGGERS`) — ein neues Modell behebt keine
  Broker-Fehlkonfiguration; `notifications/telegram_alerts.py` brauchte keine
  Aenderung, da es Trigger bereits generisch formatiert
- neue Tests: `tests/test_live_credentials.py`, `tests/test_live_credentials_io.py`,
  `tests/test_runtime_config_io.py`, plus Erweiterungen in
  `tests/test_retraining_worker.py` und `tests/test_triggers.py`
- Stop: kein neues generisches "Watch-a-directory-and-auto-commit"-Feature
  gebaut — der bestehende `retraining/worker.py`-Loop plus Aether-Vault-
  Commit (`retraining/vault_client.py`) erfuellt das bereits; hier wurde nur
  `phase_v2.retraining.worker.auto_promote` auf `true` gestellt (siehe
  separater Abschnitt in `development/v2_architecture.md`s Controlled
  Retraining Contract)

