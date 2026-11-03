import queue
from collections import deque
import numpy as np
import sounddevice as sd
import torch

from config.settings import (
    SAMPLE_RATE,
    CHANNELS,
    CHUNK_SAMPLES,
    VAD_THRESHOLD,
    SILENCE_LIMIT_SEC,
    PRE_ROLL_SEC,
    MAX_RECORD_SECONDS,
    MIN_SPEECH_RMS,
    MIN_SPEECH_DURATION_SEC,
)


class AudioListener:
    def __init__(self, on_speech_start=None):
        self.on_speech_start = on_speech_start
        self.sample_rate = SAMPLE_RATE
        self.chunk_samples = CHUNK_SAMPLES
        self.vad_threshold = VAD_THRESHOLD
        self.silence_limit_sec = SILENCE_LIMIT_SEC
        self.pre_roll_sec = PRE_ROLL_SEC
        self.max_record_seconds = MAX_RECORD_SECONDS
        self.min_speech_rms = MIN_SPEECH_RMS
        self.min_speech_duration_sec = MIN_SPEECH_DURATION_SEC

        print("[VAD] Загрузка нейросетевого фильтра голоса Silero VAD...")
        torch.set_num_threads(1)
        self.vad_model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
            trust_repo=True,
        )
        self.vad_model.eval()
        print("[VAD] Модуль прослушивания готов!")

    def _get_speech_prob(self, chunk: np.ndarray) -> float:
        tensor_chunk = torch.from_numpy(chunk).float()
        if tensor_chunk.ndim > 1:
            tensor_chunk = tensor_chunk.squeeze()
        with torch.no_grad():
            prob = self.vad_model(tensor_chunk, self.sample_rate).item()
        return float(prob)

    def listen_phrase(self) -> np.ndarray | None:
        """
        Слушает микрофон с увеличенным буфером предзаписи (0.65 сек),
        чтобы первый слог слова «Джарвис» никогда не обрезался.
        """
        audio_queue: queue.Queue[np.ndarray] = queue.Queue()

        def audio_callback(indata, frames, time_info, status):
            audio_queue.put(indata[:, 0].copy())

        chunk_duration = self.chunk_samples / float(self.sample_rate)
        pre_roll_maxlen = max(4, int(self.pre_roll_sec / chunk_duration))
        pre_roll_buffer = deque(maxlen=pre_roll_maxlen)

        recorded_chunks = []
        speech_started = False
        silence_time = 0.0
        total_record_time = 0.0
        speech_chunks_count = 0

        self.vad_model.reset_states()

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype="float32",
            blocksize=self.chunk_samples,
            callback=audio_callback,
        ):
            while True:
                try:
                    chunk = audio_queue.get(timeout=1.0)
                except queue.Empty:
                    if speech_started:
                        break
                    continue

                if len(chunk) != self.chunk_samples:
                    continue

                rms = float(np.sqrt(np.mean(chunk ** 2)))
                prob = self._get_speech_prob(chunk)
                is_speech = (prob >= self.vad_threshold) or (prob >= 0.25 and rms >= self.min_speech_rms * 1.5)

                if not speech_started:
                    pre_roll_buffer.append(chunk)
                    if is_speech and rms >= self.min_speech_rms:
                        speech_started = True
                        speech_chunks_count = 1
                        silence_time = 0.0
                        recorded_chunks.extend(pre_roll_buffer)
                        total_record_time = len(recorded_chunks) * chunk_duration
                        if callable(self.on_speech_start):
                            try:
                                self.on_speech_start()
                            except Exception:
                                pass
                else:
                    recorded_chunks.append(chunk)
                    total_record_time += chunk_duration

                    if is_speech:
                        speech_chunks_count += 1
                        silence_time = 0.0
                    else:
                        silence_time += chunk_duration

                    if silence_time >= self.silence_limit_sec or total_record_time >= self.max_record_seconds:
                        break

        if not recorded_chunks:
            return None

        speech_duration = speech_chunks_count * chunk_duration
        if speech_duration < self.min_speech_duration_sec:
            return None

        full_audio = np.concatenate(recorded_chunks).astype(np.float32)
        overall_rms = float(np.sqrt(np.mean(full_audio ** 2)))
        if overall_rms < self.min_speech_rms * 0.4:
            return None

        # Добавляем 0.2 сек тишины в начало и конец, чтобы Whisper не «съедал» первое слово «Джарвис»
        pad = np.zeros(int(self.sample_rate * 0.20), dtype=np.float32)
        return np.concatenate([pad, full_audio, pad])