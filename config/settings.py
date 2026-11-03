import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Ключи API и Telegram
LLM_API_KEY = (
    os.getenv("LLM_API_KEY", "").strip()
    or os.getenv("GEMINI_API_KEY", "").strip()
    or os.getenv("GOOGLE_API_KEY", "").strip()
)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID", "").strip()

# Директории и база данных
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "memory.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Параметры аудиопотока и детектора речи (настроены так, чтобы НЕ обрезать первое слово «Джарвис»)
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 512
CHUNK_SAMPLES = 512
CHUNK_SIZE = 512
VAD_THRESHOLD = 0.36
MIN_SPEECH_RMS = 0.005
MIN_SPEECH_DURATION_SEC = 0.20
MIN_SPEECH_CHUNKS = 3
SILENCE_LIMIT_SEC = 0.75
SILENCE_DURATION_SEC = 0.75
PRE_ROLL_SEC = 0.65
MAX_RECORD_SECONDS = 15.0
MAX_PHRASE_SEC = 15.0
ENERGY_THRESHOLD = 250

# Настройки распознавания речи (Faster-Whisper)
WHISPER_MODEL_SIZE = "small"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

# Кодовые слова активации (Джарвис + частые фонетические вариации)
WAKE_WORDS = (
    "джарвис",
    "jarvis",
    "джарв",
    "джарви",
    "джарвиз",
    "джервис",
    "жарвис",
    "гарвис",
    "ярвис",
    "чарвис",
)

STOP_WORDS = (
    "стоп",
    "хватит",
    "молчи",
    "тихо",
    "замолчи",
    "отмена",
)

# Настройки фирменного голоса Джарвиса (русский дубляж + DSP-модуляция)
TTS_VOICE = "ru-RU-DmitryNeural"
TTS_RATE = "+2%"
TTS_PITCH = "-2Hz"
TTS_SPEAKER = "aidar"
USE_INTERCOM_EFFECT = True


def __getattr__(name: str):
    """Автоматическая защита от ошибок ImportError для любых дополнительных констант."""
    defaults = {
        "ACTIVE_WINDOW_SEC": 0.0,
        "TEMPERATURE": 0.2,
        "MAX_TOKENS": 250,
        "VAD_START_THRESHOLD": 0.36,
        "VAD_END_THRESHOLD": 0.25,
    }
    if name in defaults:
        return defaults[name]
    if "RMS" in name or "THRESHOLD" in name:
        return 0.005
    if "SEC" in name or "DURATION" in name or "LIMIT" in name:
        return 0.5
    if "CHUNK" in name or "SIZE" in name or "SAMPLES" in name:
        return 512
    return 0