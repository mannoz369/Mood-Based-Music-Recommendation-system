from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import get_auth_settings
from services.auth.repository import DuplicateUserError, MongoUserRepository
from services.auth.service import AuthService, AuthenticationError


app = FastAPI(
    title="Emotion Music Auth Service",
    version="0.1.0",
    description="Email/password auth service backed by MongoDB Atlas.",
)

settings = get_auth_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class Credentials(BaseModel):
    email: str
    password: str


@lru_cache(maxsize=1)
def get_auth_service():
    service_settings = get_auth_settings()
    return AuthService(MongoUserRepository(service_settings), service_settings)


async def current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )

    token = authorization.split(" ", 1)[1].strip()

    try:
        return await get_auth_service().authenticate_token(token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@app.get("/health")
async def health():
    auth_settings = get_auth_settings()

    if not auth_settings.mongodb_uri:
        return {
            "status": "degraded",
            "service": auth_settings.service_name,
            "database": "unconfigured",
            "detail": "MONGODB_URI is not configured.",
        }

    try:
        service = get_auth_service()
        await service.ensure_ready()
        await service.health_check()
    except Exception as exc:
        return {
            "status": "degraded",
            "service": auth_settings.service_name,
            "database": "unavailable",
            "detail": str(exc),
        }

    return {
        "status": "ok",
        "service": auth_settings.service_name,
        "database": auth_settings.mongodb_database,
    }


@app.post("/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(credentials: Credentials):
    try:
        await get_auth_service().ensure_ready()
        return await get_auth_service().signup(credentials.email, credentials.password)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except DuplicateUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@app.post("/auth/login")
async def login(credentials: Credentials):
    try:
        return await get_auth_service().login(credentials.email, credentials.password)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@app.get("/auth/me")
async def me(user=Depends(current_user)):
    return {"user": user}
