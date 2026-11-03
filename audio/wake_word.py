import re
import time
from typing import Tuple

from config.settings import WAKE_WORDS

STOP_COMMANDS = ("стоп", "тихо", "замолчи", "хватит", "отмена", "пауза")


class WakeWordFilter:
    def __init__(self, active_window_sec: float = 0.0):
        """
        active_window_sec=0.0 означает СТРОГИЙ режим: ассистент срабатывает ТОЛЬКО при наличии слова 'Система'.
        Любые разговоры в комнате или звук из телевизора без слова 'Система' игнорируются на 100%.
        """
        self.active_window_sec = active_window_sec
        self.last_interaction_time: float = 0.0

    def keep_alive(self):
        self.last_interaction_time = time.time()

    def reset_session(self):
        self.last_interaction_time = 0.0

    def is_session_active(self) -> bool:
        if self.active_window_sec <= 0:
            return False
        return (time.time() - self.last_interaction_time) <= self.active_window_sec

    def extract_command(self, raw_text: str) -> Tuple[bool, str, bool]:
        if not raw_text:
            return False, "", False

        clean = raw_text.strip()
        lower = clean.lower()

        clean_words = re.sub(r"[^\w\s]", "", lower).split()
        if clean_words and clean_words[0] in STOP_COMMANDS and len(clean_words) <= 3:
            return True, "стоп", True

        for wake in WAKE_WORDS:
            pattern = rf"\b{re.escape(wake)}\b[\s,.:;!\?-]*(.*)"
            match = re.search(pattern, clean, flags=re.IGNORECASE)
            if match:
                command_part = match.group(1).strip()
                self.keep_alive()
                return True, (command_part if command_part else "ты тут?"), False

        if self.is_session_active():
            self.keep_alive()
            return True, clean, False

        return False, "", False
