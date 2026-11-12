"""FastAPI server exposing Aether Quant runtime visualization state as a JSON API.

Reads the same files the legacy HTML dashboards read (visualization/state.json,
visualization/scene.json, visualization/grafana/*) and serves them over HTTP so
the React webui (localhost:3000/3002) can consume them instead of fetching files
directly off disk. No new computation happens here - this is a read-only
reshape/serve layer over the existing runtime exports.

V6.6.5 (#350): users and roles (monitoring/auth.py). With a users file every /api route but /api/health needs a bearer
token; the one write, the manual trade lock of an account, needs an operator (lock) or an admin (unlock) and is written to
a hash-chained action log. Without a users file the reads stay open, as before, and nothing can write.
"""

import csv
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
# StaticFiles raises Starlette's HTTPException, of which fastapi's is a
# *subclass* - catching the fastapi one would miss it entirely.
from starlette.exceptions import HTTPException as StarletteHTTPException

from json_safety import load_json_lenient
from monitoring.assets_status import build_assets_status_from_disk
from monitoring.evaluation_state import build_evaluation_state, build_generations_state
from monitoring.neural_network_state import build_neural_network_state
from monitoring.strategy_catalog import build_strategy_catalog
import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from fastapi import Body, Request
from fastapi.responses import JSONResponse
from monitoring.auth import Role, User, authorize, verify_token
from monitoring.auth_io import auth_required, load_users, users_file

ROOT_DIR = Path(__file__).resolve().parent.parent
# V6.6.5 (#344): AQ_DASHBOARD_ROOT points every read at another tree (the demo data in monitoring/demo, which the
# `dashboard` image serves); unset, the paths are the repo's own, as before. AQ_DASHBOARD_DEMO=1 labels the feed as demo.
DATA_ROOT = Path(os.environ.get("AQ_DASHBOARD_ROOT") or ROOT_DIR).resolve()
CUSTOM_ROOT = DATA_ROOT != ROOT_DIR.resolve()
DEMO = os.environ.get("AQ_DASHBOARD_DEMO", "") == "1"
VISUALIZATION_DIR = DATA_ROOT / "visualization"
GRAFANA_DIR = VISUALIZATION_DIR / "grafana"
ML_DIR = DATA_ROOT / "ml"
WEBUI_DIST = Path(os.environ.get("AQ_WEBUI_DIST") or (ROOT_DIR / "webui" / "dist"))

app = FastAPI(title="Aether Quant Monitoring API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3002",
        "http://localhost:8000",
        "http://localhost:8001",
        "http://localhost:8080",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

OPEN_PATHS = frozenset({"/api/health"})
_users_lock = threading.Lock()
_users_cache: dict = {"key": None, "users": (), "tokens": {}}


def _current_users() -> tuple[User, ...]:
    """The users file, reloaded when it changes. Verified tokens are remembered by their SHA-256 (PBKDF2 is slow on purpose)."""
    path = users_file()
    try:
        key = (str(path), path.stat().st_mtime_ns) if path.exists() else (str(path), None)
    except OSError:
        key = (str(path), None)
    with _users_lock:
        if _users_cache["key"] != key:
            _users_cache.update(key=key, users=load_users(), tokens={})
        return _users_cache["users"]


def _user_for(token: str | None) -> User | None:
    users = _current_users()
    if not token:
        return None
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _users_lock:
        cached = _users_cache["tokens"].get(fingerprint)
    if cached is not None:
        return cached or None
    user = verify_token(users, token)
    with _users_lock:
        _users_cache["tokens"][fingerprint] = user or False
    return user


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else None


@app.middleware("http")
async def _require_auth(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in OPEN_PATHS or request.method == "OPTIONS":
        return await call_next(request)
    try:
        users = _current_users()
    except (OSError, ValueError):
        return JSONResponse({"detail": "the users file is unreadable or invalid; refusing to serve"}, status_code=503)
    required = auth_required(users)
    user = _user_for(_bearer(request)) if required else None
    if required and user is None:
        return JSONResponse({"detail": "a valid bearer token is required"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    account = request.query_params.get("account")
    if required and not authorize(user, Role.VIEWER, account, auth_required=True):
        return JSONResponse({"detail": "this user may not read that account"}, status_code=403)
    request.state.user = user
    request.state.auth_required = required
    return await call_next(request)


def _read_json(path: Path) -> dict:
    # V5.4.7 (Problems.md #120): a torn/mid-write file (or a TOCTOU delete
    # between exists() and open) previously raised JSONDecodeError /
    # FileNotFoundError -> HTTP 500. Degrade to the documented 404 shape.
    payload = load_json_lenient(path)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"{path.name} not found")
    return payload


def _read_csv_as_rows(path: Path) -> list[dict]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        raise HTTPException(status_code=404, detail=f"{path.name} not found")


@app.get("/api/health")
def health() -> dict:
    try:
        required = auth_required(_current_users())
    except (OSError, ValueError):
        required = True
    return {"status": "ok", "demo": DEMO, "auth": "required" if required else "off"}


@app.get("/api/auth/whoami")
def whoami(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    return {"auth": "required" if getattr(request.state, "auth_required", False) else "off", "user": user.name if user else None,
            "role": user.role.name.lower() if user else None, "accounts": list(user.accounts) if user else ["*"]}


def _accounts():
    from execution.accounts_io import load_accounts

    config = load_json_lenient(ROOT_DIR / "config.json") or {}
    return load_accounts(ROOT_DIR, config.get("phase_v2", {}))


@app.get("/api/accounts")
def get_accounts(request: Request) -> dict:
    """V6.6.5 (#349): the deployments, their secrets (names only) and last state; a scoped user sees their own."""
    from execution.accounts_io import account_status_rows

    if DEMO:
        return {"demo": True, "accounts": [{"id": "default", "broker": "paper", "environment": "live-paper", "mode": "demo", "secrets": "0/0",
                                             "secrets_missing": [], "state": "visualization/state.json", "reconciliation_breach": None}]}
    try:
        accounts = _accounts()
    except ValueError as error:
        raise HTTPException(status_code=500, detail=f"accounts.json is invalid: {error}") from None
    user = getattr(request.state, "user", None)
    rows = [row for row in account_status_rows(ROOT_DIR, accounts) if user is None or user.may_access(row["id"])]
    return {"demo": False, "accounts": rows}


@app.get("/api/readiness")
def get_readiness() -> dict:
    """V6.6.5 (#352): the paper-to-live scorecard `aq live-readiness` last wrote."""
    return _read_json(GRAFANA_DIR / "live_readiness.json")


def _append_action(record: dict) -> dict:
    """One hash-chained line in state/api_actions.jsonl (audit.hash_chain), and the same event on the audit stream when Redis is up."""
    from audit.hash_chain import GENESIS_HASH, compute_entry_hash

    path = ROOT_DIR / "state" / "api_actions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = GENESIS_HASH
    if path.exists():
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if lines:
            previous = json.loads(lines[-1])["hash"]
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {"prev_hash": previous, "event_type": "live_mode_transition", "created_at": created, "payload": record}
    entry["hash"] = compute_entry_hash(previous, entry["event_type"], created, record)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    try:
        from audit import LIVE_MODE_TRANSITION, AuditQueue, build_audit_event

        AuditQueue(enabled=True, stream_name="aether:audit").push(build_audit_event(LIVE_MODE_TRANSITION, record, actor=str(record.get("user") or "api")))
    except Exception:  # noqa: BLE001 - the local chain is the record; the stream is best effort
        pass
    return entry


@app.post("/api/accounts/{account_id}/trade-lock")
def set_trade_lock(account_id: str, request: Request, body: dict = Body(...)) -> dict:
    """Lock (an operator) or unlock (an admin) one account's trading through the manual trade-lock override main.py reads
    each session. `{"locked": true}` locks, `{"locked": false}` unlocks, `{"locked": null}` hands control back to the rules (admin)."""
    from execution.accounts import override_path, resolve_account
    from risk.manual_override import write_manual_trade_lock_override

    if DEMO:
        raise HTTPException(status_code=403, detail="the demo dashboard changes nothing")
    if "locked" not in body or body["locked"] not in (True, False, None):
        raise HTTPException(status_code=422, detail='body must be {"locked": true | false | null}')
    locked = body["locked"]
    user = getattr(request.state, "user", None)
    required = Role.OPERATOR if locked is True else Role.ADMIN
    if not authorize(user, required, account_id, auth_required=True):
        raise HTTPException(status_code=403, detail=f"needs an authenticated {required.name.lower()} scoped to {account_id}")
    try:
        account = resolve_account(_accounts(), account_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    target = override_path(ROOT_DIR, account)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():  # a named account's overrides file starts empty; the default account's is config.json
        target.write_text("{}", encoding="utf-8")
    write_manual_trade_lock_override(locked, target)
    entry = _append_action({"event": "manual_trade_lock", "account_id": account.id, "locked": locked, "user": user.name, "role": user.role.name.lower()})
    return {"account": account.id, "locked": locked, "written": target.relative_to(ROOT_DIR).as_posix(), "audit_hash": entry["hash"]}


@app.get("/api/state")
def get_state(account: str | None = None) -> dict:
    state_path = VISUALIZATION_DIR / "state.json"
    if account and account != "default":
        from execution.accounts import account_output_paths, resolve_account

        try:
            state_path = account_output_paths(DATA_ROOT, resolve_account(_accounts(), account))["state_path"]
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
    state = _read_json(state_path)
    retraining_status_path = GRAFANA_DIR / "retraining_status.json"
    payload = load_json_lenient(retraining_status_path)
    if payload is not None:
        state["retraining_status"] = payload
    paper_readiness_path = GRAFANA_DIR / "paper_readiness_report.json"
    payload = load_json_lenient(paper_readiness_path)
    if payload is not None:
        state["paper_readiness"] = payload
    return state


@app.get("/api/scene")
def get_scene() -> dict:
    return _read_json(VISUALIZATION_DIR / "scene.json")


@app.get("/api/topology")
def get_topology() -> dict:
    return _read_json(VISUALIZATION_DIR / "topology_state.json")


@app.get("/api/neural-network")
def get_neural_network() -> dict:
    return build_neural_network_state(ML_DIR if CUSTOM_ROOT else None)


@app.get("/api/evaluation")
def get_evaluation() -> dict:
    """V5.1 Phase 0 - the cost-aware rank-book simulation/capacity/stress
    reports `aq evaluate` writes to ml/evaluation/*.json. See
    monitoring/evaluation_state.py::build_evaluation_state() for the
    per-section not_evaluated degrade contract."""
    return build_evaluation_state(ML_DIR if CUSTOM_ROOT else None)


@app.get("/api/generations")
def get_generations() -> dict:
    """V6.6.1 - the model generations sharing the book, their decay state and what is due (`aq cycle status`)."""
    return build_generations_state(ML_DIR if CUSTOM_ROOT else None)


@app.get("/api/assets-status")
def get_assets_status() -> dict:
    return build_assets_status_from_disk(DATA_ROOT if CUSTOM_ROOT else None)


@app.get("/api/strategies")
def get_strategy_catalog() -> dict:
    return build_strategy_catalog()


@app.get("/api/grafana/metrics-snapshot")
def get_metrics_snapshot() -> dict:
    return _read_json(GRAFANA_DIR / "runtime_metrics_snapshot.json")


@app.get("/api/grafana/equity-curves")
def get_equity_curves() -> list[dict]:
    return _read_csv_as_rows(GRAFANA_DIR / "equity_curves.csv")


@app.get("/api/grafana/asset-performance")
def get_asset_performance() -> list[dict]:
    return _read_csv_as_rows(GRAFANA_DIR / "asset_performance.csv")


@app.get("/api/grafana/observation-equity-curve")
def get_observation_equity_curve() -> list[dict]:
    return _read_csv_as_rows(GRAFANA_DIR / "observation_equity_curve.csv")


@app.get("/api/grafana/retraining-status")
def get_retraining_status() -> dict:
    return _read_json(GRAFANA_DIR / "retraining_status.json")


@app.get("/api/audit-log")
def get_audit_log() -> dict:
    """Reads visualization/grafana/audit_log.json - written by
    audit/postgres_worker.py after every batch it persists (development/
    Problems.md #42). Same "main.py can't reach Postgres, so a worker
    exports a JSON snapshot" pattern as /api/grafana/retraining-status
    (see retraining/status_export.py's docstring)."""
    return _read_json(GRAFANA_DIR / "audit_log.json")


@app.get("/api/grafana/paper-readiness")
def get_paper_readiness() -> dict:
    return _read_json(GRAFANA_DIR / "paper_readiness_report.json")


class SpaStaticFiles(StaticFiles):
    """Serves the built webui with a client-side-routing fallback.

    `StaticFiles(html=True)` alone only maps *directory* paths to
    index.html - an unknown path like /risk or /operations still 404s. The
    React router owns those paths, so every tab except / broke on a direct
    load or hard refresh whenever the SPA was served from here (the Docker
    image and any bare-uvicorn run; the vite dev server has its own
    fallback, which is why this never showed up in local development).

    Only extensionless paths fall back. A missing /assets/*.js must keep
    404ing rather than silently returning index.html, which would turn a
    broken build into a blank page with no error.
    """

    async def get_response(self, path: str, scope):
        # Starlette signals a missing file by *raising* HTTPException(404),
        # not by returning a 404 response - catching is the only way to
        # intercept it.
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not Path(path).suffix:
                return await super().get_response("index.html", scope)
            raise


# Mounted last on purpose: "/" is a catch-all, so any route registered
# below it would be shadowed by the SPA.
if WEBUI_DIST.exists():
    app.mount("/", SpaStaticFiles(directory=WEBUI_DIST, html=True), name="static")
