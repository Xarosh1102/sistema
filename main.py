import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def _setup_background_streams():
    """Перенаправляет stdout/stderr в лог-файл при запуске через pythonw.exe."""
    logs_dir = BASE_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    bg_log_path = logs_dir / "background_console.log"

    if sys.stdout is None or sys.stderr is None:
        log_file = open(bg_log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_file
        sys.stderr = log_file
    else:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_background_streams()

import time
import ctypes
import threading
import winreg as reg

from config.settings import LOGS_DIR
from utils.logger import log
from utils.autostart import create_silent_launchers
from utils.tg_bot import run_telegram_bot
from core.memory import MemoryManager
from core.agent import AgentCore
from tools import REGISTERED_TOOLS
from audio.listener import AudioListener
from audio.stt import SpeechToText
from audio.tts import TextToSpeech
from audio.wake_word import WakeWordFilter
from ui.tray import SystemTrayIcon

_APP_MUTEX = None


def _acquire_single_instance_mutex() -> bool:
    global _APP_MUTEX
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    is_restarting = "--restarting" in sys.argv
    attempts = 20 if is_restarting else 1

    for _ in range(attempts):
        mutex = kernel32.CreateMutexW(None, False, "Local\\SistemaVoiceAssistantMutex")
        last_err = ctypes.get_last_error()
        if last_err != 183:
            _APP_MUTEX = mutex
            return True
        kernel32.CloseHandle(mutex)
        if is_restarting:
            time.sleep(0.3)

    return False


def _remove_duplicate_registry_autorun():
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_ALL_ACCESS) as key:
            reg.DeleteValue(key, "JarvisTelegramBot")
    except FileNotFoundError:
        pass
    except Exception:
        pass


def main():
    if not _acquire_single_instance_mutex():
        print("[Джарвис] Ассистент уже запущен в фоне! Закрываю дубликат.")
        sys.exit(0)

    _remove_duplicate_registry_autorun()
    try:
        vbs_path = create_silent_launchers()
        print(f"[Джарвис] Фоновый лаунчер автозагрузки обновлен: {vbs_path}")
    except Exception as e:
        log.warning(f"Не удалось обновить лаунчер автозагрузки: {e}")

    log.info("=== Запуск голосового ассистента «Джарвис» ===")

    state = {
        "muted": False,
        "running": True,
    }

    memory = MemoryManager()
    agent = AgentCore(memory=memory, extra_tools=REGISTERED_TOOLS)

    # Включаем фирменный голос Джарвиса с DSP-эффектом шлема/интеркома
    tts = TextToSpeech(use_intercom_effect=True)
    stt = SpeechToText()

    # Строгий режим: всегда требует кодовое слово «Джарвис»
    wake_filter = WakeWordFilter(active_window_sec=0.0)

    listener = AudioListener(on_speech_start=lambda: tts.stop())

    tg_thread = threading.Thread(target=run_telegram_bot, args=(agent, stt), daemon=True)
    tg_thread.start()

    def toggle_mute():
        state["muted"] = not state["muted"]
        status = "Микрофон выключен (Mute)" if state["muted"] else "Микрофон включен"
        print(f"[Джарвис] {status}")
        log.info(status)

    def clear_mem():
        memory.clear_short_term()
        print("[Джарвис] Краткосрочная память диалога очищена.")
        log.info("Краткосрочная память очищена через трей.")

    def stop_app():
        print("[Джарвис] Завершение работы ассистента...")
        state["running"] = False
        tts.stop()
        os._exit(0)

    tray = SystemTrayIcon(
        on_toggle_mute=toggle_mute,
        on_clear_memory=clear_mem,
        on_exit=stop_app,
    )
    tray.start_in_background()

    print("[Джарвис] К вашим услугам, сэр! Скажите «Джарвис, ...» для команды.")

    while state["running"]:
        if state["muted"]:
            time.sleep(0.3)
            continue

        try:
            audio_data = listener.listen_phrase()
            if audio_data is None or state["muted"]:
                continue

            raw_text = stt.transcribe(audio_data)
            if not raw_text:
                continue

            print(f"[Слух] Распознано: {raw_text}")

            should_run, command, is_stop = wake_filter.extract_command(raw_text)

            if is_stop:
                tts.stop()
                print("[Джарвис] Озвучка остановлена по команде.")
                continue

            if not should_run:
                continue

            if not command:
                tts.speak("К вашим услугам, сэр.", blocking=True)
                continue

            log.info(f"Команда пользователя: {command}")
            print(f"[Команда] Выполняю: {command}")

            answer = agent.process_command(command)
            print(f"[Ответ Джарвиса] {answer}")
            log.info(f"Ответ Джарвиса: {answer}")

            tts.speak(answer, blocking=True)
            wake_filter.keep_alive()

        except KeyboardInterrupt:
            stop_app()
        except Exception as e:
            log.error(f"Ошибка в основном цикле: {e}")
            time.sleep(0.5)


if __name__ == "__main__":
    main()