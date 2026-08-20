from dataclasses import replace

from fastapi.testclient import TestClient

from config import get_auth_settings
from services.auth import main
from services.auth.repository import DuplicateUserError
from services.auth.security import hash_password
from services.auth.service import AuthService


class InMemoryUserRepository:
    def __init__(self):
        self.users_by_email = {}
        self.users_by_id = {}
        self.next_id = 1
        self.ready = False

    async def ensure_indexes(self):
        self.ready = True

    async def health_check(self):
        return None

    async def create_user(self, email, password_hash):
        if email in self.users_by_email:
            raise DuplicateUserError("User already exists.")

        user = {
            "id": str(self.next_id),
            "email": email,
            "password_hash": password_hash,
        }
        self.next_id += 1
        self.users_by_email[email] = user
        self.users_by_id[user["id"]] = user
        return user

    async def find_by_email(self, email):
        return self.users_by_email.get(email)

    async def find_by_id(self, user_id):
        return self.users_by_id.get(user_id)


def _client(monkeypatch):
    repository = InMemoryUserRepository()
    settings = replace(
        get_auth_settings(),
        jwt_secret="test-secret",
        mongodb_uri="mongodb+srv://example.invalid",
    )
    service = AuthService(repository, settings)
    main.app.dependency_overrides = {}
    monkeypatch.setattr(main, "get_auth_service", lambda: service)
    return TestClient(main.app), repository


def test_signup_creates_user_and_returns_bearer_token(monkeypatch):
    client, repository = _client(monkeypatch)

    response = client.post(
        "/auth/signup",
        json={"email": "USER@example.com", "password": "good-password"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "user@example.com"
    stored = repository.users_by_email["user@example.com"]
    assert stored["password_hash"] != "good-password"
    assert stored["password_hash"].startswith("pbkdf2_sha256$")


def test_signup_rejects_duplicate_email(monkeypatch):
    client, _repository = _client(monkeypatch)

    first = client.post(
        "/auth/signup",
        json={"email": "user@example.com", "password": "good-password"},
    )
    second = client.post(
        "/auth/signup",
        json={"email": "user@example.com", "password": "good-password"},
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_login_returns_token_for_valid_password(monkeypatch):
    client, repository = _client(monkeypatch)
    repository.users_by_email["user@example.com"] = {
        "id": "1",
        "email": "user@example.com",
        "password_hash": hash_password("good-password"),
    }
    repository.users_by_id["1"] = repository.users_by_email["user@example.com"]

    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "good-password"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_rejects_invalid_password(monkeypatch):
    client, repository = _client(monkeypatch)
    repository.users_by_email["user@example.com"] = {
        "id": "1",
        "email": "user@example.com",
        "password_hash": hash_password("good-password"),
    }

    response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "bad-password"},
    )

    assert response.status_code == 401


def test_me_requires_valid_bearer_token(monkeypatch):
    client, _repository = _client(monkeypatch)
    signup = client.post(
        "/auth/signup",
        json={"email": "user@example.com", "password": "good-password"},
    )
    token = signup.json()["access_token"]

    missing = client.get("/auth/me")
    present = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert missing.status_code == 401
    assert present.status_code == 200
    assert present.json()["user"]["email"] == "user@example.com"
