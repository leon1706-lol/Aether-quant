"""The API's users, roles and the audited trade lock (V6.6.5, #350), through FastAPI's test client."""

from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from audit.hash_chain import verify_chain  # noqa: E402
from monitoring.auth import Role, make_user  # noqa: E402
from monitoring.auth_io import save_users  # noqa: E402


@pytest.fixture
def api(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "visualization").mkdir(parents=True)
    (root / "visualization" / "state.json").write_text(json.dumps({"mode": "paper", "positions": []}), encoding="utf-8")
    (root / "config.json").write_text(json.dumps({"phase_v2": {"live": {"max_allowed_total_drawdown_pct": 0.15}}}), encoding="utf-8")
    (root / "accounts.json").write_text(json.dumps({"accounts": [{"id": "paper-b", "broker": "paper"}]}), encoding="utf-8")
    monkeypatch.setenv("AQ_USERS_FILE", str(tmp_path / "users.json"))
    monkeypatch.setenv("AQ_ACCOUNTS_FILE", str(root / "accounts.json"))
    monkeypatch.delenv("AQ_AUTH", raising=False)
    monkeypatch.delenv("AQ_DASHBOARD_DEMO", raising=False)
    monkeypatch.setenv("AQ_DASHBOARD_ROOT", str(root))
    import monitoring.api_server as api_server

    module = importlib.reload(api_server)
    monkeypatch.setattr(module, "ROOT_DIR", root)
    tokens = {"viewer": "tok-viewer", "operator": "tok-operator", "scoped": "tok-scoped", "admin": "tok-admin"}
    users = (
        make_user("vera", Role.VIEWER, tokens["viewer"]),
        make_user("otto", Role.OPERATOR, tokens["operator"]),
        make_user("sam", Role.OPERATOR, tokens["scoped"], accounts=["paper-b"]),
        make_user("ada", Role.ADMIN, tokens["admin"]),
    )
    yield module, TestClient(module.app), tokens, users, root
    monkeypatch.delenv("AQ_DASHBOARD_ROOT")
    importlib.reload(api_server)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_without_users_reads_are_open_and_writes_are_closed(api):
    _, client, tokens, _, _ = api
    assert client.get("/api/health").json()["auth"] == "off"
    assert client.get("/api/state").status_code == 200
    assert client.post("/api/accounts/default/trade-lock", json={"locked": True}).status_code == 403


def test_with_users_every_route_but_health_needs_a_token(api):
    _, client, tokens, users, _ = api
    save_users(users)
    assert client.get("/api/health").status_code == 200 and client.get("/api/health").json()["auth"] == "required"
    assert client.get("/api/state").status_code == 401
    assert client.get("/api/state", headers=_auth("wrong")).status_code == 401
    assert client.get("/api/state", headers=_auth(tokens["viewer"])).status_code == 200
    whoami = client.get("/api/auth/whoami", headers=_auth(tokens["scoped"])).json()
    assert whoami == {"auth": "required", "user": "sam", "role": "operator", "accounts": ["paper-b"]}
    assert client.get("/api/state?account=default", headers=_auth(tokens["scoped"])).status_code == 403


def test_lock_needs_an_operator_unlock_an_admin_and_each_is_chained(api):
    module, client, tokens, users, root = api
    save_users(users)
    assert client.post("/api/accounts/default/trade-lock", json={"locked": True}, headers=_auth(tokens["viewer"])).status_code == 403
    locked = client.post("/api/accounts/default/trade-lock", json={"locked": True}, headers=_auth(tokens["operator"]))
    assert locked.status_code == 200, locked.text
    assert locked.json()["written"] == "config.json"
    assert json.loads((root / "config.json").read_text(encoding="utf-8"))["phase_v2"]["risk"]["manual_trade_lock_override"] is True
    assert client.post("/api/accounts/default/trade-lock", json={"locked": False}, headers=_auth(tokens["operator"])).status_code == 403
    assert client.post("/api/accounts/default/trade-lock", json={"locked": False}, headers=_auth(tokens["admin"])).status_code == 200
    assert client.post("/api/accounts/default/trade-lock", json={"locked": True}, headers=_auth(tokens["scoped"])).status_code == 403
    scoped = client.post("/api/accounts/paper-b/trade-lock", json={"locked": True}, headers=_auth(tokens["scoped"]))
    assert scoped.status_code == 200 and scoped.json()["written"] == "state/accounts/paper-b/overrides.json"
    assert client.post("/api/accounts/nope/trade-lock", json={"locked": True}, headers=_auth(tokens["admin"])).status_code == 404
    assert client.post("/api/accounts/default/trade-lock", json={"locked": "yes"}, headers=_auth(tokens["admin"])).status_code == 422
    rows = [json.loads(line) for line in (root / "state" / "api_actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3 and [row["payload"]["user"] for row in rows] == ["otto", "ada", "sam"]
    assert verify_chain(rows)[0] is True


def test_an_invalid_users_file_refuses_to_serve(api, tmp_path):
    _, client, _, _, _ = api
    (tmp_path / "users.json").write_text("{bad", encoding="utf-8")
    assert client.get("/api/state").status_code == 503
    assert client.get("/api/health").json()["auth"] == "required"


def test_accounts_lists_what_a_user_may_see(api):
    _, client, tokens, users, _ = api
    save_users(users)
    seen = [row["id"] for row in client.get("/api/accounts", headers=_auth(tokens["scoped"])).json()["accounts"]]
    assert seen == ["paper-b"]
    assert [row["id"] for row in client.get("/api/accounts", headers=_auth(tokens["admin"])).json()["accounts"]] == ["default", "paper-b"]
