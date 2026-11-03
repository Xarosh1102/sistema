import re
import time
from difflib import SequenceMatcher
from config.settings import WAKE_WORDS, STOP_WORDS


class WakeWordFilter:
    def __init__(self, active_window_sec: float = 0.0):
        self.active_window_sec = active_window_sec
        self.last_active_time = 0.0

    def keep_alive(self):
        if self.active_window_sec > 0:
            self.last_active_time = time.time()

    @staticmethod
    def _is_fuzzy_jarvis(word: str) -> bool:
        """Проверяет, похоже ли слово по звучанию на «Джарвис» или «Jarvis»."""
        w = re.sub(r"[^а-яёa-z]", "", word.lower())
        if len(w) < 4:
            return False
        for target in ("джарвис", "жарвис", "jarvis"):
            if SequenceMatcher(None, w, target).ratio() >= 0.62:
                return True
        return False

    def extract_command(self, raw_text: str) -> tuple[bool, str, bool]:
        """
        Проверяет наличие слова «Джарвис» (точно или по фонетическому сходству) или стоп-слов.
        Возвращает кортеж: (нужно_ли_выполнять, текст_команды, это_стоп_команда).
        """
        if not raw_text:
            return False, "", False

        clean = raw_text.strip()
        low = clean.lower().strip(" .,!?-")

        # 1. Проверка быстрых стоп-команд («Джарвис, стоп», «замолчи», «тихо»)
        for stop_w in STOP_WORDS:
            if low == stop_w or re.search(rf"\b{re.escape(stop_w)}\b", low):
                if any(w in low for w in WAKE_WORDS) or low in STOP_WORDS:
                    return False, "", True

        # 2. Точный поиск кодового слова «Джарвис» в любой части фразы
        for wake in WAKE_WORDS:
            pattern = rf"\b{re.escape(wake)}\b[\s,!.:;-]*(.*)"
            match = re.search(pattern, clean, flags=re.IGNORECASE)
            if match:
                command_part = match.group(1).strip(" .,!?-")
                self.keep_alive()
                return True, command_part, False

        # 3. Нечеткое (Fuzzy) сравнение первого слова фразы, если Whisper слегка исказил «Джарвис»
        tokens = clean.split(maxsplit=1)
        if tokens and self._is_fuzzy_jarvis(tokens[0]):
            command_part = tokens[1].strip(" .,!?-") if len(tokens) > 1 else ""
            self.keep_alive()
            return True, command_part, False

        # 4. Если активно временное окно диалога (при active_window_sec > 0)
        if self.active_window_sec > 0 and (time.time() - self.last_active_time) <= self.active_window_sec:
            self.keep_alive()
            return True, clean, False

        return False, "", False