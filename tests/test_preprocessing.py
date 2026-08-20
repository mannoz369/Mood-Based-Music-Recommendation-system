import numpy as np
import pytest

from utils.preprocessing import FACE_INPUT_SIZE, preprocess_face


def test_preprocess_face_returns_model_compatible_shape_and_range():
    face = np.full((80, 120, 3), 127, dtype=np.uint8)

    processed = preprocess_face(face)

    assert processed.shape == (1, FACE_INPUT_SIZE[1], FACE_INPUT_SIZE[0], 1)
    assert processed.dtype == np.float32
    assert processed.min() >= 0.0
    assert processed.max() <= 1.0


def test_preprocess_face_rejects_empty_crop():
    with pytest.raises(ValueError, match="Face crop is empty"):
        preprocess_face(np.empty((0, 0, 3), dtype=np.uint8))
