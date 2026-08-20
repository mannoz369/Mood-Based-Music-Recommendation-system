import importlib

import numpy as np


def test_core_modules_import_without_starting_camera():
    modules = [
        "app",
        "utils.labels",
        "utils.preprocessing",
        "detection.face_detector",
        "detection.emotion_detector",
    ]

    for module in modules:
        assert importlib.import_module(module)


def test_face_detector_primary_face_selects_largest(monkeypatch):
    from detection.face_detector import FaceDetector

    class StubDetector:
        def process(self, frame):
            return [(0, 0, 10, 10), (5, 5, 20, 15)]

    monkeypatch.setattr(
        FaceDetector,
        "_create_detector",
        lambda self, min_detection_confidence: StubDetector(),
    )

    detector = FaceDetector()
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    assert detector.get_primary_face(frame) == (5, 5, 20, 15)
