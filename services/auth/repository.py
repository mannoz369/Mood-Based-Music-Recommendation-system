from datetime import datetime, timezone


class DuplicateUserError(ValueError):
    pass


def _serialize_user(document):
    if document is None:
        return None

    return {
        "id": str(document["_id"]),
        "email": document["email"],
        "password_hash": document["password_hash"],
        "created_at": document.get("created_at"),
    }


class MongoUserRepository:
    def __init__(self, settings):
        if not settings.mongodb_uri:
            raise RuntimeError("MONGODB_URI is not configured.")

        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            from pymongo import ASCENDING
        except ImportError as exc:
            raise RuntimeError(
                "MongoDB dependencies are not installed. Run "
                "`python -m pip install -r requirements.txt`."
            ) from exc

        self._ascending = ASCENDING
        self.client = AsyncIOMotorClient(settings.mongodb_uri)
        self.database = self.client[settings.mongodb_database]
        self.collection = self.database[settings.users_collection]

    async def ensure_indexes(self):
        await self.collection.create_index(
            [("email", self._ascending)],
            unique=True,
            name="unique_user_email",
        )

    async def health_check(self):
        await self.database.command("ping")

    async def create_user(self, email, password_hash):
        now = datetime.now(timezone.utc)
        document = {
            "email": email,
            "password_hash": password_hash,
            "created_at": now,
            "updated_at": now,
        }

        try:
            result = await self.collection.insert_one(document)
        except Exception as exc:
            if exc.__class__.__name__ == "DuplicateKeyError":
                raise DuplicateUserError("User already exists.") from exc

            raise

        document["_id"] = result.inserted_id
        return _serialize_user(document)

    async def find_by_email(self, email):
        return _serialize_user(await self.collection.find_one({"email": email}))

    async def find_by_id(self, user_id):
        try:
            from bson import ObjectId
        except ImportError as exc:
            raise RuntimeError("MongoDB dependencies are not installed.") from exc

        if not ObjectId.is_valid(user_id):
            return None

        return _serialize_user(await self.collection.find_one({"_id": ObjectId(user_id)}))
