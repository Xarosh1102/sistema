import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

LLM_API_KEY = (
    os.getenv("GEMINI_API_KEY", "").strip()
    or os.getenv("LLM_API_KEY", "").strip()
)

DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Кодовые слова для активации Джарвиса
WAKE_WORDS = ["джарвис", "jarvis", "джарв"]

# Настройки Faster-Whisper
WHISPER_MODEL_SIZE = "small"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"
SAMPLE_RATE = 16000