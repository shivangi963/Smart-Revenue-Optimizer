"""Authentication & authorisation tests."""
import dataclasses
import time

import jwt
import pytest

from app import security
from app.config import settings
from conftest import ADMIN, bearer, login

PUBLIC = ["/", "/health", "/api/config", "/auth/status"]
PROTECTED_GET = ["/products", "/products/1", "/prices/1/current", "/prices/current", "/history/1", "/rules",
                 "/api/model/info", "/api/model/metrics", "/api/dashboard/stats", "/api/weather/current",
                 "/api/holidays/upcoming", "/api/exchange/currencies", "/api/analytics/revenue-curve/1",
                 "/signals/1", "/recommendations/1", "/auth/me", "/auth/users"]


def make_user(client, name, role="viewer", password="Viewer-Pass-1"):
    r = client.post("/auth/users", json={"username": name, "password": password, "role": role})
    assert r.status_code == 201, r.text
    return r.json()


def token_for(anon, name, password="Viewer-Pass-1"):
    r = login(anon, name, password)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ------------------------------------------------------------------ passwords
def test_password_hashing():
    h1, h2 = security.hash_password("correct horse"), security.hash_password("correct horse")
    assert h1 != h2 and h1.startswith("pbkdf2_sha256$")            # unique salt every time
    assert security.verify_password("correct horse", h1) and not security.verify_password("wrong", h1)
    for junk in ("", "plaintext", "a$b$c$d", "pbkdf2_sha256$x$y$z"):
        assert security.verify_password("anything", junk) is False


# --------------------------------------------------------------- open vs closed
def test_public_endpoints_need_no_login(anon):
    for path in PUBLIC:
        assert anon.get(path).status_code == 200, path


def test_everything_else_requires_login(anon):
    for path in PROTECTED_GET:
        r = anon.get(path)
        assert r.status_code == 401, (path, r.status_code)
        assert r.headers["www-authenticate"] == "Bearer"
    assert anon.post("/simulate_price", json={"product_id": 1, "features": {}}).status_code == 401
    assert anon.post("/products", json={}).status_code == 401
    assert anon.post("/api/model/retrain", json={}).status_code == 401


def test_login_and_session(anon):
    r = login(anon, "admin", ADMIN[1])
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["user"]["role"] == "admin" and "hash" not in str(body)
    assert "password_hash" not in body["user"]
    me = anon.get("/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200 and me.json()["username"] == "admin"
    assert login(anon, "ADMIN", ADMIN[1]).status_code == 200            # usernames are case-insensitive


def test_bad_logins_are_indistinguishable(anon):
    wrong_pw, no_user = login(anon, "admin", "nope-nope-nope"), login(anon, "ghost-user", "nope-nope-nope")
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()                              # no username enumeration


# ---------------------------------------------------------------------- tokens
def test_forged_expired_and_tampered_tokens_are_rejected(anon, client):
    me = client.get("/auth/me").json()
    good = dict(sub=str(me["id"]), role="admin", tv=0, iat=int(time.time()))
    cases = {
        "garbage": "not.a.token",
        "expired": jwt.encode({**good, "exp": int(time.time()) - 60}, settings.secret_key, algorithm="HS256"),
        "wrong secret": jwt.encode({**good, "exp": int(time.time()) + 600}, "some-other-secret", algorithm="HS256"),
        "alg none": jwt.encode({**good, "exp": int(time.time()) + 600}, None, algorithm="none"),
        "unknown user": jwt.encode({**{**good, "sub": "99999"}, "exp": int(time.time()) + 600}, settings.secret_key, algorithm="HS256"),
        "no subject": jwt.encode({"exp": int(time.time()) + 600}, settings.secret_key, algorithm="HS256"),
    }
    for name, token in cases.items():
        assert anon.get("/auth/me", headers=bearer(token)).status_code == 401, name
    valid = client.headers["Authorization"].split()[1]
    assert anon.get("/auth/me", headers=bearer(valid[:-3] + ("abc" if valid[-3:] != "abc" else "xyz"))).status_code == 401
    assert "expired" in anon.get("/auth/me", headers=bearer(cases["expired"])).json()["detail"].lower()


def test_role_claim_in_token_cannot_be_trusted(anon, client):
    """Forging role=admin without the secret must fail, and a real viewer token must not gain admin rights."""
    make_user(client, "claimcheck")
    vt = token_for(anon, "claimcheck")
    payload = jwt.decode(vt, options={"verify_signature": False})
    forged = jwt.encode({**payload, "role": "admin"}, "guess", algorithm="HS256")
    assert anon.post("/products", json={}, headers=bearer(forged)).status_code == 401
    # even a *correctly signed* token claiming admin is judged by the DB role, not the claim
    signed = jwt.encode({**payload, "role": "admin"}, settings.secret_key, algorithm="HS256")
    assert anon.post("/rules", json={"scope": "global", "rule_type": "freeze"}, headers=bearer(signed)).status_code == 403


# ----------------------------------------------------------------------- roles
def test_viewer_is_read_only(anon, client):
    make_user(client, "viewer1")
    h = bearer(token_for(anon, "viewer1"))
    for path in ("/products", "/prices/1/current", "/history/1", "/rules", "/api/model/metrics",
                 "/api/dashboard/stats", "/api/analytics/price-forecast/1", "/auth/me"):
        assert anon.get(path, headers=h).status_code == 200, path
    assert anon.post("/simulate_price", json={"product_id": 1, "features": {"precipitation": 0.5}}, headers=h).status_code == 200
    forbidden = [
        ("post", "/products", {"sku": "V1", "name": "x", "category": "umbrella", "base_price": 10, "cost": 5}),
        ("put", "/products/1", {"name": "hacked"}),
        ("delete", "/products/1", None),
        ("post", "/products/1/update_stock", {"new_stock": 5}),
        ("post", "/rules", {"scope": "global", "rule_type": "freeze"}),
        ("put", "/rules/1", {"is_active": False}),
        ("delete", "/rules/1", None),
        ("post", "/api/model/retrain", {}),
        ("post", "/api/model/select", {"model_type": "linear"}),
        ("post", "/signals/simulate", None),
        ("post", "/signals", {"product_id": 1, "page_views": 5}),
        ("get", "/auth/users", None),
        ("post", "/auth/users", {"username": "evil", "password": "Evil-Pass-123", "role": "admin"}),
        ("put", "/auth/users/1", {"role": "viewer"}),
        ("delete", "/auth/users/1", None),
    ]
    for method, path, body in forbidden:
        r = getattr(anon, method)(path, headers=h, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (method, path, r.status_code)
    assert client.get("/products/1").json()["name"] == "Premium Umbrella"           # nothing was changed


# ------------------------------------------------------------ user management
def test_user_validation_and_duplicates(client):
    ok = {"username": "newperson", "password": "Another-Pass-9", "role": "viewer"}
    assert client.post("/auth/users", json=ok).status_code == 201
    assert client.post("/auth/users", json={**ok, "username": "NewPerson"}).status_code == 409
    assert client.post("/auth/users", json={**ok, "username": "x"}).status_code == 422
    assert client.post("/auth/users", json={**ok, "username": "bad name!"}).status_code == 422
    assert client.post("/auth/users", json={**ok, "username": "u2", "password": "short"}).status_code == 422
    assert client.post("/auth/users", json={**ok, "username": "u3", "password": "admin123"}).status_code == 422
    assert client.post("/auth/users", json={**ok, "username": "u4", "role": "root"}).status_code == 422
    users = client.get("/auth/users").json()
    assert all("password" not in u and "password_hash" not in u for u in users)


def test_role_change_and_deactivation_cut_off_existing_sessions(anon, client):
    u = make_user(client, "shiftrole")
    old = token_for(anon, "shiftrole")
    assert anon.get("/auth/me", headers=bearer(old)).status_code == 200
    assert client.put(f"/auth/users/{u['id']}", json={"role": "admin"}).json()["role"] == "admin"
    assert anon.get("/auth/me", headers=bearer(old)).status_code == 401           # old token revoked
    new = token_for(anon, "shiftrole")
    assert anon.get("/auth/users", headers=bearer(new)).status_code == 200      # now really an admin
    client.put(f"/auth/users/{u['id']}", json={"is_active": False})
    assert anon.get("/auth/me", headers=bearer(new)).status_code == 401
    assert login(anon, "shiftrole", "Viewer-Pass-1").status_code == 401         # cannot sign in while disabled
    assert client.delete(f"/auth/users/{u['id']}").status_code == 200
    assert client.delete(f"/auth/users/{u['id']}").status_code == 404


def test_admin_cannot_lock_everyone_out(client):
    me = client.get("/auth/me").json()
    assert client.put(f"/auth/users/{me['id']}", json={"role": "viewer"}).status_code == 400
    assert client.put(f"/auth/users/{me['id']}", json={"is_active": False}).status_code == 400
    assert client.delete(f"/auth/users/{me['id']}").status_code == 400
    assert client.get("/auth/me").status_code == 200


def test_admin_reset_forces_a_password_change(anon, client):
    u = make_user(client, "resetme")
    assert client.put(f"/auth/users/{u['id']}", json={"password": "Reset-By-Admin-7"}).json()["must_change_password"] is True
    assert login(anon, "resetme", "Viewer-Pass-1").status_code == 401           # old password dead
    t = token_for(anon, "resetme", "Reset-By-Admin-7")
    assert anon.get("/auth/me", headers=bearer(t)).json()["must_change_password"] is True


# ------------------------------------------------------------- change password
def test_change_password_flow(anon, client):
    make_user(client, "pwuser")
    t1 = token_for(anon, "pwuser")
    h = bearer(t1)
    body = {"current_password": "Viewer-Pass-1", "new_password": "Brand-New-Pass-5"}
    assert anon.post("/auth/change-password", json={**body, "current_password": "wrong-one"}, headers=h).status_code == 400
    assert anon.post("/auth/change-password", json={**body, "new_password": "Viewer-Pass-1"}, headers=h).status_code == 400
    assert anon.post("/auth/change-password", json={**body, "new_password": "weak"}, headers=h).status_code == 422
    r = anon.post("/auth/change-password", json=body, headers=h)
    assert r.status_code == 200
    assert anon.get("/auth/me", headers=h).status_code == 401                    # every old token is revoked...
    assert anon.get("/auth/me", headers=bearer(r.json()["access_token"])).status_code == 200   # ...but the new one works
    assert login(anon, "pwuser", "Viewer-Pass-1").status_code == 401
    assert login(anon, "pwuser", "Brand-New-Pass-5").status_code == 200


# ------------------------------------------------------------------ brute force
def test_lockout_after_repeated_failures(anon, client):
    make_user(client, "lockme")
    for _ in range(security.LoginThrottle.MAX_FAILURES):
        assert login(anon, "lockme", "wrong-password").status_code == 401
    r = login(anon, "lockme", "Viewer-Pass-1")                                 # correct password, but locked
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
    assert login(anon, "admin", ADMIN[1]).status_code == 200                   # other accounts are unaffected
    security.login_throttle.clear("lockme|testclient")
    assert login(anon, "lockme", "Viewer-Pass-1").status_code == 200


# ------------------------------------------------------------------ ingest key
def test_signal_ingestion_accepts_api_key_or_admin_only(anon, client):
    body = {"product_id": 1, "page_views": 100, "add_to_carts": 20, "conversions": 5}
    assert anon.post("/signals", json=body).status_code == 401
    assert anon.post("/signals", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    assert anon.post("/signals", json=body, headers={"X-API-Key": "test-ingest-key"}).status_code == 201
    assert client.post("/signals", json=body).status_code == 201                # admin login works too
    make_user(client, "ingestviewer")
    assert anon.post("/signals", json=body, headers=bearer(token_for(anon, "ingestviewer"))).status_code == 403
    # the key opens ingestion only - nothing else
    assert anon.get("/products", headers={"X-API-Key": "test-ingest-key"}).status_code == 401


# ------------------------------------------------------------ bootstrap & modes
def test_default_admin_bootstrap(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base
    from app.models import User

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[User.__table__])
    db = sessionmaker(bind=engine)()
    monkeypatch.setattr(security, "settings", dataclasses.replace(settings, admin_password="", password_hash_iterations=1000))
    warning = security.ensure_default_admin(db)
    admin = db.query(User).one()
    assert warning and "DEFAULT password" in warning
    assert admin.role == "admin" and admin.must_change_password is True
    assert security.verify_password(security.DEFAULT_ADMIN_PASSWORD, admin.password_hash)
    assert security.ensure_default_admin(db) is None and db.query(User).count() == 1     # idempotent


def test_auth_can_be_disabled_for_local_development(anon, monkeypatch):
    from app.routers import auth as auth_router

    off = dataclasses.replace(settings, auth_enabled=False)
    monkeypatch.setattr(security, "settings", off)
    monkeypatch.setattr(auth_router, "settings", off)
    assert anon.get("/products").status_code == 200
    assert anon.get("/auth/status").json() == {"auth_enabled": False, "default_credentials": False}
    me = anon.get("/auth/me")
    assert me.status_code == 200 and me.json()["role"] == "admin"
    assert anon.post("/auth/login", data={"username": "a", "password": "b"}).status_code in (400, 401)


def test_status_endpoint_reveals_nothing_when_password_was_set(anon):
    assert anon.get("/auth/status").json() == {"auth_enabled": True, "default_credentials": False,
                                               "hint_username": None, "hint_password": None}
