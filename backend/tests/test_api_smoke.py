"""End-to-end HTTP smoke test for the whole API surface, with NO real Postgres or
Gmail: the DB session and the scheduler are replaced with in-memory fakes/mocks.

This is deliberately different from the other test files (which unit-test the
pure-logic layer with a real DB kept out of the picture). Those tests never touch
`app.main`, so the router wiring, auth guard, and request/response shapes were never
actually exercised (see .coveragerc — routers/main.py are excluded from coverage
for exactly this reason: they need "a live Postgres/Gmail account"). This file
plugs that gap by faking just enough of a DB session to drive the FastAPI app
through TestClient, proving the whole request path (routing -> auth -> handler ->
response) works, independent of any real database.

Run: cd backend && .venv/Scripts/pytest tests/test_api_smoke.py -v
"""
from __future__ import annotations

import itertools
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class FakeResult:
    """Stands in for a SQLAlchemy CursorResult: enough surface for the routers
    (.mappings().all()/.first(), .all(), .rowcount) to run unmodified."""

    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount if rows is None else len(rows)

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """A minimal in-memory stand-in for a SQLAlchemy Session.

    Matches on a distinctive substring of each SQL statement the routers issue
    (see app/routers/*.py) and returns canned/dynamic rows — no real SQL is ever
    parsed or executed. This keeps the test tied to *behavior* (does POST /contacts
    return a 201 with a send id?) rather than to persistence internals.
    """

    _id_counter = itertools.count(1)

    def __init__(self):
        self.templates = [{
            "id": 1, "name": "Generic", "kind": "generic",
            "subject": "Hi {company}", "body": "Hello {name}, {signature}",
            "attach_resume": False, "is_active": True,
            "created_at": datetime.now(timezone.utc),
        }]
        self.sends = {}
        self.suppression = {}
        self.committed = False

    def execute(self, clause, params=None):
        sql = str(clause).strip()
        params = params or {}

        if "SELECT 1" in sql:
            return FakeResult([(1,)])
        if "FROM templates WHERE is_active" in sql:
            return FakeResult(list(self.templates))
        if sql.startswith("INSERT INTO templates"):
            row = {**params, "id": next(self._id_counter), "is_active": True,
                   "created_at": datetime.now(timezone.utc)}
            self.templates.append(row)
            return FakeResult([row])
        if "FROM suppression_list" in sql and sql.startswith("SELECT"):
            return FakeResult(list(self.suppression.values()))
        if sql.startswith("INSERT INTO suppression_list"):
            self.suppression[params["e"]] = {
                "email": params["e"], "reason": params["r"], "note": params.get("n"),
            }
            return FakeResult(rowcount=1)
        if sql.startswith("DELETE FROM suppression_list"):
            existed = params["e"] in self.suppression
            self.suppression.pop(params["e"], None)
            return FakeResult(rowcount=1 if existed else 0)
        if "GROUP BY status" in sql and "sends" in sql:
            return FakeResult([(s["status"], 1) for s in self.sends.values()])
        if "GROUP BY status" in sql and "threads" in sql:
            return FakeResult([])
        if sql.startswith("UPDATE sends SET status='approved'"):
            sid = params["id"]
            send = self.sends.get(sid)
            if send and send["status"] == "pending_approval":
                send["status"] = "approved"
                return FakeResult(rowcount=1)
            return FakeResult(rowcount=0)
        if sql.startswith("UPDATE sends SET status='pending_approval'"):
            sid = params["id"]
            send = self.sends.get(sid)
            if send and send["status"] == "approved":
                send["status"] = "pending_approval"
                return FakeResult([dict(send)])
            return FakeResult([])
        if sql.startswith("UPDATE sends SET status='cancelled'"):
            sid = params["id"]
            send = self.sends.get(sid)
            if send and send["status"] in ("pending_approval", "approved"):
                send["status"] = "cancelled"
                return FakeResult(rowcount=1)
            return FakeResult(rowcount=0)
        if sql.startswith("SELECT status FROM sends WHERE id"):
            send = self.sends.get(params["id"])
            return FakeResult([(send["status"],)] if send else [])
        if sql.startswith("UPDATE sends SET") and ("subject" in sql or "scheduled_at" in sql):
            sid = params["id"]
            send = self.sends[sid]
            send.update({k: v for k, v in params.items() if k != "id"})
            return FakeResult([dict(send)])
        if sql.startswith("SELECT * FROM sends"):
            return FakeResult(list(self.sends.values()))
        if "audit_log" in sql:
            return FakeResult(rowcount=1)

        raise AssertionError(f"FakeSession got an unexpected query: {sql!r}")

    def add_send(self, **overrides):
        sid = next(self._id_counter)
        send = {
            "id": sid, "thread_id": 1, "type": "initial",
            "subject": "Hi Acme", "body": "Hello there,", "scheduled_at": None,
            "sent_at": None, "status": "pending_approval", "error": None,
            "attempts": 0, "gmail_message_id": None,
        }
        send.update(overrides)
        self.sends[sid] = send
        return sid

    def commit(self):
        self.committed = True

    def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    """Build a TestClient with the scheduler neutered (no APScheduler, no real
    catch_up() DB hit) and get_db swapped for an in-memory FakeSession."""
    monkeypatch.setenv("API_TOKEN", "")  # local-dev mode: auth disabled
    with patch("app.services.scheduler.start"), patch("app.services.scheduler.shutdown"):
        from app.core.db import get_db
        from app.main import app

        fake_db = FakeSession()

        def _override():
            yield fake_db

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as c:
            c.fake_db = fake_db
            yield c
        app.dependency_overrides.clear()


def test_health_is_open_and_needs_no_token(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ready_checks_the_database(client):
    # /ready lives unversioned, alongside /health
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready", "database": "ok"}


def test_stats_returns_zeroed_dashboard_counts_with_no_data(client):
    res = client.get("/api/v1/stats")
    assert res.status_code == 200
    body = res.json()
    assert body["pending_approval"] == 0
    assert body["reply_rate"] == 0


def test_list_templates_returns_the_seeded_template(client):
    res = client.get("/api/v1/templates")
    assert res.status_code == 200
    names = [t["name"] for t in res.json()]
    assert "Generic" in names


def test_create_template_then_it_appears_in_the_list(client):
    res = client.post("/api/v1/templates", json={
        "name": "Startup", "kind": "startup",
        "subject": "Hey {company}", "body": "Hi {name}",
    })
    assert res.status_code == 201
    assert res.json()["name"] == "Startup"

    res = client.get("/api/v1/templates")
    assert any(t["name"] == "Startup" for t in res.json())


def test_suppression_add_then_remove_round_trip(client):
    res = client.post("/api/v1/suppression", json={"email": "Bad@Example.com"})
    assert res.status_code == 201
    assert res.json()["email"] == "bad@example.com"

    res = client.delete("/api/v1/suppression/bad@example.com")
    assert res.status_code == 204

    # removing again is a 404 — proves the DELETE actually mutated the fake store
    res = client.delete("/api/v1/suppression/bad@example.com")
    assert res.status_code == 404


def test_approval_lifecycle_approve_unapprove_edit_cancel(client):
    send_id = client.fake_db.add_send()

    # approve moves pending_approval -> approved
    res = client.post(f"/api/v1/sends/{send_id}/approve")
    assert res.status_code == 204
    assert client.fake_db.sends[send_id]["status"] == "approved"

    # editing an approved send is refused (human-in-the-loop: approved = locked)
    res = client.patch(f"/api/v1/sends/{send_id}", json={"subject": "New subject"})
    assert res.status_code == 400

    # unapprove sends it back for review...
    res = client.post(f"/api/v1/sends/{send_id}/unapprove")
    assert res.status_code == 200
    assert res.json()["status"] == "pending_approval"

    # ...and now the edit goes through
    res = client.patch(f"/api/v1/sends/{send_id}", json={"subject": "New subject"})
    assert res.status_code == 200
    assert res.json()["subject"] == "New subject"

    # cancel works from pending_approval too
    res = client.post(f"/api/v1/sends/{send_id}/cancel")
    assert res.status_code == 204
    assert client.fake_db.sends[send_id]["status"] == "cancelled"


def test_edit_send_can_correct_a_stale_scheduled_time(client):
    # Regression coverage for the bug where approving/unapproving/editing subject
    # or body could never fix a send's scheduled_at queued under old Settings —
    # edit_send now accepts scheduled_at directly.
    from datetime import datetime, timezone

    send_id = client.fake_db.add_send(scheduled_at="2026-07-06T09:00:00+00:00")
    new_time = "2026-07-05T09:15:00+00:00"

    res = client.patch(f"/api/v1/sends/{send_id}", json={"scheduled_at": new_time})
    assert res.status_code == 200
    got = datetime.fromisoformat(res.json()["scheduled_at"].replace("Z", "+00:00"))
    assert got == datetime(2026, 7, 5, 9, 15, tzinfo=timezone.utc)


def test_unapprove_a_send_that_is_not_approved_is_rejected(client):
    send_id = client.fake_db.add_send(status="pending_approval")
    res = client.post(f"/api/v1/sends/{send_id}/unapprove")
    assert res.status_code == 400


def test_guarded_routes_require_the_token_when_one_is_configured(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "s3cret")
    with patch("app.services.scheduler.start"), patch("app.services.scheduler.shutdown"):
        # config is cached per-process (get_settings) in several modules at import
        # time, so patch the already-imported settings objects directly instead of
        # relying on the env var alone.
        import app.core.security as security_mod

        from app.core.db import get_db
        from app.main import app

        def _override():
            yield FakeSession()

        app.dependency_overrides[get_db] = _override
        monkeypatch.setattr(security_mod._settings, "api_token", "s3cret")
        with TestClient(app) as c:
            res = c.get("/api/v1/stats")
            assert res.status_code == 401

            res = c.get("/api/v1/stats", headers={"X-API-Token": "s3cret"})
            assert res.status_code == 200

            res = c.get("/api/v1/stats", headers={"X-API-Token": "wrong"})
            assert res.status_code == 401
        app.dependency_overrides.clear()


def test_health_needs_no_token_even_when_one_is_configured(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "s3cret")
    with patch("app.services.scheduler.start"), patch("app.services.scheduler.shutdown"):
        import app.core.security as security_mod

        from app.main import app

        monkeypatch.setattr(security_mod._settings, "api_token", "s3cret")
        with TestClient(app) as c:
            res = c.get("/health")
            assert res.status_code == 200
