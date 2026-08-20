import httpx


class JamendoError(RuntimeError):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class JamendoClient:
    def __init__(self, settings):
        self.settings = settings

    async def search_tracks(self, query, limit, language=None):
        if not self.settings.jamendo_client_id:
            raise JamendoError(503, "JAMENDO_CLIENT_ID is not configured.")

        print(query, flush=True)
        params = {
            "client_id": self.settings.jamendo_client_id,
            "format": "json",
            "limit": limit,
            "search": query,
            "include": "musicinfo",
            "groupby": "artist_id",
            "audioformat": "mp32",
            "imagesize": 300,
            "order": "relevance",
        }

        if language:
            params["lang"] = language

        async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
            response = await client.get(
                f"{self.settings.jamendo_api_base_url}/tracks/",
                params=params,
            )

        if response.status_code >= 400:
            raise JamendoError(response.status_code, response.text)

        payload = response.json()
        headers = payload.get("headers", {})

        if headers.get("status") == "failed":
            raise JamendoError(headers.get("code", 502), headers.get("error_message", "Jamendo request failed."))

        return [self._track_summary(track) for track in payload.get("results", [])]

    def _track_summary(self, track):
        return {
            "id": str(track.get("id")),
            "name": track.get("name"),
            "artists": [track.get("artist_name")] if track.get("artist_name") else [],
            "artist": track.get("artist_name"),
            "uri": track.get("audio"),
            "audio_url": track.get("audio"),
            "preview_url": track.get("audio"),
            "external_url": track.get("shareurl"),
            "album": track.get("album_name"),
            "artwork": track.get("album_image") or track.get("image"),
            "duration": track.get("duration"),
            "license": track.get("license_ccurl"),
            "provider": "jamendo",
        }
