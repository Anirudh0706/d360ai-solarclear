"""Registration, login, authentication and role-based authorization."""


def test_login_valid_credentials(client):
    res = client.post("/api/auth/login", json={"email": "engineer@solarclear.local", "password": "Engineer@123"})
    assert res.status_code == 200
    assert res.json()["user"]["role"] == "engineer"
    assert res.json()["token"]


def test_login_invalid_password(client):
    res = client.post("/api/auth/login", json={"email": "engineer@solarclear.local", "password": "wrong-pass1"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password"


def test_login_unknown_email(client):
    res = client.post("/api/auth/login", json={"email": "nobody@x.com", "password": "whatever1"})
    assert res.status_code == 401


def test_register_and_use_token(client):
    res = client.post("/api/auth/register", json={"name": "New Engineer", "email": "New@Example.com", "password": "solar2026"})
    assert res.status_code == 201
    body = res.json()
    assert body["user"]["email"] == "new@example.com"  # normalised
    assert body["user"]["role"] == "engineer"          # self-registration never grants admin
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200 and me.json()["name"] == "New Engineer"


def test_register_duplicate_email(client):
    res = client.post("/api/auth/register", json={"name": "Dup", "email": "engineer@solarclear.local", "password": "solar2026"})
    assert res.status_code == 409


def test_register_validation(client):
    weak = client.post("/api/auth/register", json={"name": "W", "email": "w@x.com", "password": "short"})
    assert weak.status_code == 422
    no_digit = client.post("/api/auth/register", json={"name": "Weak", "email": "w@x.com", "password": "onlyletters"})
    assert no_digit.status_code == 422
    bad_email = client.post("/api/auth/register", json={"name": "Bad", "email": "not-an-email", "password": "solar2026"})
    assert bad_email.status_code == 422


def test_protected_route_requires_token(client):
    assert client.get("/api/analytics/overview").status_code == 401


def test_tampered_token_rejected(client, engineer):
    token = engineer["Authorization"].split()[1]
    forged = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_engineer_cannot_modify_assets(client, engineer):
    res = client.post("/api/feeders", headers=engineer,
                      json={"substation_id": 1, "code": "FDR-X1", "name": "Blocked", "rating_kva": 1000})
    assert res.status_code == 403
