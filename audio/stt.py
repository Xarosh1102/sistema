import re
from pathlib import Path
import numpy as np
import av
from faster_whisper import WhisperModel
from config.settings import (
    WHISPER_MODEL_SIZE,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    SAMPLE_RATE,
)


class SpeechToText:
    def __init__(self):
        print(f"[STT] Загрузка модели Whisper ({WHISPER_MODEL_SIZE})...")
        self.model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
            cpu_threads=4,
        )
        try:
            dummy_audio = np.zeros(SAMPLE_RATE // 2, dtype=np.float32)
            list(self.model.transcribe(dummy_audio, language="ru", beam_size=1))
            print("[STT] Модель Whisper прогрета!")
        except Exception as e:
            print(f"[STT] Предупреждение: {e}")

    @staticmethod
    def _normalize_audio(audio_data: np.ndarray) -> np.ndarray:
        audio = audio_data.astype(np.float32)
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio = audio / max_val * 0.95
        return audio

    def _apply_phonetic_fixes(self, text: str) -> str:
        if not text:
            return ""
        replacements = {
            r"\bжарвис\b": "джарвис",
            r"\bдарвис\b": "джарвис",
            r"\bгарвис\b": "джарвис",
            r"\bярвис\b": "джарвис",
            r"\bчарвис\b": "джарвис",
            r"\bчарлиз\b": "джарвис",
            r"\bджарвиз\b": "джарвис",
            r"\bджарвес\b": "джарвис",
            r"\bджарви\b": "джарвис",
            r"\bджэрвис\b": "джарвис",
            r"\bjarvis\b": "джарвис",
        }
        fixed = text
        for pattern, repl in replacements.items():
            fixed = re.sub(pattern, repl, fixed, flags=re.IGNORECASE)
        return fixed.strip()

    def transcribe(self, audio_data: np.ndarray) -> str:
        if audio_data is None or len(audio_data) == 0:
            return ""
        norm_audio = self._normalize_audio(audio_data)
        segments, _ = self.model.transcribe(
            norm_audio,
            language="ru",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,
            initial_prompt="Джарвис, открой, закрой, громкость, режим кодинга, перезапуск.",
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return self._apply_phonetic_fixes(text)

    def transcribe_file(self, file_path: str | Path) -> str:
        path_str = str(file_path)
        if not Path(path_str).exists():
            return ""
        container = None
        try:
            container = av.open(path_str)
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            chunks = []
            for frame in container.decode(audio=0):
                frame.pts = None
                resampled = resampler.resample(frame)
                if resampled:
                    frame_list = resampled if isinstance(resampled, list) else [resampled]
                    for r_frame in frame_list:
                        arr = np.frombuffer(bytes(r_frame.planes[0]), dtype=np.int16)
                        chunks.append(arr)
            if not chunks:
                return ""
            audio_np = np.concatenate(chunks).astype(np.float32) / 32768.0
            return self.transcribe(audio_np)
        except Exception as e:
            print(f"[STT] Ошибка декодирования аудиофайла: {e}")
            return ""
        finally:
            if container is not None:
                try:
                    container.close()
                except Exception:
                    pass