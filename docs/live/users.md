# Users

| Role | May |
|---|---|
| viewer | read every page and route |
| operator | also lock an account's trading (the manual trade lock) |
| admin | also unlock it, or hand it back to the rules |

```bash
aq users add ada --role admin                      # prints the token once
aq users add sam --role operator --accounts paper-b
aq users list
aq users remove sam                                # revokes the token
```

- **How tokens are kept.** Tokens are random, and stored only as salted PBKDF2-SHA256 hashes in `state/users.json` (gitignored, owner-only; `AQ_USERS_FILE` moves it).
- **What a request needs.** With at least one user, or `AQ_AUTH=required`, every `/api` route but `/api/health` needs `Authorization: Bearer <token>`, and the dashboard asks for it. A user scoped to some accounts cannot read or lock another.
- **What is recorded.** `POST /api/accounts/<id>/trade-lock` writes the override `main.py` reads each session and appends a hash-chained record to `state/api_actions.jsonl`, with the user's name. When Redis is up, the same event goes to the audit stream.
- **Before serving the LAN.** The engine's port is bound to `127.0.0.1` by default. Set `AETHER_QUANT_BIND=0.0.0.0` only with users configured, because the API includes the audit log.

`authorize` never grants above a user's role or outside their accounts, and an anonymous caller can never write. This is proved in `formal/AetherFormal/Authorize.lean` and checked against the Python on 400 generated cases.
