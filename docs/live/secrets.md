# Secrets

Every credential has a name: `IB_ACCOUNT`, `IB_USER_NAME`, `IB_PASSWORD`, `IB_TRADING_MODE`, `COINBASE_API_KEY`, `COINBASE_API_SECRET`, `POSTGRES_DSN`, `REDIS_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `POLYGON_API_KEY` and `IEX_CLOUD_API_KEY`. `execution/secrets_io.py` finds each one, first match wins, in:

1. the file named by `AETHER_<NAME>_FILE` (the Docker and Kubernetes convention)
2. the Docker secret `/run/secrets/aether_<name>`
3. the environment variable `AETHER_<NAME>`, which is what every service read before; with only that set, nothing changes
4. the OS keyring, service `aether-quant` (`aq secrets set NAME`)

A named account reads `AETHER_<ACCOUNT>_<NAME>` instead, so two accounts never share a credential by accident. A value travels as a `SecretValue`, whose `repr`, `str` and f-string forms are `***`.

```bash
aq secrets status                 # names, whether each resolves, from where; never a value
aq secrets set COINBASE_API_KEY   # prompted, stored in the OS keyring (pip install keyring)
aq render-lean-config             # lean.live.json for the default account, from those sources
aq render-lean-config --account live-1   # lean.live.live-1.json
```

**With Docker**, `docker-compose.secrets.yml` mounts `secrets/postgres_password` and `secrets/postgres_dsn` (gitignored and dockerignored) as Docker secrets, and Postgres reads `POSTGRES_PASSWORD_FILE`:

```bash
docker compose -f docker-compose.yml -f docker-compose.secrets.yml up -d
```

**Never in a repo file.** The tracked `lean.json` stays empty: `aq secrets-check`, the pre-commit hook and gitleaks in CI fail a commit that fills a secret field. **Rotation** is RUNBOOK "Secrets": set the new value, render again, restart the deployment, then revoke the old key at the venue.
