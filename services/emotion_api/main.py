from functools import lru_cache

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from app import _configure_process_environment
from config import get_emotion_api_settings
from services.emotion_api.detection_service import EmotionDetectionService


_configure_process_environment()

app = FastAPI(
    title="Emotion API",
    version="0.1.0",
    description="HTTP wrapper around the local webcam emotion detection core.",
)

settings = get_emotion_api_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def get_detection_service():
    return EmotionDetectionService(get_emotion_api_settings())


def _service_or_503():
    try:
        return get_detection_service()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Emotion service is unavailable: {exc}",
        ) from exc


@app.get("/health")
def health():
    settings = get_emotion_api_settings()

    try:
        service = get_detection_service()
    except Exception as exc:
        return {
            "status": "degraded",
            "service": settings.service_name,
            "model_available": False,
            "detail": str(exc),
        }

    return {
        "status": "ok",
        "service": settings.service_name,
        "model_available": True,
        "face_detector_backend": service.face_detector_backend,
        "model": service.emotion_detector.model_path.name,
    }


@app.get("/emotion/metadata")
def emotion_metadata():
    return _service_or_503().metadata()


@app.post("/emotion/detect")
async def detect_emotion(file: UploadFile = File(...)):
    settings = get_emotion_api_settings()

    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload must be an image file.",
        )

    image_bytes = await file.read()

    if len(image_bytes) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image upload is too large.",
        )

    try:
        result = _service_or_503().detect(image_bytes)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No face was detected in the uploaded image.",
        )

    return result
