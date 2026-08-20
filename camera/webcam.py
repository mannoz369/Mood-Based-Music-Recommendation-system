import cv2


def _open_capture(camera_index):
    logging = getattr(getattr(cv2, "utils", None), "logging", None)

    if logging is None:
        return cv2.VideoCapture(camera_index)

    previous_level = logging.getLogLevel()

    try:
        logging.setLogLevel(logging.LOG_LEVEL_SILENT)
        return cv2.VideoCapture(camera_index)
    finally:
        logging.setLogLevel(previous_level)


class Webcam:
    def __init__(self, camera_index=0, width=1280, height=720):
        self.cap = _open_capture(camera_index)

        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open webcam at index {camera_index}.")

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def read(self):
        ret, frame = self.cap.read()

        if not ret:
            return None

        return frame

    def release(self):
        self.cap.release()
