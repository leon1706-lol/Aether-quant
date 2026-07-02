# infrastructure

Docker Compose verbindet die lokalen V2-Bausteine:

- `lean`: Lean Runtime / Backtest-Umgebung
- `grafana`: Monitoring-Oberflaeche
- `redis`: schneller temporaerer In-Memory-Puffer fuer Signale, Trades und Rohmetriken
- `postgres`: permanente Experience Database und spaetere Single Source of Truth fuer Retraining

## Datenfluss

1. Live- oder Observation-Schleife erzeugt ein Signal und schreibt rohe Metriken sofort nach Redis.
2. Redis speichert die Events temporaer als Stream oder Queue, zum Beispiel per `XADD` oder `LPUSH`.
3. Ein Worker liest entkoppelt aus Redis, zum Beispiel per `XREAD` oder `BLPOP`.
4. Der Worker schreibt Events gebuendelt nach PostgreSQL.
5. Controlled Retraining nutzt PostgreSQL als stabile Datenquelle.

## Start

```powershell
docker compose up -d redis postgres grafana
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

Wenn du eigene Redis-, PostgreSQL-, Grafana- oder Lean-Images hast, setzt du vor dem Start die Image-Namen:

```powershell
$env:REDIS_IMAGE="dein-redis-image:tag"
$env:POSTGRES_IMAGE="dein-postgres-image:tag"
$env:GRAFANA_IMAGE="dein-grafana-image:tag"
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
`localhost:6379` des Hosts. Fuer eine echte Redis-Verbindung waehrend des
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
python -m uvicorn monitoring.api_server:app --reload
cd webui && npm run dev
```

Im Webui (`http://localhost:3000`) zeigt das neue "Observation Mode" Panel
(`webui/src/components/monitoring/ObservationPanel.tsx`) das gelbe
"SIMULATED - NOT REAL TRADES"-Banner, simulierte Equity/Exposure/Drawdown/
Turnover, Sharpe, Signal-Verteilung und "Rejected By Reason". Dieselben
Daten liegen als Datei unter `visualization/grafana/observation_summary.json`
und `visualization/grafana/observation_equity_curve.csv`, bzw. per API unter
`/api/grafana/observation-summary` und `/api/grafana/observation-equity-curve`.

**5. Bereit fuer Paper Trading?** Checkliste, bevor `phase_v2.runtime.mode`
auf `"paper"` umgestellt wird (zusaetzlich zu `allow_live_orders=true` und
vorhandener Broker-Konfiguration):

- Ausreichend Beobachtungsvolumen (`count_observations` deutlich > 0 ueber
  mehrere Markttage/-regime hinweg).
- `simulated_max_drawdown` in einem akzeptablen Rahmen.
- `rejected_by_reason` zeigt keine dominante, unerwartete Ablehnungsursache
  (z. B. staendig `liquidity_blocked_insufficient_volume_simulate_instead`
  fuer Kernassets).
- `simulated_sharpe` liegt ueber einer selbst definierten Mindestschwelle.
- Manuelle Durchsicht der Trade-Historie (`SimulatedPortfolioState.trade_log`
  bzw. die Experience Events) zeigt plausible Entry-/Exit-Preise.

## Verbindung Zwischen Containern

Innerhalb des Compose-Netzwerks nutzen die Services ihre Servicenamen:

- Redis: `redis://redis:6379/0`
- PostgreSQL: `postgresql://aether:aether_dev_password@postgres:5432/aether_quant`
- Grafana: `http://grafana:3000`

Von Windows aus erreichst du die Ports standardmaessig so:

- Grafana: `http://localhost:3000`
- Redis: `localhost:6379`
- PostgreSQL: `localhost:5432`
