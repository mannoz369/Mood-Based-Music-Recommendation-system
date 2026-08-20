import cv2


class _OpenCvFaceDetector:
    def __init__(self, min_detection_confidence):
        if not hasattr(cv2, "CascadeClassifier"):
            raise RuntimeError("This OpenCV build does not include CascadeClassifier.")

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.detector = cv2.CascadeClassifier(cascade_path)

        if self.detector.empty():
            raise RuntimeError(f"Could not load OpenCV face cascade: {cascade_path}")

        # Haar cascades do not expose confidence in the same way MediaPipe does.
        self.min_detection_confidence = min_detection_confidence

    def process(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)

        detections = self.detector.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(40, 40),
        )

        return [(int(x), int(y), int(w), int(h)) for x, y, w, h in detections]


class _NoOpFaceDetector:
    def process(self, frame):
        return []


class _MediaPipeSolutionsFaceDetector:
    def __init__(self, mp_face_detection, min_detection_confidence):
        self.detector = mp_face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=min_detection_confidence,
        )

    def process(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.detector.process(rgb)
        faces = []

        if not results.detections:
            return faces

        image_height, image_width, _ = frame.shape

        for detection in results.detections:
            bbox = detection.location_data.relative_bounding_box

            x = int(bbox.xmin * image_width)
            y = int(bbox.ymin * image_height)
            w = int(bbox.width * image_width)
            h = int(bbox.height * image_height)

            x = max(0, x)
            y = max(0, y)
            w = min(w, image_width - x)
            h = min(h, image_height - y)

            faces.append((x, y, w, h))

        return faces


class FaceDetector:
    def __init__(self, min_detection_confidence=0.6):
        """
        Initializes the best available face detector.
        """

        self.detector = self._create_detector(min_detection_confidence)

    def _create_detector(self, min_detection_confidence):
        opencv_detector = self._create_opencv_detector(
            min_detection_confidence,
            quiet=True,
        )

        if opencv_detector is not None:
            return opencv_detector

        try:
            import mediapipe as mp
        except (ImportError, ModuleNotFoundError) as exc:
            print(
                "Face detection is disabled: OpenCV does not include the "
                f"fallback cascade detector, and MediaPipe could not load. "
                f"Details: {exc}"
            )
            return _NoOpFaceDetector()

        mp_solutions = getattr(mp, "solutions", None)

        if mp_solutions is None or not hasattr(mp_solutions, "face_detection"):
            return self._create_opencv_detector(min_detection_confidence)

        return _MediaPipeSolutionsFaceDetector(
            mp_solutions.face_detection,
            min_detection_confidence,
        )

    def _create_opencv_detector(self, min_detection_confidence, quiet=False):
        try:
            return _OpenCvFaceDetector(min_detection_confidence)
        except RuntimeError as exc:
            if quiet:
                return None

            print(
                "Face detection is disabled: this environment has MediaPipe "
                "without `solutions.face_detection`, and OpenCV does not "
                f"include the fallback cascade detector. Details: {exc}"
            )
            return _NoOpFaceDetector()

    def detect(self, frame):
        """
        Detect all faces in the frame.

        Args:
            frame (numpy.ndarray): BGR image.

        Returns:
            list:
                [
                    (x, y, w, h),
                    ...
                ]
        """

        return self.detector.process(frame)

    def get_primary_face(self, frame):
        """
        Returns the largest face in the frame.

        Args:
            frame (numpy.ndarray)

        Returns:
            (x, y, w, h) or None
        """

        faces = self.detect(frame)

        if not faces:
            return None

        # Largest area = primary user
        primary_face = max(
            faces,
            key=lambda face: face[2] * face[3]
        )

        return primary_face
