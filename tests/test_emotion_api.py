import cv2
import numpy as np
from fastapi.testclient import TestClient

from services.emotion_api import main


class FakeEmotionService:
    face_detector_backend = "FakeFaceDetector"

    class EmotionDetector:
        labels = ("Angry", "Disgust", "Fear", "Happy", "Sad", "Surprise", "Neutral")
        input_size = (64, 64)

        class ModelPath:
            name = "fake-model.hdf5"

        model_path = ModelPath()

    emotion_detector = EmotionDetector()

    def __init__(self, result):
        self.result = result

    def metadata(self):
        return {
            "labels": list(self.emotion_detector.labels),
            "model": {
                "name": self.emotion_detector.model_path.name,
                "path": "fake-model.hdf5",
                "input_size": [64, 64],
            },
            "face_detector_backend": self.face_detector_backend,
        }

    def detect(self, image_bytes):
        return self.result


def _client_with_service(service):
    main.get_detection_service.cache_clear()
    main.app.dependency_overrides = {}
    main.get_detection_service = lambda: service
    return TestClient(main.app)


def _jpeg_bytes():
    image = np.full((20, 20, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def test_health_reports_loaded_model(monkeypatch):
    monkeypatch.setattr(main, "get_detection_service", lambda: FakeEmotionService({}))
    client = TestClient(main.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["model_available"] is True


def test_metadata_returns_labels_and_model(monkeypatch):
    monkeypatch.setattr(main, "get_detection_service", lambda: FakeEmotionService({}))
    client = TestClient(main.app)

    response = client.get("/emotion/metadata")

    assert response.status_code == 200
    body = response.json()
    assert body["labels"][3] == "Happy"
    assert body["model"]["name"] == "fake-model.hdf5"


def test_detect_returns_emotion_confidence_and_face(monkeypatch):
    service = FakeEmotionService(
        {
            "emotion": "Happy",
            "confidence": 0.87,
            "face": {"x": 1, "y": 2, "width": 3, "height": 4},
        }
    )
    monkeypatch.setattr(main, "get_detection_service", lambda: service)
    client = TestClient(main.app)

    response = client.post(
        "/emotion/detect",
        files={"file": ("face.jpg", _jpeg_bytes(), "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json() == service.result


def test_detect_returns_422_when_no_face(monkeypatch):
    monkeypatch.setattr(main, "get_detection_service", lambda: FakeEmotionService(None))
    client = TestClient(main.app)

    response = client.post(
        "/emotion/detect",
        files={"file": ("blank.jpg", _jpeg_bytes(), "image/jpeg")},
    )

    assert response.status_code == 422
    assert "No face" in response.json()["detail"]


def test_detect_rejects_non_image_upload(monkeypatch):
    monkeypatch.setattr(main, "get_detection_service", lambda: FakeEmotionService({}))
    client = TestClient(main.app)

    response = client.post(
        "/emotion/detect",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 415
