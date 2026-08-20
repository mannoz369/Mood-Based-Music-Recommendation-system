import React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Aperture,
  Camera,
  CheckCircle2,
  ExternalLink,
  ListMusic,
  Loader2,
  Lock,
  LogOut,
  Music2,
  Pause,
  Play,
  RefreshCw,
  ScanFace,
  Settings2,
  SkipBack,
  SkipForward,
  Square,
  Upload,
  User,
  Video,
  X,
} from "lucide-react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8001";
const MAX_CAPTURE_WIDTH = 960;
const DEFAULT_RATE_LIMIT_NOTICE_SECONDS = 8;
const autoCaptureIntervals = [30, 60, 120];

const emotionTone = {
  Angry: "#ff4242",
  Disgust: "#6ee08b",
  Fear: "#a982ff",
  Happy: "#ffcf3f",
  Sad: "#5fa8ff",
  Surprise: "#ff884d",
  Neutral: "#9aa4b2",
};

const emotionBackgrounds = {
  Angry: ["#2b0708", "#ff2020", "#790909"],
  Disgust: ["#062016", "#6ee08b", "#125c39"],
  Fear: ["#12092a", "#a982ff", "#39206f"],
  Happy: ["#2d2207", "#ffcf3f", "#b15f00"],
  Sad: ["#071629", "#5fa8ff", "#123d67"],
  Surprise: ["#2d1408", "#ff884d", "#8b2b0f"],
  Neutral: ["#111218", "#9aa4b2", "#313744"],
};

const languageOptions = [
  { value: "", label: "Any language" },
  { value: "hi", label: "Hindi" },
  { value: "te", label: "Telugu" },
  { value: "ta", label: "Tamil" },
  { value: "kn", label: "Kannada" },
  { value: "ml", label: "Malayalam" },
  { value: "bn", label: "Bengali" },
  { value: "mr", label: "Marathi" },
  { value: "pa", label: "Punjabi" },
  { value: "en", label: "English" },
];

function formatPercent(value) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "--";
}

function formatTime(value) {
  if (!Number.isFinite(value) || value < 0) {
    return "0:00";
  }

  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function formatRetrySeconds(value) {
  if (!Number.isFinite(value) || value <= 0) {
    return "a moment";
  }

  if (value < 60) {
    return `${Math.ceil(value)}s`;
  }

  const minutes = Math.ceil(value / 60);
  return `${minutes} min`;
}

function App() {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const streamRef = useRef(null);
  const audioRef = useRef(null);
  const recommendationRequestRef = useRef(0);
  const recommendationAbortRef = useRef(null);
  const autoCaptureUserRef = useRef("");
  const queueRefillInFlightRef = useRef(false);
  const autoTrackingInFlightRef = useRef(false);
  const playbackEndingRef = useRef(false);

  const [cameraStatus, setCameraStatus] = useState("idle");
  const [apiStatus, setApiStatus] = useState("checking");
  const [apiDetail, setApiDetail] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [isDetecting, setIsDetecting] = useState(false);
  const [snapshotUrl, setSnapshotUrl] = useState("");
  const [authMode, setAuthMode] = useState("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authToken, setAuthToken] = useState(() => localStorage.getItem("emotionMusicToken") || "");
  const [authUser, setAuthUser] = useState(null);
  const [authStatus, setAuthStatus] = useState(authToken ? "checking" : "signed-out");
  const [authMessage, setAuthMessage] = useState("");
  const [recommendations, setRecommendations] = useState([]);
  const [recommendationStatus, setRecommendationStatus] = useState("idle");
  const [recommendationError, setRecommendationError] = useState("");
  const [currentTrackIndex, setCurrentTrackIndex] = useState(0);
  const [shouldAutoPlay, setShouldAutoPlay] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playerMessage, setPlayerMessage] = useState("");
  const [autoCapturePending, setAutoCapturePending] = useState(false);
  const [languagePreference, setLanguagePreference] = useState(() => localStorage.getItem("emotionMusicLanguage") || "");
  const [showCameraPanel, setShowCameraPanel] = useState(false);
  const [showProfilePanel, setShowProfilePanel] = useState(() => !authToken);
  const [showPreferencesPanel, setShowPreferencesPanel] = useState(false);
  const [showQueue, setShowQueue] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [bubblePush, setBubblePush] = useState({ x: 0, y: 0 });
  const [rateLimitNotice, setRateLimitNotice] = useState(null);
  const [autoTrackingEnabled, setAutoTrackingEnabled] = useState(false);
  const [autoTrackingInterval, setAutoTrackingInterval] = useState(60);
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.6);
  const [refreshOnlyOnMoodChange, setRefreshOnlyOnMoodChange] = useState(true);

  const currentTrack = recommendations[currentTrackIndex] || null;
  const accent = useMemo(
    () => (result ? emotionTone[result.emotion] || emotionTone.Neutral : "#ff2020"),
    [result],
  );
  const moodBackground = useMemo(
    () => emotionBackgrounds[result?.emotion] || emotionBackgrounds.Neutral,
    [result],
  );
  const selectedLanguageLabel = languageOptions.find((option) => option.value === languagePreference)?.label || "Any language";
  const progressPercent = duration ? Math.min(100, Math.max(0, (currentTime / duration) * 100)) : 0;
  const shellStyle = {
    "--accent": accent,
    "--mood-bg": moodBackground[0],
    "--mood-glow": moodBackground[1],
    "--mood-deep": moodBackground[2],
    "--bubble-push-x": `${bubblePush.x}px`,
    "--bubble-push-y": `${bubblePush.y}px`,
  };

  function languageLabelFor(value) {
    return languageOptions.find((option) => option.value === value)?.label || "Any language";
  }

  function showRateLimitNotice(response, body = {}) {
    const retryHeader = Number(response.headers.get("Retry-After"));
    const retryBody = Number(body.retry_after_seconds);
    const retrySeconds = Number.isFinite(retryHeader)
      ? retryHeader
      : Number.isFinite(retryBody)
        ? retryBody
        : DEFAULT_RATE_LIMIT_NOTICE_SECONDS;
    const visibleSeconds = Math.max(DEFAULT_RATE_LIMIT_NOTICE_SECONDS, retrySeconds || DEFAULT_RATE_LIMIT_NOTICE_SECONDS);

    setRateLimitNotice({
      id: Date.now(),
      durationMs: visibleSeconds * 1000,
      message: `You are making too many requests. Try again after ${formatRetrySeconds(retrySeconds)}.`,
    });
  }

  function showRateLimitFetchFailureNotice() {
    setRateLimitNotice({
      id: Date.now(),
      durationMs: DEFAULT_RATE_LIMIT_NOTICE_SECONDS * 1000,
      message: "You are making too many requests. Try again after a moment.",
    });
  }

  function isFetchFailure(error) {
    return error instanceof TypeError && /failed to fetch/i.test(error.message);
  }

  function dismissRateLimitNotice() {
    setRateLimitNotice(null);
  }

  function handleBackgroundPointerMove(event) {
    if (event.target.closest(".wrapper, .app-nav, .nav-popover, .camera-dock")) {
      return;
    }

    const centerX = window.innerWidth / 2;
    const centerY = window.innerHeight / 2;
    const pushX = Math.max(-90, Math.min(90, (event.clientX - centerX) / 6));
    const pushY = Math.max(-70, Math.min(70, (event.clientY - centerY) / 8));
    setBubblePush({ x: pushX, y: pushY });
  }

  useEffect(() => {
    let cancelled = false;

    async function checkApi() {
      try {
        const response = await fetch(`${API_BASE_URL}/api/health`);

        if (!response.ok) {
          throw new Error(`Health check returned ${response.status}`);
        }

        const body = await response.json();

        if (!cancelled) {
          setApiStatus(body.status === "ok" ? "online" : "degraded");
          setApiDetail(body.emotion_api?.model || body.emotion_api?.detail || body.detail || "");
        }
      } catch (healthError) {
        if (!cancelled) {
          setApiStatus("offline");
          setApiDetail(healthError.message);
        }
      }
    }

    checkApi();

    return () => {
      cancelled = true;
      stopCamera();
    };
  }, []);

  useEffect(() => {
    if (!rateLimitNotice) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      setRateLimitNotice(null);
    }, rateLimitNotice.durationMs);

    return () => window.clearTimeout(timer);
  }, [rateLimitNotice]);

  useEffect(() => {
    let cancelled = false;

    async function loadCurrentUser() {
      if (!authToken) {
        setAuthUser(null);
        setAuthStatus("signed-out");
        return;
      }

      setAuthStatus("checking");

      try {
        const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });

        if (!response.ok) {
          throw new Error("Session expired. Sign in again.");
        }

        const body = await response.json();

        if (!cancelled) {
          setAuthUser(body.user);
          setAuthStatus("signed-in");
          setAuthMessage("");
        }
      } catch (currentUserError) {
        localStorage.removeItem("emotionMusicToken");

        if (!cancelled) {
          setAuthToken("");
          setAuthUser(null);
          setAuthStatus("signed-out");
          setAuthMessage(currentUserError.message);
        }
      }
    }

    loadCurrentUser();

    return () => {
      cancelled = true;
    };
  }, [authToken]);

  useEffect(() => {
    if (authStatus !== "signed-in" || !authUser) {
      return;
    }

    const userKey = authUser.id || authUser.email;

    if (!userKey || autoCaptureUserRef.current === userKey) {
      return;
    }

    autoCaptureUserRef.current = userKey;
    setAutoCapturePending(true);

    if (cameraStatus === "idle") {
      startCamera();
    }
  }, [authStatus, authUser, cameraStatus]);

  useEffect(() => {
    if (!autoCapturePending || authStatus !== "signed-in" || cameraStatus !== "ready" || isDetecting) {
      return;
    }

    const timer = window.setTimeout(() => {
      setAutoCapturePending(false);
      detectEmotion();
    }, 900);

    return () => window.clearTimeout(timer);
  }, [autoCapturePending, authStatus, cameraStatus, isDetecting]);

  useEffect(() => {
    if (
      !autoTrackingEnabled
      || authStatus !== "signed-in"
      || cameraStatus !== "ready"
      || isDetecting
    ) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      detectEmotion({ mode: "auto" });
    }, autoTrackingInterval * 1000);

    return () => window.clearTimeout(timer);
  }, [
    autoTrackingEnabled,
    autoTrackingInterval,
    authStatus,
    cameraStatus,
    isDetecting,
    result?.emotion,
    confidenceThreshold,
    refreshOnlyOnMoodChange,
  ]);

  useEffect(() => {
    if (!shouldAutoPlay || !currentTrack?.audio_url || !audioRef.current) {
      return;
    }

    const audio = audioRef.current;
    audio.load();
    const playPromise = audio.play();

    if (playPromise) {
      playPromise
        .then(() => {
          setIsPlaying(true);
          setPlayerMessage("");
        })
        .catch(() => {
          setIsPlaying(false);
          setPlayerMessage("Press play to start audio in this browser.");
        });
    }
  }, [currentTrack?.audio_url, shouldAutoPlay]);

  async function startCamera() {
    setError("");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      });

      streamRef.current = stream;

      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }

      setCameraStatus("ready");
    } catch (cameraError) {
      setCameraStatus("blocked");
      setAutoCapturePending(false);
      setError(cameraError.message || "Camera permission was denied.");
    }
  }

  function stopCamera() {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }

    setCameraStatus("idle");
    setAutoTrackingEnabled(false);
    autoTrackingInFlightRef.current = false;
  }

  function toggleCameraPanel() {
    setShowCameraPanel((visible) => {
      const nextVisible = authStatus === "signed-in" ? !visible : false;

      if (nextVisible && cameraStatus === "idle") {
        startCamera();
      }

      if (nextVisible) {
        setShowQueue(false);
        setShowPreferencesPanel(false);
        setShowProfilePanel(false);
      }

      return nextVisible;
    });
  }

  function captureBlob() {
    const video = videoRef.current;
    const canvas = canvasRef.current;

    if (!video || !canvas || video.videoWidth === 0) {
      throw new Error("Camera frame is not ready yet.");
    }

    const scale = Math.min(1, MAX_CAPTURE_WIDTH / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const context = canvas.getContext("2d");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    return new Promise((resolve, reject) => {
      canvas.toBlob(
        (blob) => {
          if (!blob) {
            reject(new Error("Could not capture the current frame."));
            return;
          }

          resolve(blob);
        },
        "image/jpeg",
        0.85,
      );
    });
  }

  async function loadRecommendations(emotion, language = languagePreference) {
    if (recommendationAbortRef.current) {
      recommendationAbortRef.current.abort();
    }

    const abortController = new AbortController();
    recommendationAbortRef.current = abortController;
    const requestId = recommendationRequestRef.current + 1;
    recommendationRequestRef.current = requestId;

    if (!emotion) {
      setRecommendations([]);
      setRecommendationStatus("idle");
      setRecommendationError("");
      return;
    }

    setRecommendationStatus("loading");
    setRecommendationError("");

    try {
      let body = null;
      let fallbackMessage = "";
      const selectedLanguage = language || "";

      for (let attempt = 1; attempt <= 3; attempt += 1) {
        body = await fetchRecommendations(emotion, selectedLanguage, abortController.signal);

        if (body.tracks?.length || !selectedLanguage) {
          break;
        }
      }

      if (requestId !== recommendationRequestRef.current) {
        return;
      }

      if (selectedLanguage && !body.tracks?.length) {
        fallbackMessage = `No ${languageLabelFor(selectedLanguage)} tracks after 3 tries. Switched to Any language.`;
        setLanguagePreference("");
        localStorage.setItem("emotionMusicLanguage", "");
        body = await fetchRecommendations(emotion, "", abortController.signal);
      }

      if (requestId !== recommendationRequestRef.current) {
        return;
      }

      const tracks = body.tracks || [];
      const languageLabel = languageLabelFor(selectedLanguage);
      setRecommendations(tracks);
      setCurrentTrackIndex(0);
      setShouldAutoPlay(tracks.some((track) => track.audio_url));
      setPlayerMessage(
        tracks.length
          ? fallbackMessage
          : `No songs found for ${fallbackMessage ? "Any language" : languageLabel}. Select another language.`,
      );
      setRecommendationStatus(tracks.length ? "ready" : "empty");
      setShowQueue(tracks.length > 0);
    } catch (recommendationLoadError) {
      if (recommendationLoadError.name === "AbortError" || requestId !== recommendationRequestRef.current) {
        return;
      }

      if (isFetchFailure(recommendationLoadError)) {
        showRateLimitFetchFailureNotice();
      }

      setRecommendations([]);
      setCurrentTrackIndex(0);
      setShouldAutoPlay(false);
      setIsPlaying(false);
      setRecommendationStatus("error");
      setRecommendationError(recommendationLoadError.message);
    }
  }

  async function fetchRecommendations(emotion, language, signal) {
    const response = await fetch(`${API_BASE_URL}/api/recommendation/from-emotion`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${authToken}`,
      },
      body: JSON.stringify({
        emotion,
        limit: 5,
        language: language || null,
      }),
      signal,
    });
    const body = await response.json().catch(() => ({}));

    if (!response.ok) {
      if (response.status === 429) {
        showRateLimitNotice(response, body);
      }

      throw new Error(body.detail || `Recommendations failed with ${response.status}`);
    }

    return body;
  }

  async function fetchCachedCurrentEmotion() {
    const response = await fetch(`${API_BASE_URL}/api/recommendation/current-emotion`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    const body = await response.json().catch(() => ({}));

    if (!response.ok) {
      if (response.status === 429) {
        showRateLimitNotice(response, body);
      }

      throw new Error(body.detail || `Current mood lookup failed with ${response.status}`);
    }

    return body.emotion || null;
  }

  function emitPlaybackEvent(eventType, track = currentTrack) {
    const trackId = track?.id || track?.uri || track?.audio_url;

    if (!trackId || !authToken) {
      return;
    }

    fetch(`${API_BASE_URL}/api/playback/event`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${authToken}`,
      },
      body: JSON.stringify({
        event_type: eventType,
        track_id: String(trackId),
        emotion: result?.emotion || null,
        provider: track?.provider || "jamendo",
      }),
    }).catch(() => {});
  }

  function changeLanguagePreference(event) {
    const nextLanguage = event.target.value;
    setLanguagePreference(nextLanguage);
    localStorage.setItem("emotionMusicLanguage", nextLanguage);

    if (result?.emotion) {
      resetRecommendations();
      loadRecommendations(result.emotion, nextLanguage);
    }
  }

  function toggleAutoTracking() {
    setAutoTrackingEnabled((enabled) => {
      const nextEnabled = !enabled;

      if (nextEnabled && cameraStatus === "idle") {
        setShowCameraPanel(true);
        startCamera();
      }

      return nextEnabled;
    });
  }

  function resetRecommendations() {
    if (recommendationAbortRef.current) {
      recommendationAbortRef.current.abort();
      recommendationAbortRef.current = null;
    }

    setRecommendations([]);
    setRecommendationStatus("idle");
    setRecommendationError("");
    setCurrentTrackIndex(0);
    setShouldAutoPlay(false);
    setIsPlaying(false);
    setPlayerMessage("");
  }

  function playTrack(index) {
    if (currentTrack && index !== currentTrackIndex) {
      emitPlaybackEvent("skipped", currentTrack);
    }

    setCurrentTrackIndex(index);
    setShouldAutoPlay(true);
  }

  function togglePlayback() {
    const audio = audioRef.current;

    if (!audio || !currentTrack?.audio_url) {
      return;
    }

    if (audio.paused) {
      setShouldAutoPlay(true);
      audio.play()
        .then(() => {
          setIsPlaying(true);
          setPlayerMessage("");
        })
        .catch(() => {
          setIsPlaying(false);
          setPlayerMessage("Press play again or choose another track.");
        });
      return;
    }

    audio.pause();
    setIsPlaying(false);
  }

  async function playNextTrack() {
    const nextIndex = recommendations.findIndex(
      (track, index) => index > currentTrackIndex && Boolean(track.audio_url),
    );

    if (nextIndex === -1) {
      await refillQueueAfterTrackEnd();
      return;
    }

    playTrack(nextIndex);
  }

  async function refillQueueAfterTrackEnd() {
    if (queueRefillInFlightRef.current) {
      return;
    }

    queueRefillInFlightRef.current = true;
    setShouldAutoPlay(false);
    setIsPlaying(false);
    setPlayerMessage("Queue finished. Checking latest mood.");

    try {
      const cachedEmotion = await fetchCachedCurrentEmotion();

      if (cachedEmotion) {
        setResult((previous) => ({
          ...(previous || {}),
          emotion: cachedEmotion,
          confidence: previous?.emotion === cachedEmotion ? previous.confidence : null,
        }));
        setPlayerMessage(`Refreshing songs for ${cachedEmotion}.`);
        await loadRecommendations(cachedEmotion, languagePreference);
        return;
      }

      if (cameraStatus === "ready") {
        setPlayerMessage("No cached mood found. Capturing a fresh mood.");
        await detectEmotion();
        return;
      }

      if (cameraStatus === "idle") {
        setPlayerMessage("No cached mood found. Starting camera for a fresh mood.");
        setShowCameraPanel(true);
        setAutoCapturePending(true);
        await startCamera();
        return;
      }

      setPlayerMessage("No cached mood found. Start the camera to refresh songs.");
    } catch (refillError) {
      if (isFetchFailure(refillError)) {
        showRateLimitFetchFailureNotice();
      }

      setPlayerMessage(refillError.message);
    } finally {
      queueRefillInFlightRef.current = false;
    }
  }

  function playPreviousTrack() {
    const previous = [...recommendations]
      .slice(0, currentTrackIndex)
      .map((track, index) => ({ track, index }))
      .reverse()
      .find((item) => Boolean(item.track.audio_url));

    if (previous) {
      playTrack(previous.index);
    }
  }

  async function handleAudioEnded() {
    playbackEndingRef.current = true;
    emitPlaybackEvent("ended");
    await playNextTrack();
    window.setTimeout(() => {
      playbackEndingRef.current = false;
    }, 0);
  }

  function seekAudio(event) {
    if (!audioRef.current || !duration) {
      return;
    }

    const bounds = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - bounds.left) / bounds.width;
    audioRef.current.currentTime = Math.min(duration, Math.max(0, ratio * duration));
  }

  function toggleQueuePanel() {
    if (authStatus !== "signed-in") {
      return;
    }

    setShowQueue((visible) => {
      const nextVisible = !visible;

      if (nextVisible) {
        setShowCameraPanel(false);
        setShowPreferencesPanel(false);
        setShowProfilePanel(false);
      }

      return nextVisible;
    });
  }

  function togglePreferencesPanel() {
    if (authStatus !== "signed-in") {
      return;
    }

    setShowPreferencesPanel((visible) => {
      const nextVisible = !visible;

      if (nextVisible) {
        setShowCameraPanel(false);
        setShowQueue(false);
        setShowProfilePanel(false);
      }

      return nextVisible;
    });
  }

  function toggleProfilePanel() {
    setShowProfilePanel((visible) => {
      const nextVisible = !visible;

      if (nextVisible) {
        setShowCameraPanel(false);
        setShowQueue(false);
        setShowPreferencesPanel(false);
      }

      return nextVisible;
    });
  }

  async function detectEmotion(options = {}) {
    const isAutoMode = options.mode === "auto";

    if (isAutoMode && autoTrackingInFlightRef.current) {
      return;
    }

    if (isAutoMode) {
      autoTrackingInFlightRef.current = true;
    }

    const previousEmotion = result?.emotion;
    setError("");
    setIsDetecting(true);

    if (!isAutoMode) {
      resetRecommendations();
    }

    try {
      const blob = await captureBlob();
      setSnapshotUrl((previous) => {
        if (previous) {
          URL.revokeObjectURL(previous);
        }

        return URL.createObjectURL(blob);
      });

      const formData = new FormData();
      formData.append("file", blob, "camera-frame.jpg");

      const response = await fetch(`${API_BASE_URL}/api/emotion/detect`, {
        method: "POST",
        headers: { Authorization: `Bearer ${authToken}` },
        body: formData,
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        if (response.status === 429) {
          showRateLimitNotice(response, body);
        }
        throw new Error(body.detail || `Detection failed with ${response.status}`);
      }

      const detection = await response.json();
      setResult(detection);
      setIsDetecting(false);

      if (isAutoMode && detection.confidence < confidenceThreshold) {
        setPlayerMessage(
          `${detection.emotion} confidence ${formatPercent(detection.confidence)} is below ${formatPercent(confidenceThreshold)}.`,
        );
        return;
      }

      if (isAutoMode && refreshOnlyOnMoodChange && previousEmotion === detection.emotion) {
        setPlayerMessage(`Mood still ${detection.emotion}. Keeping the current queue.`);
        return;
      }

      loadRecommendations(detection.emotion);
    } catch (detectError) {
      if (isFetchFailure(detectError)) {
        showRateLimitFetchFailureNotice();
      }

      setError(detectError.message);
    } finally {
      setIsDetecting(false);
      autoTrackingInFlightRef.current = false;
    }
  }

  async function submitAuth(event) {
    event.preventDefault();
    setAuthStatus("submitting");
    setAuthMessage("");

    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/${authMode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: authEmail,
          password: authPassword,
        }),
      });

      const body = await response.json().catch(() => ({}));

      if (!response.ok) {
        if (response.status === 429) {
          showRateLimitNotice(response, body);
        }

        throw new Error(body.detail || `${authMode} failed with ${response.status}`);
      }

      localStorage.setItem("emotionMusicToken", body.access_token);
      setAuthToken(body.access_token);
      setAuthUser(body.user);
      setAuthStatus("signed-in");
      setAuthPassword("");
      setAuthMessage(authMode === "signup" ? "Account created." : "Signed in.");
      setShowProfilePanel(false);
    } catch (authError) {
      if (isFetchFailure(authError)) {
        showRateLimitFetchFailureNotice();
      }

      setAuthStatus("signed-out");
      setAuthMessage(authError.message);
    }
  }

  function signOut() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }

    localStorage.removeItem("emotionMusicToken");
    setAuthToken("");
    setAuthUser(null);
    setAuthStatus("signed-out");
    setAuthMessage("Signed out.");
    setAutoCapturePending(false);
    setAutoTrackingEnabled(false);
    autoTrackingInFlightRef.current = false;
    autoCaptureUserRef.current = "";
    stopCamera();
    resetRecommendations();
    setResult(null);
    setSnapshotUrl("");
    setCurrentTime(0);
    setDuration(0);
    setShowCameraPanel(false);
    setShowQueue(false);
    setShowPreferencesPanel(false);
    setShowProfilePanel(true);
  }

  async function handleUpload(event) {
    const file = event.target.files?.[0];

    if (!file) {
      return;
    }

    setError("");
    setIsDetecting(true);
    resetRecommendations();

    try {
      const formData = new FormData();
      formData.append("file", file);
      setSnapshotUrl((previous) => {
        if (previous) {
          URL.revokeObjectURL(previous);
        }

        return URL.createObjectURL(file);
      });

      const response = await fetch(`${API_BASE_URL}/api/emotion/detect`, {
        method: "POST",
        headers: { Authorization: `Bearer ${authToken}` },
        body: formData,
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        if (response.status === 429) {
          showRateLimitNotice(response, body);
        }
        throw new Error(body.detail || `Detection failed with ${response.status}`);
      }

      const detection = await response.json();
      setResult(detection);
      setIsDetecting(false);
      loadRecommendations(detection.emotion);
    } catch (uploadError) {
      if (isFetchFailure(uploadError)) {
        showRateLimitFetchFailureNotice();
      }

      setError(uploadError.message);
    } finally {
      setIsDetecting(false);
      event.target.value = "";
    }
  }

  return (
    <main className="app-shell" onMouseMove={handleBackgroundPointerMove} style={shellStyle}>
      {rateLimitNotice && (
        <aside
          className="rate-limit-toast"
          key={rateLimitNotice.id}
          role="alert"
          style={{ "--toast-duration": `${rateLimitNotice.durationMs}ms` }}
        >
          <div className="rate-limit-timer" aria-hidden="true" />
          <div className="rate-limit-icon">
            <AlertCircle size={20} />
          </div>
          <div className="rate-limit-copy">
            <strong>Too many requests</strong>
            <span>{rateLimitNotice.message}</span>
          </div>
          <button className="rate-limit-close" onClick={dismissRateLimitNotice} type="button" aria-label="Dismiss rate limit warning">
            <X size={18} />
          </button>
        </aside>
      )}

      <div className="particle-field" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>

      <nav className="app-nav">
        <div className="brand-lockup">
          <Music2 size={20} />
          <span>Emotion Player</span>
        </div>
        <div className="nav-actions">
          {authStatus === "signed-in" && (
            <>
              <button className={`nav-button ${showCameraPanel ? "active" : ""}`} onClick={toggleCameraPanel} title="Video" type="button">
                <Video size={18} />
              </button>
              <button className={`nav-button ${showQueue ? "active" : ""}`} onClick={toggleQueuePanel} title="Music queue" type="button">
                <ListMusic size={18} />
              </button>
              <button className={`nav-button ${showPreferencesPanel ? "active" : ""}`} onClick={togglePreferencesPanel} title="Music preferences" type="button">
                <Settings2 size={18} />
              </button>
            </>
          )}
          <button className={`nav-button ${showProfilePanel ? "active" : ""}`} onClick={toggleProfilePanel} title="Profile" type="button">
            <User size={18} />
          </button>
        </div>
      </nav>

      {showProfilePanel && (
        <section className="nav-popover profile-popover">
          <button className="close-button" onClick={() => setShowProfilePanel(false)} type="button">
            <X size={18} />
          </button>
          {authUser ? (
            <div className="profile-summary">
              <p className="panel-kicker">Profile</p>
              <h2>{authUser.email}</h2>
              <button className="ghost-command" onClick={signOut} type="button">
                <LogOut size={17} />
                <span>Logout</span>
              </button>
            </div>
          ) : (
            <form className="auth-form" onSubmit={submitAuth}>
              <p className="panel-kicker">Account</p>
              <div className="mode-toggle" role="tablist" aria-label="Auth mode">
                <button className={authMode === "login" ? "active" : ""} onClick={() => setAuthMode("login")} type="button">
                  Login
                </button>
                <button className={authMode === "signup" ? "active" : ""} onClick={() => setAuthMode("signup")} type="button">
                  Sign Up
                </button>
              </div>
              <label>
                <span>Email</span>
                <input autoComplete="email" onChange={(event) => setAuthEmail(event.target.value)} required type="email" value={authEmail} />
              </label>
              <label>
                <span>Password</span>
                <input
                  autoComplete={authMode === "login" ? "current-password" : "new-password"}
                  minLength={8}
                  onChange={(event) => setAuthPassword(event.target.value)}
                  required
                  type="password"
                  value={authPassword}
                />
              </label>
              <button className="primary-command" disabled={authStatus === "submitting"} type="submit">
                {authStatus === "submitting" ? <Loader2 className="spin" size={18} /> : <Lock size={18} />}
                <span>{authMode === "login" ? "Login" : "Create Account"}</span>
              </button>
              {authMessage && (
                <div className={`notice compact ${authStatus === "signed-out" ? "error" : "ready"}`}>
                  {authStatus === "signed-out" ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
                  <span>{authMessage}</span>
                </div>
              )}
            </form>
          )}
        </section>
      )}

      {showPreferencesPanel && (
        <section className="nav-popover preferences-popover">
          <button className="close-button" onClick={() => setShowPreferencesPanel(false)} type="button">
            <X size={18} />
          </button>
          <p className="panel-kicker">Music Preferences</p>
          <label className="language-control">
            <span>Language</span>
            <select onChange={changeLanguagePreference} value={languagePreference}>
              {languageOptions.map((option) => (
                <option key={option.label} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <div className="preference-copy">
            <span>{selectedLanguageLabel}</span>
            <p>{result?.emotion ? `Using this for ${result.emotion} recommendations.` : "Used for the next mood capture."}</p>
          </div>
          <div className="tracking-console">
            <div className="tracking-row">
              <div>
                <span>Auto mood tracking</span>
                <p>{autoTrackingEnabled ? `Every ${autoTrackingInterval}s` : "Off"}</p>
              </div>
              <button
                className={`switch-control ${autoTrackingEnabled ? "on" : ""}`}
                onClick={toggleAutoTracking}
                type="button"
                aria-pressed={autoTrackingEnabled}
              >
                <span />
              </button>
            </div>
            <div className="tracking-control">
              <span>Capture interval</span>
              <div className="interval-selector">
                {autoCaptureIntervals.map((seconds) => (
                  <button
                    className={autoTrackingInterval === seconds ? "active" : ""}
                    key={seconds}
                    onClick={() => setAutoTrackingInterval(seconds)}
                    type="button"
                  >
                    {seconds}s
                  </button>
                ))}
              </div>
            </div>
            <label className="tracking-control">
              <span>Confidence {formatPercent(confidenceThreshold)}</span>
              <input
                max="0.9"
                min="0.5"
                onChange={(event) => setConfidenceThreshold(Number(event.target.value))}
                step="0.05"
                type="range"
                value={confidenceThreshold}
              />
            </label>
            <label className="tracking-check">
              <input
                checked={refreshOnlyOnMoodChange}
                onChange={(event) => setRefreshOnlyOnMoodChange(event.target.checked)}
                type="checkbox"
              />
              <span>Refresh only when mood changes</span>
            </label>
          </div>
        </section>
      )}

      <section className={`camera-dock ${showCameraPanel ? "open" : ""}`}>
        <div className="camera-shell">
          <div className="camera-toolbar">
            <span>{cameraStatus === "ready" ? "Live Camera" : "Camera"}</span>
            <button className="close-button" onClick={() => setShowCameraPanel(false)} type="button">
              <X size={18} />
            </button>
          </div>
          <div className="video-stage">
            <video ref={videoRef} className="camera-feed" playsInline muted />
            {cameraStatus !== "ready" && (
              <div className="camera-empty">
                <ScanFace size={48} strokeWidth={1.6} />
                <p>{cameraStatus === "blocked" ? "Camera unavailable" : "Camera hidden"}</p>
              </div>
            )}
            <div className="scan-frame" aria-hidden="true" />
          </div>
          <div className="camera-actions">
            {cameraStatus === "ready" ? (
              <button className="ghost-command" onClick={stopCamera} type="button">
                <Square size={18} />
                <span>Stop</span>
              </button>
            ) : (
              <button className="ghost-command" onClick={startCamera} type="button">
                <Camera size={18} />
                <span>Start</span>
              </button>
            )}
            <button className="primary-command" disabled={cameraStatus !== "ready" || isDetecting || authStatus !== "signed-in"} onClick={detectEmotion} type="button">
              {isDetecting ? <Loader2 className="spin" size={18} /> : <Aperture size={18} />}
              <span>{isDetecting ? "Detecting" : "Capture"}</span>
            </button>
            <label className="ghost-command file-button">
              <Upload size={18} />
              <span>Upload</span>
              <input accept="image/*" onChange={handleUpload} type="file" />
            </label>
          </div>
        </div>
      </section>

      <section className="player-stage">
        <div className="wrapper">
          <div className="top-bar">
            <span>{recommendationStatus === "loading" ? "Finding Tracks" : "Now Playing"}</span>
          </div>

          <div className="img-area">
            {currentTrack?.artwork ? (
              <img src={currentTrack.artwork} alt="" />
            ) : snapshotUrl ? (
              <img src={snapshotUrl} alt="" />
            ) : (
              <div className="album-placeholder">
                <Music2 size={64} />
              </div>
            )}
          </div>

          <div className="song-details">
            <p className="name">{currentTrack?.name || result?.emotion || "Waiting for Mood"}</p>
            <p className="artist">{currentTrack?.artist || currentTrack?.artists?.join(", ") || selectedLanguageLabel}</p>
          </div>

          <button className="mood-chip" disabled={cameraStatus !== "ready" || isDetecting || authStatus !== "signed-in"} onClick={detectEmotion} type="button">
            {isDetecting || autoCapturePending ? <Loader2 className="spin" size={16} /> : <Aperture size={16} />}
            <span>
              {autoCapturePending
                ? "Auto capture"
                : result
                  ? `${result.emotion} ${formatPercent(result.confidence)}`
                  : "Capture mood"}
            </span>
          </button>

          <div className="progress-area" onClick={seekAudio} role="presentation">
            <div className="progress-bar" style={{ width: `${progressPercent}%` }} />
            <audio
              ref={audioRef}
              onDurationChange={(event) => setDuration(event.currentTarget.duration || 0)}
              onEnded={handleAudioEnded}
              onPause={() => {
                setIsPlaying(false);

                if (!playbackEndingRef.current) {
                  emitPlaybackEvent("paused");
                }
              }}
              onPlay={() => {
                setIsPlaying(true);
                emitPlaybackEvent("started");
              }}
              onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime || 0)}
              src={currentTrack?.audio_url || ""}
            />
          </div>

          <div className="song-timer">
            <span>{formatTime(currentTime)}</span>
            <span>{formatTime(duration)}</span>
          </div>

          <div className="controls">
            <button className="control-button" onClick={() => loadRecommendations(result?.emotion, languagePreference)} disabled={!result?.emotion || recommendationStatus === "loading"} type="button">
              <RefreshCw size={24} />
            </button>
            <button className="control-button skip" onClick={playPreviousTrack} disabled={!recommendations.length} type="button">
              <SkipBack size={36} />
            </button>
            <button className="play-pause" onClick={togglePlayback} disabled={!currentTrack?.audio_url} type="button">
              {isPlaying ? <Pause size={30} /> : <Play size={30} />}
            </button>
            <button className="control-button skip" onClick={playNextTrack} disabled={!recommendations.length} type="button">
              <SkipForward size={36} />
            </button>
            <button className="control-button" onClick={toggleQueuePanel} type="button">
              <ListMusic size={24} />
            </button>
          </div>

          {recommendationStatus === "loading" && (
            <div className="notice compact ready">
              <Loader2 className="spin" size={16} />
              <span>Finding {selectedLanguageLabel.toLowerCase()} tracks for {result?.emotion}</span>
            </div>
          )}

          {recommendationStatus === "error" && (
            <div className="notice compact error">
              <AlertCircle size={16} />
              <span>{recommendationError}</span>
            </div>
          )}

          {recommendationStatus === "empty" && (
            <div className="notice compact warning">
              <AlertCircle size={16} />
              <span>No song library found for {selectedLanguageLabel}.</span>
              {languagePreference && (
                <button className="text-action" onClick={() => changeLanguagePreference({ target: { value: "" } })} type="button">
                  Use Any
                </button>
              )}
            </div>
          )}

          {playerMessage && <p className="player-message">{playerMessage}</p>}

          {error ? (
            <div className="notice compact error" role="alert">
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          ) : (
            <div className="notice compact ready">
              <CheckCircle2 size={16} />
              <span>{apiStatus === "online" ? "Ready" : apiDetail || "Checking API"}</span>
            </div>
          )}

          <div className={`music-list ${showQueue ? "show" : ""}`}>
            <div className="header">
              <div className="row">
                <ListMusic size={20} />
                <span>Music list</span>
              </div>
              <button id="close" onClick={() => setShowQueue(false)} type="button">
                <X size={20} />
              </button>
            </div>
            <ul>
              {recommendations.length ? recommendations.map((track, index) => (
                <li className={index === currentTrackIndex ? "playing" : ""} key={track.id || track.audio_url || track.name} onClick={() => playTrack(index)}>
                  <div className="row">
                    <span>{track.name || "Untitled track"}</span>
                    <p>{track.artist || track.artists?.join(", ") || "Jamendo artist"}</p>
                  </div>
                  <span className="audio-duration">{index === currentTrackIndex ? "Playing" : track.duration ? formatTime(track.duration) : "--"}</span>
                </li>
              )) : (
                <li className="empty-list">
                  <div className="row">
                    <span>No tracks yet</span>
                    <p>Capture a mood to build the queue.</p>
                  </div>
                </li>
              )}
            </ul>
          </div>
        </div>
      </section>

      <canvas ref={canvasRef} hidden />
    </main>
  );
}

export default App;
