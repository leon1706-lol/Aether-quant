# infrastructure

Docker Compose verbindet die lokalen V2-Bausteine:

- `lean`: Lean Runtime / Backtest-Umgebung
- `redis`: schneller temporaerer In-Memory-Puffer fuer Signale, Trades und Rohmetriken
- `postgres`: permanente Experience Database und spaetere Single Source of Truth fuer Retraining

Grafana war frueher Teil dieses Stacks, wurde in V2-18 aber entfernt — die Webui-Tracing-Seite (`/tracing`) zeigt dieselben Feeds jetzt nativ an, siehe `development/v2_architecture.md`.

## Datenfluss

1. Live- oder Observation-Schleife erzeugt ein Signal und schreibt rohe Metriken sofort nach Redis.
2. Redis speichert die Events temporaer als Stream oder Queue, zum Beispiel per `XADD` oder `LPUSH`.
3. Ein Worker liest entkoppelt aus Redis, zum Beispiel per `XREAD` oder `BLPOP`.
4. Der Worker schreibt Events gebuendelt nach PostgreSQL.
5. Controlled Retraining nutzt PostgreSQL als stabile Datenquelle.

## Start

```powershell
docker compose up -d redis postgres
```

Lean wird bewusst ueber ein Compose-Profil gestartet, damit der Container nicht automatisch dauerhaft laeuft:

```powershell
docker compose --profile lean up -d
```

## Experience Worker starten

Worker mit Redis und PostgreSQL starten:

```powershell
docker compose up -d redis postgres experience-worker
docker compose logs -f experience-worker
```

Einmaligen Batch verarbeiten (nuetzlich nach einem Backtest):

```powershell
docker compose run --rm experience-worker python -m experience.postgres_worker --once
```

## PostgreSQL — Experience Events pruefen

```powershell
docker exec -it aether-postgres psql -U aether -d aether_quant
```

```sql
-- Zeilenzahl
SELECT COUNT(*) FROM experience_events;

-- Letzte 10 Events
SELECT event_id, created_at, ticker, signal, action, confidence
FROM experience_events
ORDER BY created_at DESC LIMIT 10;

-- JSONB-Abfrage: portfolio_value
SELECT event_id, payload -> 'portfolio' ->> 'total_value' AS portfolio_value
FROM experience_events ORDER BY created_at DESC LIMIT 5;
```

Dead-Letter-Stream in Redis:

```powershell
docker exec -it aether-redis redis-cli XLEN aether:experience:deadletter
docker exec -it aether-redis redis-cli XRANGE aether:experience:deadletter - + COUNT 5
```

## Eigene Images Verwenden

Wenn du eigene Redis-, PostgreSQL- oder Lean-Images hast, setzt du vor dem Start die Image-Namen:

```powershell
$env:REDIS_IMAGE="dein-redis-image:tag"
$env:POSTGRES_IMAGE="dein-postgres-image:tag"
$env:LEAN_IMAGE="dein-lean-image:tag"
docker compose --profile lean up -d
```

## Observation Mode Betreiben (V2-15)

Observation Mode laesst den Algorithmus wie live laufen (Signale, Risiko,
Regime, Topologie, Liquiditaet, MoE bleiben aktiv), platziert aber niemals
eine echte Order — jede Entscheidung wird stattdessen in einem simulierten
Portfolio (`experience/simulated_portfolio.py`) nachgebildet und wie gewohnt
nach Redis/PostgreSQL geloggt.

**1. Modus einschalten** — in `config.json`:

```json
"phase_v2": {
  "runtime": {
    "mode": "observation",
    "allow_live_orders": false
  }
}
```

`allow_live_orders` bleibt `false` — Observation Mode ignoriert dieses Flag
ohnehin und blockiert echte Orders immer, aber es sollte fuer diesen Modus
nie versehentlich auf `true` stehen. Committed Default ist `"backtest"`
(unveraendertes Verhalten von `lean backtest .`); fuer Observation Mode
explizit auf `"observation"` umstellen und danach wieder zurueckstellen,
wenn ein normaler Backtest gefahren werden soll.

**2. Start-Reihenfolge:**

```powershell
docker compose up -d redis postgres experience-worker
lean backtest .
```

Hinweis: Ein einzelner `lean backtest .`-Lauf (LEAN CLI, kein
Compose-Service) startet einen eigenen Docker-Container ohne Zugriff auf
`localhost:6380` des Hosts. Fuer eine echte Redis-Verbindung waehrend des
Laufs entweder `docker compose --profile lean up -d` verwenden (Container
im selben Compose-Netzwerk, `AETHER_REDIS_URL=redis://redis:6379/0`) oder
akzeptieren, dass `ExperienceQueue` bei nicht erreichbarem Redis nur eine
Warnung loggt und den Push ueberspringt — das Trading/die Simulation selbst
wird dadurch nie blockiert, es fehlen nur die Redis/Postgres-Events fuer
diesen Lauf.

**3. PostgreSQL — Observation-Events pruefen:**

```sql
SELECT COUNT(*) FROM experience_events WHERE mode = 'observation';

SELECT event_id, created_at, ticker, signal, action,
       payload -> 'portfolio' ->> 'total_value' AS simulated_equity
FROM experience_events
WHERE mode = 'observation'
ORDER BY created_at DESC LIMIT 10;
```

**4. Dashboard oeffnen:**

```powershell
python -m uvicorn monitoring.api_server:app --port 8001 --reload
cd webui && npm run dev
```

Im Webui (`http://localhost:3002`) zeigt das neue "Observation Mode" Panel
(`webui/src/components/monitoring/ObservationPanel.tsx`) das gelbe
"SIMULATED - NOT REAL TRADES"-Banner, simulierte Equity/Exposure/Drawdown/
Turnover, Sharpe, Signal-Verteilung und "Rejected By Reason". Dieselben
Daten liegen als Datei unter `visualization/grafana/observation_summary.json`
und `visualization/grafana/observation_equity_curve.csv`, bzw. per API unter
`/api/grafana/observation-summary` und `/api/grafana/observation-equity-curve`.

**5. Bereit fuer Paper Trading?** Seit V2-21 automatisiert statt einer rein
manuellen Checkliste — siehe "Paper Trading Betreiben (V2-21)" unten fuer den
vollstaendigen Ablauf. Kurzfassung: `aq paper-readiness` wertet 4 der
folgenden 5 Punkte automatisch aus (`execution/paper_readiness.py::evaluate_observation_readiness()`);
nur der letzte bleibt bewusst eine manuelle Entscheidung:

- Ausreichend Beobachtungsvolumen (`count_observations` >= `phase_v2.paper_trading.readiness_thresholds.min_observations`).
- `simulated_max_drawdown` nicht schlechter als `max_simulated_drawdown_floor`.
- `rejected_by_reason` zeigt keine dominante Ablehnungsursache ueber
  `max_single_rejection_reason_share` (z. B. staendig
  `liquidity_blocked_insufficient_volume_simulate_instead` fuer Kernassets).
- `simulated_sharpe` liegt ueber `min_simulated_sharpe`.
- **Bleibt manuell:** Durchsicht der Trade-Historie
  (`SimulatedPortfolioState.trade_log` bzw. die Experience Events) auf
  plausible Entry-/Exit-Preise — bestaetigt ueber
  `phase_v2.paper_trading.manual_review_confirmed`.

## Performance Triggers Pruefen (V2-16)

Der Trigger-Worker beobachtet `experience_events` (nicht nur den aktuellen
Lauf) und schreibt erkannte Warnungen/Retrain-Kandidaten dauerhaft in die
eigene Tabelle `performance_triggers`. Phase 16 retrained nichts selbst —
`retrain_candidate` ist nur ein Flag fuer Phase 17.

**1. Worker starten** — braucht nur PostgreSQL, kein Redis (der Worker liest
`experience_events`, schreibt aber nie in den Redis-Stream):

```powershell
docker compose up -d redis postgres performance-trigger-worker
docker compose logs -f performance-trigger-worker
```

**2. Einmaligen Batch verarbeiten** (nuetzlich nach einem Backtest):

```powershell
docker compose run --rm performance-trigger-worker python -m performance.trigger_worker --once
```

**3. PostgreSQL — Trigger pruefen:**

```sql
SELECT COUNT(*) FROM performance_triggers;

SELECT trigger_type, severity, scope, message, retrain_candidate, created_at
FROM performance_triggers ORDER BY created_at DESC LIMIT 10;

-- Nur Retrain-Kandidaten
SELECT * FROM performance_triggers WHERE retrain_candidate = true ORDER BY created_at DESC;
```

**4. Dashboard:** gleicher `uvicorn`/`npm run dev`-Start wie bei Observation
Mode. Das neue "Performance Triggers"-Panel
(`webui/src/components/monitoring/PerformanceTriggersPanel.tsx`) steht ganz
oben in der rechten Spalte — Retrain-Kandidat-Banner, Schweregrad-Verteilung,
letzter Trigger und Trigger-Typ-Aufschluesselung. Dieselben Daten (nur der
aktuelle, in-memory Lauf — nicht die dauerhafte Tabelle) liegen als Datei
unter `visualization/grafana/performance_triggers.json` bzw. per API unter
`/api/grafana/performance-triggers`.

## Controlled Retraining Betreiben (V2-17)

`retraining/` liest `retrain_candidate = true`-Zeilen aus der dauerhaften
`performance_triggers`-Tabelle, trainiert bei Bedarf ein Kandidatenmodell
isoliert unter `ml/versions/<version_id>/`, validiert/backtestet es gegen
das aktive Modell, committet es nach Aether-Vault und uebernimmt es erst
danach (oder rollt zurueck). Seit V2-22 promotet der Worker standardmaessig
**automatisch** — `phase_v2.retraining.worker.auto_promote` ist `true` —
solange `phase_v2.runtime.mode` nicht `"live"` ist: sobald Live-Trading
aktiv ist, erzwingt `phase_v2.retraining.worker.auto_promote_blocked_in_live_mode`
(Default `true`) trotzdem eine manuelle Promotion (siehe Live Deployment
Contract in `v2_architecture.md`). Manuelle Promotion bleibt jederzeit ueber
`python -m retraining.orchestrator promote --version-id <uuid>` moeglich.

**1. Worker starten** (braucht nur PostgreSQL, kein Redis — anders als
`experience-worker`/`performance-trigger-worker` braucht das Image aber den
vollen Trainings-Stack, da `train()` `train.py --candidate` per Subprocess
aufruft):

```powershell
docker compose up -d postgres retraining-worker
docker compose logs -f retraining-worker
```

**2. Einmaligen Zyklus verarbeiten** (nuetzlich nach einem Backtest oder zum
manuellen Testen):

```powershell
docker compose run --rm retraining-worker python -m retraining.worker --once
```

**3. Einzelne Stufen manuell/gestaffelt ausfuehren** — unabhaengig davon, ob
der Worker laeuft (`retraining_id`/`version_id` aus dem vorherigen Schritt
uebernehmen):

```powershell
python -m retraining.orchestrator plan
python -m retraining.orchestrator train --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator validate --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator backtest --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator commit --retraining-id <id> --version-id <uuid>
python -m retraining.orchestrator promote --version-id <uuid>
python -m retraining.orchestrator rollback --to-version-id <uuid>
python -m retraining.orchestrator status
```

**4. Retraining komplett abschalten** (ohne den Container anzufassen) — in
`config.json`:

```json
"phase_v2": {
  "retraining": {
    "enabled": false
  }
}
```

**5. PostgreSQL — Modellversionen und Retraining-Events pruefen:**

```sql
SELECT model_version_id, status, aether_vault_commit, created_at FROM model_versions ORDER BY created_at DESC;

SELECT retraining_id, status, reason, candidate_version_id, created_at FROM retraining_events ORDER BY created_at DESC LIMIT 10;
```

**6. Dashboard:** gleicher `uvicorn`/`npm run dev`-Start wie bei Observation
Mode. Das neue "Retraining Status"-Panel
(`webui/src/components/monitoring/RetrainingStatusPanel.tsx`) steht direkt
unter dem Performance-Triggers-Panel — aktive/Kandidat-Version,
Validierungsstatus, Vault-Commit-Kurzhash, letzter Trigger und
Rollback-Verfuegbarkeit. Anders als bei `performance_triggers` gibt es hier
keine In-Memory-Naeherung aus `main.py` (das haelt nie eine eigene
Postgres-Verbindung) — `visualization/grafana/retraining_status.json` ist
die einzige Quelle, geschrieben von `retraining/status_export.py` und per
`/api/grafana/retraining-status` bzw. serverseitig in `/api/state`
gemergt.

## Telegram Alerts Betreiben (V2-19)

`notifications/telegram_worker.py` sendet Telegram-Nachrichten fuer zwei
Kanaele: jede `performance_triggers`-Zeile ab
`phase_v2.telegram.min_severity_for_trigger_alert` (nicht nur Drawdown —
Risk-Lock, Regime-Shift, Liquiditaet, Sharpe/Win-Rate/Confidence,
Topologie-Trigger kommen automatisch mit), sowie ein Session-Summary pro
Handelstag (`event_type="session_summary"` in `experience_events`, von
`main.py` beim Session-Rollover gepusht).

**1. Bot-Token/Chat-ID setzen** — `.env` (siehe `.env.compose.example`):

```
AETHER_TELEGRAM_BOT_TOKEN=<dein-bot-token>
AETHER_TELEGRAM_CHAT_ID=<deine-chat-id>
```

Ohne diese beiden Werte laeuft der Worker als sicheres No-Op weiter (jede
`send_message()` gibt `False` zurueck, loggt eine WARNING, blockiert
nichts).

**2. Worker starten** (braucht nur PostgreSQL, kein Redis):

```powershell
docker compose up -d postgres telegram-worker
docker compose logs -f telegram-worker
```

**3. Einmaligen Batch verarbeiten:**

```powershell
docker compose run --rm telegram-worker python -m notifications.telegram_worker --once
```

**4. PostgreSQL — Watermarks pruefen:**

```sql
SELECT * FROM telegram_alert_watermark;
```

**5. Alerts komplett abschalten** (ohne den Container anzufassen) — in
`config.json`:

```json
"phase_v2": {
  "telegram": {
    "enabled": false
  }
}
```

## Yahoo Finance Backfill Ausfuehren (V2-19.5)

`data_pipeline/yfinance_backfill.py` ist ein manuelles Offline-Skript —
kein Docker-Service, laeuft nie automatisch. `yfinance` muss lokal
installiert sein (`pip install -r requirements/requirements-dev.txt`).

```powershell
# Dry Run — schreibt nichts, zeigt nur den Plan
python -m data_pipeline.yfinance_backfill --tickers ETHUSD LTCUSD

# Tatsaechlich schreiben
python -m data_pipeline.yfinance_backfill --tickers ETHUSD LTCUSD --apply
```

`config.json`s `available_from`/`available_to` werden dabei **nie**
automatisch geaendert — das Skript gibt am Ende nur die vorgeschlagenen
neuen Werte aus; diese muessen von Hand eingetragen werden, damit
`train.py::build_asset_quality()` die zusaetzliche Historie ueberhaupt
mitzaehlt.

## Paper Trading Betreiben (V2-21)

Zielarchitektur ist Lean's eingebaute `PaperBrokerage` (`lean.json`s
`live-paper`-Environment) — **kein** echtes IBKR-Paper-Konto noetig. Die
einzige externe Abhaengigkeit ist ein Live-Marktdaten-Feed.

**1. Voraussetzung pruefen — Live-Marktdaten-Zugang:**

Entweder ein QuantConnect-Cloud-Login (`lean login`, dann `lean whoami` zur
Bestaetigung) oder ein selbst konfigurierter Anbieter (z. B. `iex-cloud-api-key`
oder `polygon-api-key` in `lean.json` ausfuellen und `data-queue-handler` in
`lean.json`s `live-paper`-Environment entsprechend setzen). Dies kann nicht
automatisch geprueft werden (ein QC-Login lebt ausserhalb dieses Repos) — von
Hand bestaetigen, dann `phase_v2.paper_trading.live_data_provider_configured`
in `config.json` auf `true` setzen.

**2. Readiness-Report laufen lassen:**

```powershell
aq paper-readiness
```

Prueft `phase_v2.paper_trading`s Broker-Konfiguration (Brokerage gesetzt,
Live-Datenanbieter bestaetigt, manuelle Review bestaetigt) und wertet
Observation-Mode-Daten aus (`count_observations`, `simulated_sharpe`,
`simulated_max_drawdown`, dominante `rejected_by_reason`) gegen
`phase_v2.paper_trading.readiness_thresholds`. Exit-Code `1`, solange nicht
bereit — Ergebnis zusaetzlich unter `visualization/grafana/paper_readiness_report.json`,
`/api/grafana/paper-readiness` und im Webui-Panel "Paper Trading Readiness".

**3. Nach manueller Durchsicht der Trade-Historie** (der einzige Punkt, den
`aq paper-readiness` bewusst nicht automatisiert) — in `config.json`:

```json
"phase_v2": {
  "runtime": { "mode": "paper", "allow_live_orders": true },
  "paper_trading": {
    "live_data_provider_configured": true,
    "manual_review_confirmed": true
  }
}
```

**4. Paper-Session starten** (eigener, dauerhaft laufender Service, anders
als der bestehende `lean`-Service, der nur `sleep infinity` fuer
Ad-hoc-Backtests bereitstellt):

```powershell
docker compose up -d redis postgres experience-worker
docker compose --profile lean-live up -d
docker compose logs -f aether-lean-live
```

**Achtung:** `lean live deploy`s genaue CLI-Flags wurden in dieser Session
nicht gegen eine installierte Lean-CLI verifiziert (`docker-compose.yml`s
`lean-live`-Service nimmt `lean live deploy . --environment
${LEAN_LIVE_ENVIRONMENT:-live-paper}` an) — vor dem produktiven Einsatz
einmal `lean live deploy --help` pruefen.

## Live Deployment Betreiben (V2-22)

Rein strukturell — diese Phase hat keine echten Broker-Credentials angelegt
oder getestet. Ablauf, sobald ein echtes IBKR- (oder anderes
Lean-unterstuetztes) Live-Konto bereitsteht:

**1. Paper-Track-Record bestaetigen** — `aq paper-readiness` sollte ueber
einen aussagekraeftigen Zeitraum durchgaengig "ready" gemeldet haben, bevor
echtes Kapital involviert wird.

**2. Credentials hinterlegen** — zwei gleichwertige Wege
(`execution/live_credentials_io.py::load_live_credentials()` probiert beide,
`ib_config.py` zuerst):

```powershell
# Weg A: .env.live (kopiert von .env.live.example, niemals committen)
cp .env.live.example .env.live
# AETHER_IB_ACCOUNT / AETHER_IB_USER_NAME / AETHER_IB_PASSWORD ausfuellen

# Weg B: ib_config.py im Repo-Root (gitignored)
# IB_ACCOUNT = "..."; IB_USER_NAME = "..."; IB_PASSWORD = "..."; IB_TRADING_MODE = "live"
```

Das ist reine Preflight-Validierung fuer `execution/paper_readiness.py`s
`evaluate_live_broker_config()` — Lean selbst braucht die Felder zusaetzlich
**direkt in `lean.json`** (`ib-account`, `ib-user-name`, `ib-password`,
`ib-trading-mode`), von Hand eingetragen, da Lean niemals `config.json`/`.env.live`
liest.

**3. Live-Risiko-Deckel setzen** — in `config.json`:

```json
"phase_v2": {
  "live": {
    "max_allowed_daily_drawdown_pct": 0.05,
    "max_allowed_total_drawdown_pct": 0.15
  }
}
```

`main.py`s tatsaechliche `max_daily_drawdown_pct`/`max_total_drawdown_pct`
(`phase6.risk`) muessen darunter bleiben, sonst blockiert
`evaluate_live_risk_posture()` den Broker-Check dauerhaft.

**4. Umschalten und starten:**

```powershell
# config.json: phase_v2.runtime.mode = "live"
$env:LEAN_LIVE_ENVIRONMENT = "live-interactive"
docker compose --profile lean-live up -d
docker compose logs -f aether-lean-live
```

**5. Ueberwachen:** Telegram (V2-19) alarmiert bei `critical`-Triggern,
inklusive des neuen `live_order_permission_blocked_trigger` — feuert, wenn
`mode == "live"`, aber `execution_note`s weiterhin `simulated_*` zeigen
(Broker-Credentials/`allow_live_orders`/Risk-Lock pruefen). Modell-Promotion
bleibt in diesem Modus zwangsweise manuell
(`phase_v2.retraining.worker.auto_promote_blocked_in_live_mode`, Default
`true`) — `aq retrain promote --version-id <uuid>` nach Review.

## Verbindung Zwischen Containern

Innerhalb des Compose-Netzwerks nutzen die Services ihre Servicenamen:

- Redis: `redis://redis:6379/0`
- PostgreSQL: `postgresql://aether:aether_dev_password@postgres:5432/aether_quant`

Von Windows aus erreichst du die Ports standardmaessig so (seit V2-17 remapped, damit sie
nicht mit dem separaten Aether-Vault-Compose-Stack kollidieren):

- Redis: `localhost:6380`
- PostgreSQL: `localhost:5433`
- aether-quant (FastAPI + Webui-Bundle): `http://localhost:8001`
