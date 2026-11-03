import io
import queue
import re
import threading
import time
import wave

import numpy as np
import pygame
import torch

LATIN_TO_CYRILLIC = {
    "jarvis": "джарвис", "windows": "виндовс", "cpu": "процессор", "ram": "память",
    "gpu": "видеокарта", "python": "пайтон", "github": "гитхаб", "chrome": "хром",
    "telegram": "телеграм", "whatsapp": "ватсап", "youtube": "ютуб", "steam": "стим",
    "discord": "дискорд", "wi-fi": "вайфай", "wifi": "вайфай", "ip": "айпи", "ok": "окей",
}

DIGITS_MAP = {
    "0": "ноль", "1": "один", "2": "два", "3": "три", "4": "четыре",
    "5": "пять", "6": "шесть", "7": "семь", "8": "восемь", "9": "девять",
}


def normalize_for_silero(text: str) -> str:
    res = text.lower().replace("%", " процентов ")
    for eng, rus in LATIN_TO_CYRILLIC.items():
        res = re.sub(rf"\b{re.escape(eng)}\b", rus, res)

    latin_chars = {
        "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "г",
        "h": "х", "i": "и", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н",
        "o": "о", "p": "п", "q": "к", "r": "р", "s": "с", "t": "т", "u": "у",
        "v": "в", "w": "в", "x": "кс", "y": "й", "z": "з",
    }
    out = []
    for ch in res:
        if ch in DIGITS_MAP:
            out.append(f" {DIGITS_MAP[ch]} ")
        elif ch in latin_chars:
            out.append(latin_chars[ch])
        else:
            out.append(ch)

    cleaned = re.sub(r"\s+", " ", "".join(out)).strip()
    if not re.search(r"[а-яё]", cleaned):
        return "Готово."
    return cleaned


class TextToSpeech:
    def __init__(self, use_intercom_effect: bool = False, speaker: str = "eugene"):
        self.speaker = speaker
        self.sample_rate = 48000
        self._current_sound = None

        print(f"[TTS] Загрузка нейросети голоса (спикер: {self.speaker})...")
        try:
            self.model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_tts",
                language="ru",
                speaker="v5_ru",
            )
        except Exception:
            self.model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-models",
                model="silero_tts",
                language="ru",
                speaker="v4_ru",
            )
        self.model.to(torch.device("cpu"))

        # Прогрев словаря ударений
        _ = self.model.apply_tts(
            text="Система готова.",
            speaker=self.speaker,
            sample_rate=self.sample_rate,
            put_accent=True,
            put_yo=True,
        )

        pygame.mixer.init(frequency=self.sample_rate, size=-16, channels=1)

        self._queue: queue.Queue[str] = queue.Queue()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        print(f"[TTS] In-Memory аудиодвижок ({self.speaker}) готов.")

    def is_speaking(self) -> bool:
        return pygame.mixer.get_init() is not None and pygame.mixer.get_busy()

    def stop(self):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break

        if self.is_speaking():
            pygame.mixer.stop()

    def speak(self, text: str, blocking: bool = False):
        if not text or not text.strip():
            return

        self.stop()
        self._queue.put(text.strip())

        if blocking:
            self._queue.join()

    def _tensor_to_wav_bytes(self, audio_tensor: torch.Tensor) -> io.BytesIO:
        """Конвертирует аудио-тензор в WAV-буфер прямо в оперативной памяти (без записи на диск)."""
        audio_np = audio_tensor.numpy()
        pcm_int16 = np.clip(audio_np * 32767.0, -32768, 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16 бит = 2 байта
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm_int16.tobytes())
        buf.seek(0)
        return buf

    def _worker_loop(self):
        while True:
            text = self._queue.get()
            try:
                t0 = time.perf_counter()
                norm_text = normalize_for_silero(text)

                audio_tensor = self.model.apply_tts(
                    text=norm_text,
                    speaker=self.speaker,
                    sample_rate=self.sample_rate,
                    put_accent=True,
                    put_yo=True,
                )

                wav_buffer = self._tensor_to_wav_bytes(audio_tensor)
                synth_sec = time.perf_counter() - t0
                print(f"[Тайминг TTS] Синтез в ОЗУ занял: {synth_sec:.2f} сек.")

                sound = pygame.mixer.Sound(file=wav_buffer)
                self._current_sound = sound
                channel = sound.play()
                while channel is not None and channel.get_busy():
                    time.sleep(0.03)

            except Exception as e:
                print(f"[TTS] Ошибка синтеза/воспроизведения: {e}")
            finally:
                self._queue.task_done()
