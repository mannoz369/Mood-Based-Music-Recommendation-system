class MongoAnalyticsRepository:
    def __init__(self, settings):
        if not settings.mongodb_uri:
            raise RuntimeError("MONGODB_URI is not configured.")

        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            from pymongo import ASCENDING, DESCENDING
        except ImportError as exc:
            raise RuntimeError(
                "MongoDB dependencies are not installed. Run "
                "`python -m pip install -r requirements.txt`."
            ) from exc

        self._ascending = ASCENDING
        self._descending = DESCENDING
        self.client = AsyncIOMotorClient(settings.mongodb_uri)
        self.database = self.client[settings.mongodb_database]
        self.events = self.database[settings.events_collection]
        self.mood_timeline = self.database[settings.mood_timeline_collection]
        self.recommendation_history = self.database[
            settings.recommendation_history_collection
        ]
        self.playback_history = self.database[settings.playback_history_collection]

    async def ensure_indexes(self):
        await self.events.create_index(
            [("event_id", self._ascending)],
            unique=True,
            name="unique_event_id",
        )
        await self.events.create_index(
            [("event_type", self._ascending), ("occurred_at", self._descending)],
            name="event_type_time",
        )
        await self.mood_timeline.create_index(
            [("user_id", self._ascending), ("occurred_at", self._descending)],
            name="user_mood_time",
        )
        await self.recommendation_history.create_index(
            [("user_id", self._ascending), ("occurred_at", self._descending)],
            name="user_recommendation_time",
        )
        await self.playback_history.create_index(
            [("user_id", self._ascending), ("occurred_at", self._descending)],
            name="user_playback_time",
        )

    async def health_check(self):
        await self.database.command("ping")

    async def store_event(self, document):
        await self.events.update_one(
            {"event_id": document["event_id"]},
            {"$setOnInsert": document},
            upsert=True,
        )
        return document

    async def store_mood_timeline(self, document):
        await self.mood_timeline.insert_one(document)
        return document

    async def store_recommendation_history(self, document):
        await self.recommendation_history.insert_one(document)
        return document

    async def store_playback_history(self, document):
        await self.playback_history.insert_one(document)
        return document

    async def list_moods(self, user_id, limit=50):
        return await self._list_user_documents(self.mood_timeline, user_id, limit)

    async def list_recommendations(self, user_id, limit=50):
        return await self._list_user_documents(
            self.recommendation_history,
            user_id,
            limit,
        )

    async def list_playback(self, user_id, limit=50):
        return await self._list_user_documents(self.playback_history, user_id, limit)

    async def _list_user_documents(self, collection, user_id, limit):
        cursor = (
            collection.find({"user_id": user_id}, {"_id": False})
            .sort("occurred_at", self._descending)
            .limit(max(1, min(int(limit), 200)))
        )
        return await cursor.to_list(length=max(1, min(int(limit), 200)))
