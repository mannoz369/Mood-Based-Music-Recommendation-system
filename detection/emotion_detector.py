from pathlib import Path
import sys

import numpy as np

from utils.labels import EMOTION_LABELS
from utils.preprocessing import FACE_INPUT_SIZE, preprocess_face


DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parents[1]
    / "models"
    / "fer2013_mini_XCEPTION.102-0.66.hdf5"
)


class EmotionDetector:
    def __init__(self, model_path=DEFAULT_MODEL_PATH, labels=EMOTION_LABELS):
        self.model_path = Path(model_path)
        self.labels = tuple(labels)

        if not self.model_path.exists():
            raise FileNotFoundError(f"Emotion model not found: {self.model_path}")

        self.model = self._load_model()
        self.input_size = self._resolve_input_size()

    def _load_model(self):
        try:
            # TensorFlow imports optional JAX support when JAX is installed.
            # This app does not use JAX, and incompatible JAX wheels can break
            # TensorFlow import before the emotion model is loaded.
            sys.modules.setdefault("jax", None)
            from tensorflow.keras.models import load_model
        except ImportError as exc:
            raise RuntimeError(
                "TensorFlow/Keras could not be imported. Reinstall the project "
                "dependencies with `python -m pip install -r requirements.txt`."
            ) from exc

        return load_model(self.model_path, compile=False)

    def _resolve_input_size(self):
        input_shape = self.model.input_shape

        if isinstance(input_shape, list):
            input_shape = input_shape[0]

        if len(input_shape) != 4 or input_shape[1] is None or input_shape[2] is None:
            return FACE_INPUT_SIZE

        return int(input_shape[2]), int(input_shape[1])

    def predict_probabilities(self, face_crop):
        processed_face = preprocess_face(face_crop, target_size=self.input_size)
        probabilities = self.model.predict(processed_face, verbose=0)[0]
        return np.asarray(probabilities, dtype="float32")

    def predict(self, face_crop):
        probabilities = self.predict_probabilities(face_crop)

        predicted_index = int(np.argmax(probabilities))

        if predicted_index >= len(self.labels):
            raise ValueError(
                "Emotion model output has more classes than configured labels."
            )

        emotion = self.labels[predicted_index]
        confidence = float(probabilities[predicted_index])

        return emotion, confidence
