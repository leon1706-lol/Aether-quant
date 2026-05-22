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

## Eigene Images Verwenden

Wenn du eigene Redis-, PostgreSQL-, Grafana- oder Lean-Images hast, setzt du vor dem Start die Image-Namen:

```powershell
$env:REDIS_IMAGE="dein-redis-image:tag"
$env:POSTGRES_IMAGE="dein-postgres-image:tag"
$env:GRAFANA_IMAGE="dein-grafana-image:tag"
$env:LEAN_IMAGE="dein-lean-image:tag"
docker compose --profile lean up -d
```

## Verbindung Zwischen Containern

Innerhalb des Compose-Netzwerks nutzen die Services ihre Servicenamen:

- Redis: `redis://redis:6379/0`
- PostgreSQL: `postgresql://aether:aether_dev_password@postgres:5432/aether_quant`
- Grafana: `http://grafana:3000`

Von Windows aus erreichst du die Ports standardmaessig so:

- Grafana: `http://localhost:3000`
- Redis: `localhost:6379`
- PostgreSQL: `localhost:5432`
