import numpy as np
import pytest

from detection.emotion_detector import EmotionDetector


class FakeModel:
    input_shape = (None, 64, 64, 1)

    def predict(self, batch, verbose=0):
        assert batch.shape == (1, 64, 64, 1)
        assert verbose == 0
        return np.array([[0.01, 0.02, 0.03, 0.91, 0.01, 0.01, 0.01]])


class ExtraClassFakeModel:
    input_shape = (None, 64, 64, 1)

    def predict(self, batch, verbose=0):
        return np.array([[0.0, 1.0]])


def test_emotion_detector_predict_uses_labels_and_confidence(tmp_path):
    model_path = tmp_path / "model.hdf5"
    model_path.write_bytes(b"fake")

    detector = EmotionDetector.__new__(EmotionDetector)
    detector.model_path = model_path
    detector.labels = (
        "Angry",
        "Disgust",
        "Fear",
        "Happy",
        "Sad",
        "Surprise",
        "Neutral",
    )
    detector.model = FakeModel()
    detector.input_size = detector._resolve_input_size()

    emotion, confidence = detector.predict(np.full((90, 90, 3), 255, dtype=np.uint8))

    assert emotion == "Happy"
    assert confidence == pytest.approx(0.91)


def test_emotion_detector_rejects_model_outputs_without_labels(tmp_path):
    model_path = tmp_path / "model.hdf5"
    model_path.write_bytes(b"fake")

    detector = EmotionDetector.__new__(EmotionDetector)
    detector.model_path = model_path
    detector.labels = ("OnlyOne",)
    detector.model = ExtraClassFakeModel()
    detector.input_size = detector._resolve_input_size()

    with pytest.raises(ValueError, match="more classes than configured labels"):
        detector.predict(np.full((90, 90, 3), 255, dtype=np.uint8))
