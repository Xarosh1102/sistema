import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "memory.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Ключевые слова активации
WAKE_WORDS = ("система", "систем", "cистема")

# Настройки аудиопотока
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SAMPLES = 512  # ~32 мс для Silero VAD при 16 кГц

# Оптимальный баланс: слышит спокойный голос у ноутбука, но отсекает далекий фон
VAD_THRESHOLD = 0.40          # Было 0.52+ (слишком строго для спокойного голоса)
MIN_SPEECH_RMS = 0.0022       # Было 0.005 (требовало говорить громко)

# Тайминги записи (ускоренный отклик)
PRE_ROLL_MS = 350             # Запас до начала фразы, чтобы не съедало "Си-" в слове "Система"
SILENCE_TIMEOUT_MS = 450      # Было 700-800 мс: теперь отвечает почти в 2 раза быстрее после конца фразы
MIN_SPEECH_MS = 180           # Позволяет распознавать короткие быстрые команды
MAX_SPEECH_SECONDS = 12       # Максимальная длина одной голосовой команды

# Настройки модели распознавания речи (Faster-Whisper)
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

# Ключ Gemini API
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()