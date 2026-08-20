from services.auth.repository import DuplicateUserError
from services.auth.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    normalize_email,
    validate_password,
    verify_password,
)


class AuthenticationError(ValueError):
    pass


class AuthService:
    def __init__(self, repository, settings):
        self.repository = repository
        self.settings = settings

    async def ensure_ready(self):
        await self.repository.ensure_indexes()

    async def health_check(self):
        await self.repository.health_check()

    async def signup(self, email, password):
        email = normalize_email(email)
        validate_password(password)

        existing = await self.repository.find_by_email(email)

        if existing:
            raise DuplicateUserError("User already exists.")

        user = await self.repository.create_user(email, hash_password(password))
        return self._token_response(user)

    async def login(self, email, password):
        email = normalize_email(email)
        user = await self.repository.find_by_email(email)

        if not user or not verify_password(password, user["password_hash"]):
            raise AuthenticationError("Invalid email or password.")

        return self._token_response(user)

    async def authenticate_token(self, token):
        try:
            payload = decode_access_token(token, self.settings)
        except TokenError as exc:
            raise AuthenticationError(str(exc)) from exc

        user = await self.repository.find_by_id(payload["sub"])

        if not user:
            raise AuthenticationError("User no longer exists.")

        return self._public_user(user)

    def _token_response(self, user):
        return {
            "access_token": create_access_token(user, self.settings),
            "token_type": "bearer",
            "expires_in": self.settings.jwt_expires_minutes * 60,
            "user": self._public_user(user),
        }

    def _public_user(self, user):
        return {
            "id": user["id"],
            "email": user["email"],
        }
