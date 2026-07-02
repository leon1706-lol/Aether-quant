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
