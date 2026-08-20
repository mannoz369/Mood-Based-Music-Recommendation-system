import cv2
import numpy as np


FACE_INPUT_SIZE = (64, 64)


def preprocess_face(face_bgr, target_size=FACE_INPUT_SIZE):
    if face_bgr is None or face_bgr.size == 0:
        raise ValueError("Face crop is empty.")

    gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, target_size, interpolation=cv2.INTER_AREA)
    normalized = resized.astype("float32") / 255.0

    return np.expand_dims(normalized, axis=(0, -1))
