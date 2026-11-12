# The dashboard

One command, with demo data and no database:

```bash
docker run --rm -p 8080:8000 ghcr.io/leon1706-lol/aether-quant-dashboard:latest
# then open http://localhost:8080
```

The `dashboard` image holds FastAPI, the built web UI and demo data generated from `aq hello`'s run of the shipped rule on the bundled sample (`scripts/build_dashboard_demo.py`). Every page says it is demo data. Nothing in it comes from a broker, a model or a Lean run. The image has no torch, no Lean and no Postgres; it installs the library's wheel and nothing of the trading system.

| Command | What |
|---|---|
| `aq webui --docker` | the same image (`--build` builds it from your clone first) |
| `aq webui --docker --data DIR` | serve a real run's `visualization/` and `ml/` read-only instead of the demo |
| `docker compose --profile dashboard up dashboard` | the same, from the compose file, on port 8080 |
| `aq api` then `aq webui` | development: the API on 8001 and the Vite server on 3002 |

## Users

With no users file the API's reads are open and nothing can write, as before. `aq users add NAME --role viewer|operator|admin` turns auth on: every `/api` route but `/api/health` then needs a bearer token, and the dashboard asks for it. An operator may lock an account's trading from the Operations page, and only an admin may unlock it. Each change is written to a hash-chained action log. See [Users](../live/users.md).
