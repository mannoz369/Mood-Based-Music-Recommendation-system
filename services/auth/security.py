import base64
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HASH_ALGORITHM = "pbkdf2_sha256"
HASH_ITERATIONS = 210_000


class TokenError(ValueError):
    pass


def normalize_email(email):
    value = email.strip().lower()

    if not EMAIL_RE.match(value):
        raise ValueError("Enter a valid email address.")

    return value


def validate_password(password):
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")


def hash_password(password):
    validate_password(password)
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        HASH_ITERATIONS,
    ).hex()
    return f"{HASH_ALGORITHM}${HASH_ITERATIONS}${salt}${digest}"


def verify_password(password, password_hash):
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != HASH_ALGORITHM:
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    ).hex()

    return hmac.compare_digest(digest, expected)


def _b64encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value):
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def create_access_token(user, settings, now=None):
    now = now or datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.jwt_expires_minutes)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": settings.jwt_issuer,
        "sub": str(user["id"]),
        "email": user["email"],
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    signing_input = ".".join(
        [
            _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()

    return f"{signing_input}.{_b64encode(signature)}"


def decode_access_token(token, settings, now=None):
    now = now or datetime.now(timezone.utc)

    try:
        header_segment, payload_segment, signature_segment = token.split(".", 2)
    except ValueError as exc:
        raise TokenError("Token is malformed.") from exc

    signing_input = f"{header_segment}.{payload_segment}"
    expected = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(_b64encode(expected), signature_segment):
        raise TokenError("Token signature is invalid.")

    try:
        header = json.loads(_b64decode(header_segment))
        payload = json.loads(_b64decode(payload_segment))
    except (json.JSONDecodeError, ValueError) as exc:
        raise TokenError("Token payload is invalid.") from exc

    if header.get("alg") != "HS256":
        raise TokenError("Token algorithm is invalid.")

    if payload.get("iss") != settings.jwt_issuer:
        raise TokenError("Token issuer is invalid.")

    if int(payload.get("exp", 0)) < int(now.timestamp()):
        raise TokenError("Token has expired.")

    return payload
