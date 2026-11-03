from pathlib import Path
import numpy as np
import soundfile as sf
from scipy import signal


def apply_jarvis_effect(input_path: Path, output_path: Path) -> Path:
    """
    Накладывает легкий эффект интеркома/HUD (фильтрация частот + короткое фазовое эхо).
    Если обработка не удалась, возвращает исходный файл.
    """
    try:
        data, samplerate = sf.read(str(input_path), dtype="float32")
        if data.ndim > 1:
            data = np.mean(data, axis=1)

        # 1. Полосовой фильтр (срезаем глухие низы ниже 180 Гц и резкий песок выше 6500 Гц)
        nyquist = 0.5 * samplerate
        low = 180.0 / nyquist
        high = min(6500.0 / nyquist, 0.99)
        b, a = signal.butter(2, [low, high], btype="band")
        filtered = signal.lfilter(b, a, data)

        # 2. Короткая задержка (12 мс) с малым весом для эффекта "кабины/шлема"
        delay_samples = int(0.012 * samplerate)
        delayed = np.zeros_like(filtered)
        delayed[delay_samples:] = filtered[:-delay_samples]
        mixed = filtered + 0.18 * delayed

        # 3. Мягкая сатурация и нормализация громкости
        saturated = np.tanh(mixed * 1.15)
        max_val = np.max(np.abs(saturated))
        if max_val > 0:
            saturated = (saturated / max_val) * 0.9

        sf.write(str(output_path), saturated, samplerate, subtype="PCM_16")
        return output_path
    except Exception as e:
        print(f"[AudioEffects] Предупреждение (используется чистый голос): {e}")
        return input_path