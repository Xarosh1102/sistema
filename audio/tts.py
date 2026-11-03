import os
import re
import hashlib
import asyncio
import threading
from pathlib import Path

import numpy as np
import pygame
import soundfile as sf
from scipy import signal
import edge_tts

from config.settings import (
    DATA_DIR,
    TTS_VOICE,
    TTS_RATE,
    TTS_PITCH,
    USE_INTERCOM_EFFECT,
)

JARVIS_SOUNDS_DIR = DATA_DIR / "jarvis_sounds"
JARVIS_CACHE_DIR = DATA_DIR / "jarvis_cache"


class TextToSpeech:
    def __init__(self, use_intercom_effect: bool = USE_INTERCOM_EFFECT, speaker: str = "dmitry"):
        self.use_intercom_effect = use_intercom_effect
        self.voice = TTS_VOICE
        self.rate = TTS_RATE
        self.pitch = TTS_PITCH
        self._lock = threading.Lock()
        self._stop_requested = False

        JARVIS_SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        JARVIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=512)
        except Exception as e:
            print(f"[TTS] Ошибка инициализации аудиомикшера: {e}")

        # В фоне прогреваем коронные фразы Джарвиса для мгновенного отклика
        threading.Thread(target=self._warmup_jarvis_phrases, daemon=True).start()

    def _warmup_jarvis_phrases(self):
        phrases = [
            "К вашим услугам, сэр.",
            "Да, сэр?",
            "Всегда к вашим услугам, сэр.",
            "Выполнено, сэр.",
            "Как прикажете, сэр.",
        ]
        for p in phrases:
            try:
                self._get_or_create_cached_audio(p)
            except Exception:
                pass
        print("[TTS] Голосовой модуль Джарвиса (DSP Intercom) готов к работе!")

    @staticmethod
    def _clean_text_for_speech(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"[*#`_~>|]", "", text)
        cleaned = re.sub(r"https?://\S+", "ссылка", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _apply_jarvis_dsp(self, audio: np.ndarray, sr: int) -> np.ndarray:
        """
        Создает фирменный тембр Джарвиса из фильма «Железный человек»:
        фильтрация частот, двойной фазовый микро-дилей (эффект голограммы/шлема) и мягкая сатурация.
        """
        if audio.ndim > 1:
            audio = np.mean(audio, axis=1)
        audio = audio.astype(np.float32)

        # 1. Полосовой фильтр (убираем глухой низ ниже 85 Гц и резкий песок выше 7800 Гц)
        nyq = 0.5 * sr
        low = max(0.001, min(85.0 / nyq, 0.99))
        high = max(low + 0.01, min(7800.0 / nyq, 0.99))
        b, a = signal.butter(2, [low, high], btype="band")
        filtered = signal.lfilter(b, a, audio)

        # 2. Легкий подъем презенса (2.5 кГц) для четкости дикции
        b_peak, a_peak = signal.iirpeak(min(2500.0 / nyq, 0.95), Q=2.5)
        presence = signal.lfilter(b_peak, a_peak, filtered)
        sculpted = filtered * 0.82 + presence * 0.18

        # 3. Двойная пространственная микро-задержка (14 мс и 27 мс) — узнаваемый металлический оттенок Джарвиса
        d1 = int(sr * 0.014)
        d2 = int(sr * 0.027)
        delayed1 = np.zeros_like(sculpted)
        delayed2 = np.zeros_like(sculpted)
        if len(sculpted) > d2:
            delayed1[d1:] = sculpted[:-d1]
            delayed2[d2:] = sculpted[:-d2]

        mixed = sculpted * 0.78 + delayed1 * 0.15 + delayed2 * 0.07

        # 4. Мягкая компрессия и нормализация громкости
        compressed = np.tanh(mixed * 1.35)
        max_val = float(np.max(np.abs(compressed)))
        if max_val > 1e-5:
            compressed = (compressed / max_val) * 0.92

        return compressed.astype(np.float32)

    async def _synthesize_edge_async(self, text: str, raw_mp3_path: Path):
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            pitch=self.pitch,
        )
        await communicate.save(str(raw_mp3_path))

    def _find_original_movie_sample(self, clean_text: str) -> Path | None:
        """Если в папке data/jarvis_sounds лежат оригинальные сэмплы из фильма, возвращает их."""
        low = clean_text.lower().strip(" .,!?")
        mapping = {
            "да, сэр": ["yes_sir.wav", "yes_sir.mp3"],
            "да сэр": ["yes_sir.wav", "yes_sir.mp3"],
            "к вашим услугам, сэр": ["at_your_service.wav", "at_your_service.mp3"],
            "к вашим услугам сэр": ["at_your_service.wav", "at_your_service.mp3"],
            "всегда к вашим услугам, сэр": ["at_your_service.wav", "at_your_service.mp3"],
        }
        for key, filenames in mapping.items():
            if low == key:
                for fname in filenames:
                    candidate = JARVIS_SOUNDS_DIR / fname
                    if candidate.exists():
                        return candidate
        return None

    def _get_or_create_cached_audio(self, clean_text: str) -> Path | None:
        orig_sample = self._find_original_movie_sample(clean_text)
        if orig_sample is not None:
            return orig_sample

        text_hash = hashlib.md5(
            f"{clean_text}_{self.voice}_{self.rate}_{self.pitch}_{self.use_intercom_effect}".encode("utf-8")
        ).hexdigest()[:16]

        final_wav = JARVIS_CACHE_DIR / f"jarvis_{text_hash}.wav"
        if final_wav.exists():
            return final_wav

        temp_mp3 = JARVIS_CACHE_DIR / f"temp_{text_hash}.mp3"
        try:
            asyncio.run(self._synthesize_edge_async(clean_text, temp_mp3))
            if not temp_mp3.exists():
                return None

            data, sr = sf.read(str(temp_mp3), dtype="float32")
            if self.use_intercom_effect:
                data = self._apply_jarvis_dsp(data, sr)

            sf.write(str(final_wav), data, sr, subtype="PCM_16")
            return final_wav
        except Exception as e:
            print(f"[TTS] Ошибка синтеза речи Джарвиса: {e}")
            return temp_mp3 if temp_mp3.exists() else None
        finally:
            if temp_mp3.exists() and final_wav.exists():
                temp_mp3.unlink(missing_ok=True)

    def speak(self, text: str, blocking: bool = True):
        clean_text = self._clean_text_for_speech(text)
        if not clean_text:
            return

        self._stop_requested = False

        def _play_task():
            with self._lock:
                if self._stop_requested:
                    return
                audio_path = self._get_or_create_cached_audio(clean_text)
                if not audio_path or not audio_path.exists() or self._stop_requested:
                    return

                try:
                    pygame.mixer.music.load(str(audio_path))
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        if self._stop_requested:
                            pygame.mixer.music.stop()
                            break
                        pygame.time.Clock().tick(30)
                except Exception as e:
                    print(f"[TTS] Ошибка воспроизведения: {e}")

        if blocking:
            _play_task()
        else:
            threading.Thread(target=_play_task, daemon=True).start()

    def stop(self):
        self._stop_requested = True
        try:
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
        except Exception:
            pass