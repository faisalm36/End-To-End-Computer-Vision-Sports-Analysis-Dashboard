import jwt

from config import settings


def test_register_login_me(client):
    r = client.post("/api/auth/register", json={"first_name": "Ada", "last_name": "Lovelace",
                                                "email": "Ada@Example.com", "password": "correct-horse"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "ada@example.com" and "password_hash" not in body and "password" not in body

    r = client.post("/api/auth/login", json={"email": "ada@example.com", "password": "correct-horse"})
    assert r.status_code == 200
    tok = r.json()
    assert tok["token_type"] == "bearer" and tok["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    claims = jwt.decode(tok["access_token"], settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    assert claims["sub"] == str(body["user_id"])

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok['access_token']}"})
    assert me.status_code == 200 and me.json()["user_id"] == body["user_id"]


def test_duplicate_email_409(client):
    payload = {"first_name": "A", "last_name": "B", "email": "dup@example.com", "password": "password123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    payload["email"] = "DUP@example.com"
    assert client.post("/api/auth/register", json=payload).status_code == 409


def test_bad_login_401(client):
    assert client.post("/api/auth/login", json={"email": "ada@example.com", "password": "wrong-pass"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}).status_code == 401


def test_oauth2_form_token_for_docs(client):
    r = client.post("/api/auth/token", data={"username": "faisal@example.com", "password": "capstone123"})
    assert r.status_code == 200 and r.json()["access_token"]


def test_me_requires_valid_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401
    forged = jwt.encode({"sub": "1"}, "some-other-secret-at-least-32-bytes-long", algorithm="HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_register_validation(client):
    base = {"first_name": "A", "last_name": "B", "email": "short@example.com"}
    assert client.post("/api/auth/register", json={**base, "password": "short"}).status_code == 422
    assert client.post("/api/auth/register", json={**base, "password": "x" * 73}).status_code == 422
    assert client.post("/api/auth/register", json={**base, "email": "not-an-email", "password": "longenough"}).status_code == 422
