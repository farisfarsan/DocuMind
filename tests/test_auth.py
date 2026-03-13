"""
test_auth.py — tests for /auth/register and /auth/login

Your router returns:
  register → 201  { "message": "Account created", "username": "..." }
  login    → 200  { "access_token": "...", "token_type": "bearer" }
"""

import pytest
from tests.conftest import TEST_USER, TEST_USER_2


class TestRegister:

    def test_register_success(self, client):
        """New user registers — gets 201 with username in response."""
        resp = client.post("/auth/register", json=TEST_USER)
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == TEST_USER["username"]
        assert "message" in data

    def test_register_never_returns_password(self, client):
        """Password or hash must never appear in the response."""
        resp = client.post("/auth/register", json=TEST_USER)
        data = resp.json()
        assert "password"  not in data
        assert "hashed_pw" not in data

    def test_register_duplicate_email(self, client, registered_user):
        """Same email → 400 'Email already registered'."""
        resp = client.post("/auth/register", json={
            **TEST_USER,
            "username": "completely_different_username",
        })
        assert resp.status_code == 400
        assert "email" in resp.json()["detail"].lower()

    def test_register_duplicate_username(self, client, registered_user):
        """Same username → 400 'Username already taken'."""
        resp = client.post("/auth/register", json={
            **TEST_USER,
            "email": "totally_different@email.com",
        })
        assert resp.status_code == 400
        assert "username" in resp.json()["detail"].lower()

    def test_register_missing_email(self, client):
        """Missing email field → 422 validation error."""
        resp = client.post("/auth/register", json={
            "username": "noEmail",
            "password": "SomePass123!",
        })
        assert resp.status_code == 422

    def test_register_missing_password(self, client):
        """Missing password field → 422 validation error."""
        resp = client.post("/auth/register", json={
            "email": "test@test.com",
            "username": "noPassword",
        })
        assert resp.status_code == 422

    def test_register_invalid_email_format(self, client):
        """Malformed email → 422 (Pydantic EmailStr rejects it)."""
        resp = client.post("/auth/register", json={
            **TEST_USER,
            "email": "not-an-email",
        })
        assert resp.status_code == 422

    def test_register_empty_body(self, client):
        """Empty body → 422."""
        resp = client.post("/auth/register", json={})
        assert resp.status_code == 422


class TestLogin:

    def test_login_success(self, client, registered_user):
        """Correct credentials → 200 with access_token."""
        resp = client.post("/auth/login", data={
            "username": TEST_USER["username"],
            "password": TEST_USER["password"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_token_is_nonempty(self, client, registered_user):
        """Token must be a real non-trivial string."""
        resp = client.post("/auth/login", data={
            "username": TEST_USER["username"],
            "password": TEST_USER["password"],
        })
        assert len(resp.json()["access_token"]) > 20

    def test_login_wrong_password(self, client, registered_user):
        """Wrong password → 401."""
        resp = client.post("/auth/login", data={
            "username": TEST_USER["username"],
            "password": "TotallyWrongPassword!",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        """User that was never registered → 401."""
        resp = client.post("/auth/login", data={
            "username": "ghost_user_xyz",
            "password": "AnyPassword123!",
        })
        assert resp.status_code == 401

    def test_login_missing_username(self, client):
        """Missing username field → 422."""
        resp = client.post("/auth/login", data={"password": "pass"})
        assert resp.status_code == 422

    def test_login_missing_password(self, client):
        """Missing password field → 422."""
        resp = client.post("/auth/login", data={"username": "user"})
        assert resp.status_code == 422

    def test_two_users_get_different_tokens(self, client, registered_user):
        """Two different users must get different JWT tokens."""
        client.post("/auth/register", json=TEST_USER_2)

        resp1 = client.post("/auth/login", data={
            "username": TEST_USER["username"],
            "password": TEST_USER["password"],
        })
        resp2 = client.post("/auth/login", data={
            "username": TEST_USER_2["username"],
            "password": TEST_USER_2["password"],
        })
        assert resp1.json()["access_token"] != resp2.json()["access_token"]


class TestProtectedRoutes:

    def test_valid_token_grants_access(self, client, auth_headers):
        """Valid JWT → 200 on protected route."""
        resp = client.get("/documents/", headers=auth_headers)
        assert resp.status_code == 200

    def test_no_token_denied(self, client):
        """No Authorization header → 401."""
        resp = client.get("/documents/")
        assert resp.status_code == 401

    def test_garbage_token_denied(self, client):
        """Random string as token → 401."""
        resp = client.get("/documents/", headers={
            "Authorization": "Bearer this.is.garbage"
        })
        assert resp.status_code == 401

    def test_malformed_auth_header(self, client):
        """Missing 'Bearer' prefix → 401."""
        resp = client.get("/documents/", headers={
            "Authorization": "NotBearer sometoken"
        })
        assert resp.status_code == 401