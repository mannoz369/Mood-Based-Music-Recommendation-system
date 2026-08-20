import argparse
import os
import sys
from pathlib import Path


def _configure_process_environment():
    defaults = {
        "OPENCV_LOG_LEVEL": "SILENT",
        "TF_ENABLE_ONEDNN_OPTS": "0",
    }

    changed = False

    for name, value in defaults.items():
        if name not in os.environ:
            os.environ[name] = value
            changed = True

    return changed


def _relaunch_with_project_venv():
    if not sys.argv or Path(sys.argv[0]).name != Path(__file__).name:
        return

    env_changed = _configure_process_environment()
    project_root = Path(__file__).resolve().parent
    venv_python = project_root / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )

    target_python = venv_python if venv_python.exists() else Path(sys.executable)
    target_python = target_python.resolve()

    current_python = Path(sys.executable).resolve()

    if current_python == target_python and not env_changed:
        return

    process_args = [str(target_python), *sys.argv]

    if os.name == "nt":
        raise SystemExit(os.spawnv(os.P_WAIT, str(target_python), process_args))

    os.execv(str(target_python), process_args)


def _parse_args():
    parser = argparse.ArgumentParser(description="Run the Emotion AI webcam app.")
    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="OpenCV camera index to use.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1280,
        help="Requested webcam capture width.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=720,
        help="Requested webcam capture height.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify imports and exit without opening the webcam.",
    )

    return parser.parse_args()


def _load_camera_dependencies():
    try:
        import cv2
        from camera.webcam import Webcam
    except ModuleNotFoundError as exc:
        if exc.name == "cv2":
            raise SystemExit(
                "OpenCV is not installed for this Python environment. "
                "Run `python -m pip install -r requirements.txt`, or run the "
                "app from the project virtual environment at `.venv`."
            ) from exc

        raise

    return cv2, Webcam


def _load_face_detector():
    try:
        from detection.face_detector import FaceDetector
    except ModuleNotFoundError as exc:
        if exc.name != "mediapipe":
            raise

        raise SystemExit(
            "MediaPipe is not installed for this Python environment. "
            "Run `python -m pip install -r requirements.txt`, or run the app "
            "from the project virtual environment at `.venv`."
        ) from exc

    return FaceDetector


def _load_emotion_detector():
    try:
        from detection.emotion_detector import EmotionDetector
    except ModuleNotFoundError as exc:
        if exc.name not in {"tensorflow", "keras"}:
            raise

        raise SystemExit(
            "TensorFlow/Keras is not installed for this Python environment. "
            "Run `python -m pip install -r requirements.txt`, or run the app "
            "from the project virtual environment at `.venv`."
        ) from exc

    return EmotionDetector


def _crop_face(frame, face):
    x, y, w, h = face
    return frame[y : y + h, x : x + w]


def _draw_face_prediction(cv2, frame, face, emotion=None, confidence=None):
    x, y, w, h = face

    cv2.rectangle(
        frame,
        (x, y),
        (x + w, y + h),
        (0, 255, 0),
        2,
    )

    if emotion is None or confidence is None:
        label = "Primary Face"
    else:
        label = f"Emotion: {emotion}"
        confidence_label = f"Confidence: {confidence * 100:.2f}%"
        confidence_y = max(20, y - 10)
        emotion_y = max(20, confidence_y - 25)

        cv2.putText(
            frame,
            confidence_label,
            (x, confidence_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            frame,
            label,
            (x, emotion_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )
        return

    cv2.putText(
        frame,
        label,
        (x, max(20, y - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0),
        2,
    )


def main():
    _configure_process_environment()
    args = _parse_args()
    cv2, Webcam = _load_camera_dependencies()

    if args.check:
        FaceDetector = _load_face_detector()
        EmotionDetector = _load_emotion_detector()
        face_detector = FaceDetector()
        emotion_detector = EmotionDetector()
        detector_backend = type(face_detector.detector).__name__
        print(
            f"Startup check passed. OpenCV {cv2.__version__} is available. "
            f"Face detector backend: {detector_backend}. "
            f"Emotion model: {emotion_detector.model_path.name}."
        )
        return

    try:
        camera = Webcam(
            camera_index=args.camera_index,
            width=args.width,
            height=args.height,
        )
    except RuntimeError as exc:
        raise SystemExit(
            f"{exc} Check that the camera is connected, not already in use, "
            "and try another index with `python app.py --camera-index 1`."
        ) from exc

    FaceDetector = _load_face_detector()
    EmotionDetector = _load_emotion_detector()
    face_detector = FaceDetector()
    emotion_detector = EmotionDetector()

    try:
        while True:
            frame = camera.read()

            if frame is None:
                break

            face = face_detector.get_primary_face(frame)

            if face is not None:
                face_crop = _crop_face(frame, face)
                emotion, confidence = emotion_detector.predict(face_crop)
                _draw_face_prediction(cv2, frame, face, emotion, confidence)

            cv2.imshow("Emotion AI", frame)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    _relaunch_with_project_venv()
    main()
