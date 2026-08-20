from dataclasses import dataclass

import cv2
import numpy as np

from config import EmotionApiSettings
from detection.emotion_detector import EmotionDetector
from detection.face_detector import FaceDetector


@dataclass(frozen=True)
class FaceBox:
    x: int
    y: int
    width: int
    height: int

    @classmethod
    def from_tuple(cls, face):
        x, y, width, height = face
        return cls(x=x, y=y, width=width, height=height)

    def to_dict(self):
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


class EmotionDetectionService:
    def __init__(self, settings: EmotionApiSettings):
        self.settings = settings
        self.face_detector = FaceDetector(
            min_detection_confidence=settings.min_detection_confidence
        )
        self.emotion_detector = EmotionDetector(model_path=settings.model_path)

    @property
    def face_detector_backend(self):
        return type(self.face_detector.detector).__name__

    def metadata(self):
        return {
            "labels": list(self.emotion_detector.labels),
            "model": {
                "name": self.emotion_detector.model_path.name,
                "path": str(self.emotion_detector.model_path),
                "input_size": list(self.emotion_detector.input_size),
            },
            "face_detector_backend": self.face_detector_backend,
        }

    def detect(self, image_bytes):
        frame = self._decode_image(image_bytes)
        face = self.face_detector.get_primary_face(frame)

        if face is None:
            return None

        x, y, width, height = face
        face_crop = frame[y : y + height, x : x + width]
        emotion, confidence = self.emotion_detector.predict(face_crop)

        return {
            "emotion": emotion,
            "confidence": confidence,
            "face": FaceBox.from_tuple(face).to_dict(),
        }

    def _decode_image(self, image_bytes):
        if not image_bytes:
            raise ValueError("Image upload is empty.")

        encoded = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)

        if frame is None:
            raise ValueError("Uploaded file is not a readable image.")

        return frame
