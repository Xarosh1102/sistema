import queue
import collections
import numpy as np
import sounddevice as sd
import torch

from config.settings import (
    SAMPLE_RATE,
    CHANNELS,
    CHUNK_SAMPLES,
    VAD_THRESHOLD,
    MIN_SPEECH_RMS,
    PRE_ROLL_MS,
    SILENCE_TIMEOUT_MS,
    MIN_SPEECH_MS,
    MAX_SPEECH_SECONDS,
)


class AudioListener:
    def __init__(self, on_speech_start=None):
        self.on_speech_start = on_speech_start
        self.audio_queue = queue.Queue()

        print("[Audio] Загрузка модели Silero VAD...")
        self.vad_model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
            trust_repo=True,
        )
        self.vad_model.eval()

        # Адаптивный уровень фонового шума комнаты
        self.noise_floor = 0.0010

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            pass
        self.audio_queue.put(indata[:, 0].copy())

    def _is_close_voice(self, chunk: np.ndarray, is_speaking: bool = False) -> tuple[bool, float]:
        """
        Проверяет, принадлежит ли звук голосу пользователя, а не фоновому телевизору.
        Если речь уже началась (is_speaking=True), порог удерживания мягче, чтобы не терять окончания слов.
        """
        rms = float(np.sqrt(np.mean(np.square(chunk)) + 1e-12))
        peak = float(np.max(np.abs(chunk)) + 1e-12)
        crest_factor = peak / rms  # У живого близкого голоса выраженные пики, у далекого ТВ звук "плоский"

        if not is_speaking:
            # Плавное обновление уровня фонового шума в тишине
            if rms < MIN_SPEECH_RMS * 1.2:
                self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms

            # Для старта фразы голос должен быть выше минимального порога и заметно громче фона
            min_required = max(MIN_SPEECH_RMS, self.noise_floor * 1.7)
            return (rms >= min_required and crest_factor >= 1.8), rms
        else:
            # Когда ты уже говоришь, позволяем голосу становиться тише на концах слов
            hold_rms = max(MIN_SPEECH_RMS * 0.45, self.noise_floor * 1.2)
            return (rms >= hold_rms), rms

    def listen_phrase(self) -> np.ndarray | None:
        chunk_ms = (CHUNK_SAMPLES / SAMPLE_RATE) * 1000.0
        pre_roll_chunks = max(1, int(PRE_ROLL_MS / chunk_ms))
        silence_limit_chunks = max(1, int(SILENCE_TIMEOUT_MS / chunk_ms))
        min_speech_chunks = max(1, int(MIN_SPEECH_MS / chunk_ms))
        max_total_chunks = int((MAX_SPEECH_SECONDS * 1000.0) / chunk_ms)

        pre_roll_buffer = collections.deque(maxlen=pre_roll_chunks)
        recorded_chunks = []

        is_speaking = False
        speech_chunks_count = 0
        silence_chunks_count = 0

        # Очищаем очередь перед новым циклом прослушивания
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        self.vad_model.reset_states()

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=CHUNK_SAMPLES,
            callback=self._audio_callback,
        ):
            while True:
                chunk = self.audio_queue.get()

                if len(chunk) < CHUNK_SAMPLES:
                    chunk = np.pad(chunk, (0, CHUNK_SAMPLES - len(chunk)))

                close_ok, _ = self._is_close_voice(chunk, is_speaking=is_speaking)

                # Считаем вероятность речи через Silero VAD
                tensor_chunk = torch.from_numpy(chunk)
                with torch.no_grad():
                    speech_prob = float(self.vad_model(tensor_chunk, SAMPLE_RATE).item())

                # Для старта фразы нужен VAD >= VAD_THRESHOLD, для продолжения — мягче (0.7 от порога)
                active_vad_threshold = VAD_THRESHOLD if not is_speaking else (VAD_THRESHOLD * 0.70)
                is_voice_chunk = close_ok and (speech_prob >= active_vad_threshold)

                if not is_speaking:
                    pre_roll_buffer.append(chunk)
                    if is_voice_chunk:
                        is_speaking = True
                        speech_chunks_count = 1
                        silence_chunks_count = 0
                        recorded_chunks.extend(pre_roll_buffer)
                        if self.on_speech_start:
                            try:
                                self.on_speech_start()
                            except Exception:
                                pass
                else:
                    recorded_chunks.append(chunk)
                    if is_voice_chunk:
                        speech_chunks_count += 1
                        silence_chunks_count = 0
                    else:
                        silence_chunks_count += 1

                    # Завершаем запись, если наступила пауза или превышен лимит времени
                    if silence_chunks_count >= silence_limit_chunks or len(recorded_chunks) >= max_total_chunks:
                        break

        if speech_chunks_count < min_speech_chunks:
            return None

        return np.concatenate(recorded_chunks, axis=0)