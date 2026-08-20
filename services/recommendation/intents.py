from utils.labels import EMOTION_LABELS


EMOTION_INTENTS = {
    "Angry": {
        "intent": "de-escalate",
        "query": "ambient acoustic chill downtempo calm",
        "description": "Lower intensity with ambient, acoustic, and downtempo calm tracks.",
    },
    "Disgust": {
        "intent": "reset",
        "query": "indie pop bright clean upbeat",
        "description": "Reset the mood with bright indie-pop and clean upbeat tracks.",
    },
    "Fear": {
        "intent": "reassure",
        "query": "piano ambient soothing cinematic",
        "description": "Reduce tension with soft piano, ambient, and soothing cinematic tracks.",
    },
    "Happy": {
        "intent": "amplify",
        "query": "dance pop rock upbeat feel good",
        "description": "Amplify energy with upbeat dance, pop, and rock tracks.",
    },
    "Sad": {
        "intent": "comfort",
        "query": "soul acoustic mellow warm",
        "description": "Comfort with warm soul, acoustic, and mellow tracks.",
    },
    "Surprise": {
        "intent": "channel",
        "query": "electronic pop discovery energetic",
        "description": "Channel alert energy into electronic, pop, and discovery tracks.",
    },
    "Neutral": {
        "intent": "focus",
        "query": "lofi instrumental focus chill",
        "description": "Maintain balance with lofi, instrumental, and focus-friendly tracks.",
    },
}


MOOD_PROFILE_VARIANTS = {
    "Angry": [
        {
            "variant": "ambient-calm",
            "query": "ambient acoustic chill downtempo calm",
            "energy": "low",
            "genre": "ambient",
            "instrument": "acoustic",
            "tempo": "slow",
            "vibe": "settling",
        },
        {
            "variant": "piano-reset",
            "query": "soft piano peaceful instrumental",
            "energy": "low",
            "genre": "instrumental",
            "instrument": "piano",
            "tempo": "slow",
            "vibe": "peaceful",
        },
        {
            "variant": "lofi-release",
            "query": "lofi chill mellow beats",
            "energy": "low-medium",
            "genre": "lofi",
            "instrument": "beats",
            "tempo": "mid",
            "vibe": "release",
        },
    ],
    "Disgust": [
        {
            "variant": "bright-clean",
            "query": "indie pop bright clean upbeat",
            "energy": "medium",
            "genre": "indie pop",
            "instrument": "guitar",
            "tempo": "mid",
            "vibe": "fresh",
        },
        {
            "variant": "sunny-reset",
            "query": "sunny pop fresh feel good",
            "energy": "medium-high",
            "genre": "pop",
            "instrument": "synth",
            "tempo": "mid",
            "vibe": "clean",
        },
        {
            "variant": "acoustic-lift",
            "query": "acoustic bright hopeful light",
            "energy": "medium",
            "genre": "acoustic",
            "instrument": "guitar",
            "tempo": "mid",
            "vibe": "hopeful",
        },
    ],
    "Fear": [
        {
            "variant": "piano-soothe",
            "query": "piano ambient soothing cinematic",
            "energy": "low",
            "genre": "cinematic",
            "instrument": "piano",
            "tempo": "slow",
            "vibe": "reassuring",
        },
        {
            "variant": "warm-ambient",
            "query": "warm ambient soft relaxing",
            "energy": "low",
            "genre": "ambient",
            "instrument": "pads",
            "tempo": "slow",
            "vibe": "safe",
        },
        {
            "variant": "gentle-acoustic",
            "query": "gentle acoustic calm peaceful",
            "energy": "low-medium",
            "genre": "acoustic",
            "instrument": "guitar",
            "tempo": "slow",
            "vibe": "steady",
        },
    ],
    "Happy": [
        {
            "variant": "feel-good",
            "query": "dance pop rock upbeat feel good",
            "energy": "high",
            "genre": "pop rock",
            "instrument": "drums",
            "tempo": "fast",
            "vibe": "upbeat",
        },
        {
            "variant": "funk-groove",
            "query": "funk bright groove upbeat",
            "energy": "medium-high",
            "genre": "funk",
            "instrument": "bass",
            "tempo": "mid",
            "vibe": "bright",
        },
        {
            "variant": "sunny-indie",
            "query": "indie pop sunny energetic",
            "energy": "high",
            "genre": "indie pop",
            "instrument": "guitar",
            "tempo": "fast",
            "vibe": "sunny",
        },
        {
            "variant": "electronic-cheer",
            "query": "electronic dance cheerful",
            "energy": "high",
            "genre": "electronic",
            "instrument": "synth",
            "tempo": "fast",
            "vibe": "cheerful",
        },
        {
            "variant": "summer-pop",
            "query": "pop summer high energy",
            "energy": "high",
            "genre": "pop",
            "instrument": "drums",
            "tempo": "fast",
            "vibe": "summer",
        },
    ],
    "Sad": [
        {
            "variant": "warm-mellow",
            "query": "soul acoustic mellow warm",
            "energy": "low-medium",
            "genre": "soul",
            "instrument": "acoustic",
            "tempo": "slow",
            "vibe": "warm",
        },
        {
            "variant": "soft-comfort",
            "query": "soft indie folk comforting",
            "energy": "low",
            "genre": "folk",
            "instrument": "guitar",
            "tempo": "slow",
            "vibe": "comforting",
        },
        {
            "variant": "gentle-soul",
            "query": "gentle soul mellow hopeful",
            "energy": "low-medium",
            "genre": "soul",
            "instrument": "keys",
            "tempo": "mid",
            "vibe": "hopeful",
        },
    ],
    "Surprise": [
        {
            "variant": "electronic-discovery",
            "query": "electronic pop discovery energetic",
            "energy": "high",
            "genre": "electronic pop",
            "instrument": "synth",
            "tempo": "fast",
            "vibe": "curious",
        },
        {
            "variant": "alt-pop-spark",
            "query": "alternative pop fresh energetic",
            "energy": "medium-high",
            "genre": "alternative pop",
            "instrument": "guitar",
            "tempo": "mid",
            "vibe": "fresh",
        },
        {
            "variant": "dance-pulse",
            "query": "dance electronic bright pulse",
            "energy": "high",
            "genre": "dance",
            "instrument": "synth",
            "tempo": "fast",
            "vibe": "bright",
        },
    ],
    "Neutral": [
        {
            "variant": "lofi-focus",
            "query": "lofi instrumental focus chill",
            "energy": "medium",
            "genre": "lofi",
            "instrument": "beats",
            "tempo": "mid",
            "vibe": "focused",
        },
        {
            "variant": "instrumental-flow",
            "query": "instrumental electronic focus flow",
            "energy": "medium",
            "genre": "electronic",
            "instrument": "synth",
            "tempo": "mid",
            "vibe": "flow",
        },
        {
            "variant": "acoustic-work",
            "query": "acoustic instrumental calm focus",
            "energy": "low-medium",
            "genre": "acoustic",
            "instrument": "guitar",
            "tempo": "mid",
            "vibe": "balanced",
        },
    ],
}


def get_intent_for_emotion(emotion):
    if emotion not in EMOTION_LABELS:
        raise ValueError(f"Unsupported emotion: {emotion}")

    return EMOTION_INTENTS[emotion]


def get_profile_variants_for_emotion(emotion):
    if emotion not in EMOTION_LABELS:
        raise ValueError(f"Unsupported emotion: {emotion}")

    return MOOD_PROFILE_VARIANTS[emotion]
