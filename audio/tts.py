import asyncio
import os
import random
import tempfile
import threading
from pathlib import Path

import edge_tts
import numpy as np
import pygame

from config.settings import DATA_DIR


class TextToSpeech:
    def __init__(
        self,
        use_intercom_effect: bool = True,
        speaker: str = "eugene",
        voice: str = "ru-RU-DmitryNeural",
        rate: str = "+6%",
        pitch: str = "-6Hz",
    ):
        self.use_intercom_effect = use_intercom_effect
        self.speaker = speaker
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self._lock = threading.Lock()
        self._stop_requested = False

        # Папка для оригинальных фраз Джарвиса из фильма (по желанию)
        self.sounds_dir = DATA_DIR / "jarvis_sounds"
        self.sounds_dir.mkdir(parents=True, exist_ok=True)

        # Карта быстрых фраз -> файлов в data/jarvis_sounds/
        self.phrase_samples = {
            "да, сэр?": ["yes_sir.wav", "yes_sir.mp3", "at_your_service.wav"],
            "да, слушаю?": ["yes_sir.wav", "yes_sir.mp3"],
            "к вашим услугам, сэр.": ["at_your_service.wav", "at_your_service.mp3"],
        }

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=512)
        except Exception as e:
            print(f"[TTS] Ошибка инициализации аудиомикшера: {e}")

    def _find_original_sample(self, text: str) -> Path | None:
        key = text.strip().lower()
        candidates = self.phrase_samples.get(key, [])
        existing = [self.sounds_dir / f for f in candidates if (self.sounds_dir / f).exists()]
        if existing:
            return random.choice(existing)
        return None

    async def _synthesize_edge(self, text: str, out_path: str):
        communicate = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
            pitch=self.pitch,
        )
        await communicate.save(out_path)

    @staticmethod
    def _apply_jarvis_helmet_filter(input_mp3: str, output_wav: str) -> bool:
        """Накладывает фирменный эффект интеркома шлема Тони Старка."""
        try:
            import av
            import soundfile as sf
            from scipy.signal import butter, lfilter

            container = av.open(input_mp3)
            resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)
            chunks = []
            for frame in container.decode(audio=0):
                frame.pts = None
                resampled = resampler.resample(frame)
                if resampled:
                    frames = resampled if isinstance(resampled, list) else [resampled]
                    for rf in frames:
                        chunks.append(np.frombuffer(bytes(rf.planes[0]), dtype=np.int16))
            container.close()

            if not chunks:
                return False

            audio = np.concatenate(chunks).astype(np.float32) / 32768.0
            sr = 24000

            # 1. Полосной фильтр (срезаем глухие низы < 180 Гц и резкие верха > 7500 Гц)
            b, a = butter(2, [180 / (sr / 2), 7500 / (sr / 2)], btype="band")
            filtered = lfilter(b, a, audio)

            # 2. Легкая микро-задержка (эффект акустики внутри шлема ~12 мс)
            delay_samples = int(0.012 * sr)
            delayed = np.zeros_like(filtered)
            delayed[delay_samples:] = filtered[:-delay_samples]
            processed = filtered * 0.82 + delayed * 0.22

            # 3. Мягкая компрессия и нормализация
            processed = np.tanh(processed * 1.25)
            max_val = np.max(np.abs(processed))
            if max_val > 0:
                processed = processed / max_val * 0.92

            sf.write(output_wav, processed, sr, subtype="PCM_16")
            return True
        except Exception:
            return False

    def speak(self, text: str, blocking: bool = True):
        clean_text = (text or "").strip()
        if not clean_text:
            return

        print(f"🔹 [ДЖАРВИС]: {clean_text}")

        if blocking:
            self._speak_worker(clean_text)
        else:
            threading.Thread(target=self._speak_worker, args=(clean_text,), daemon=True).start()

    def _speak_worker(self, text: str):
        with self._lock:
            self._stop_requested = False

            # 1. Проверяем, есть ли оригинальный сэмпл из фильма для этой фразы
            sample_path = self._find_original_sample(text)
            if sample_path is not None:
                self._play_file(str(sample_path))
                return

            # 2. Генерируем голос Джарвиса через Edge-TTS + фильтр шлема
            tmp_mp3 = None
            tmp_wav = None
            try:
                fd_mp3, tmp_mp3 = tempfile.mkstemp(suffix=".mp3")
                os.close(fd_mp3)

                asyncio.run(self._synthesize_edge(text, tmp_mp3))

                if self._stop_requested:
                    return

                play_target = tmp_mp3
                if self.use_intercom_effect:
                    fd_wav, tmp_wav = tempfile.mkstemp(suffix=".wav")
                    os.close(fd_wav)
                    if self._apply_jarvis_helmet_filter(tmp_mp3, tmp_wav):
                        play_target = tmp_wav

                self._play_file(play_target)

            except Exception as e:
                print(f"[TTS] Ошибка синтеза речи: {e}")
            finally:
                for p in (tmp_mp3, tmp_wav):
                    if p and os.path.exists(p):
                        try:
                            os.remove(p)
                        except Exception:
                            pass

    def _play_file(self, file_path: str):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            clock = pygame.time.Clock()
            while pygame.mixer.music.get_busy():
                if self._stop_requested:
                    pygame.mixer.music.stop()
                    break
                clock.tick(20)
            pygame.mixer.music.unload()
        except Exception as e:
            print(f"[TTS] Ошибка воспроизведения: {e}")

    def stop(self):
        self._stop_requested = True
        try:
            if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()
        except Exception:
            pass