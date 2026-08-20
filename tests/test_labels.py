from utils.labels import EMOTION_LABELS


def test_emotion_labels_match_fer2013_order():
    assert EMOTION_LABELS == (
        "Angry",
        "Disgust",
        "Fear",
        "Happy",
        "Sad",
        "Surprise",
        "Neutral",
    )
    assert len(EMOTION_LABELS) == 7
