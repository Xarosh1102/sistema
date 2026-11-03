import os
import json
import time
import ctypes
import subprocess
from pathlib import Path
import psutil
import pyautogui

from config.settings import DATA_DIR
from tools.base import register_tool
from tools.os_system import maximize_window_by_hint

pyautogui.FAILSAFE = False

MACROS_FILE = DATA_DIR / "macros.json"

ASTAR_ONGOING_SCHEDULE_URL = "https://v1.astar.bz/raspisanie-vyhoda-seriy-ongoingov.html"
GEMINI_URL = "https://gemini.google.com/app"

SYSTEM_PROTECTED_PROCESSES = {
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe",
    "lsass.exe", "svchost.exe", "fontdrvhost.exe", "winlogon.exe", "dwm.exe",
    "explorer.exe", "taskhostw.exe", "sihost.exe", "ctfmon.exe", "conhost.exe",
    "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "textinputhost.exe", "audiodg.exe", "dllhost.exe",
    "securityhealthsystray.exe", "securityhealthservice.exe", "spoolsv.exe",
    "python.exe", "pythonw.exe",
}


def _get_visible_window_pids() -> set[int]:
    pids = set()
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    current_pid = os.getpid()

    def enum_cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value and pid.value != current_pid:
                pids.add(pid.value)
        return True

    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    return pids


def _close_apps_except(allowed_names: set[str]):
    """Закрывает все открытые приложения (включая Терминал и Диспетчер задач), кроме разрешенных."""
    allowed_lower = {name.lower() for name in allowed_names} | SYSTEM_PROTECTED_PROCESSES
    visible_pids = _get_visible_window_pids()
    current_pid = os.getpid()

    common_user_apps = {
        "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe",
        "code.exe", "telegram.exe", "whatsapp.exe", "whatsapp.root.exe",
        "discord.exe", "steam.exe", "epicgameslauncher.exe", "robloxplayerbeta.exe",
        "notepad.exe", "winword.exe", "excel.exe", "powerpnt.exe",
        "vlc.exe", "mpc-hc64.exe", "spotify.exe", "qbittorrent.exe",
        "windowsterminal.exe", "powershell.exe", "cmd.exe", "openconsole.exe", "taskmgr.exe",
    }

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            pid = proc.info["pid"]
            name = (proc.info["name"] or "").lower()

            if not name or pid == current_pid or name in allowed_lower:
                continue

            if pid in visible_pids or name in common_user_apps:
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    no_win = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for sys_tool in ("Taskmgr.exe", "WindowsTerminal.exe", "powershell.exe", "cmd.exe"):
        if sys_tool.lower() not in allowed_lower:
            subprocess.run(
                f"taskkill /F /IM {sys_tool} /T",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=no_win,
            )


def _set_system_volume_percent(target_percent: int):
    target_percent = max(0, min(100, target_percent))
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMute(0, None)
        volume.SetMasterVolumeLevelScalar(target_percent / 100.0, None)
        return
    except Exception:
        pass

    try:
        for _ in range(50):
            pyautogui.press("volumedown")
        steps_up = round(target_percent / 2)
        for _ in range(steps_up):
            pyautogui.press("volumeup")
    except Exception as e:
        print(f"[Macros] Ошибка регулировки громкости: {e}")


def _find_chrome_exe() -> str:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "chrome"


def _restart_chrome_with_urls(urls: list[str]):
    """
    Если Chrome открыт — полностью закрывает его (без ошибки восстановления сессии),
    а затем открывает чистый Chrome во весь экран ТОЛЬКО с указанными вкладками.
    """
    no_win = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    # 1. Сначала отправляем мягкое закрытие окна, чтобы Chrome не считал это аварийным сбоем
    subprocess.run(
        "taskkill /IM chrome.exe",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=no_win,
    )
    time.sleep(0.35)

    # 2. Принудительно завершаем все оставшиеся фоновые процессы Chrome
    subprocess.run(
        "taskkill /F /IM chrome.exe /T",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=no_win,
    )
    time.sleep(0.45)

    # 3. Запускаем чистый Chrome во весь экран только с нужными ссылками
    chrome_exe = _find_chrome_exe()
    if chrome_exe != "chrome":
        subprocess.Popen([chrome_exe, "--start-maximized", "--new-window", *urls])
    else:
        quoted_urls = " ".join(f'"{u}"' for u in urls)
        subprocess.Popen(f"start /max chrome --start-maximized --new-window {quoted_urls}", shell=True)

    maximize_window_by_hint("chrome", timeout=3.5)


def _launch_vscode_maximized():
    vscode_paths = [
        Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Microsoft VS Code/Code.exe",
    ]
    launched = False
    for p in vscode_paths:
        if p.exists():
            subprocess.Popen([str(p)])
            launched = True
            break
    if not launched:
        subprocess.Popen("start /max code", shell=True)
    maximize_window_by_hint("code", timeout=3.5)


def _run_coding_mode() -> str:
    # 1. Закрываем всё лишнее (Chrome тоже будет перезапущен с нуля)
    allowed = {
        "telegram.exe",
        "whatsapp.exe",
        "whatsapp.root.exe",
        "explorer.exe",
        "code.exe",
    }
    _close_apps_except(allowed)

    # 2. Выставляем громкость на 25%
    _set_system_volume_percent(25)

    # 3. Открываем VS Code во весь экран
    _launch_vscode_maximized()

    # 4. Закрываем старый Chrome (если был открыт) и открываем чистый только с 2 вкладками Gemini
    _restart_chrome_with_urls([GEMINI_URL, GEMINI_URL])

    return "Режим кодинга запущен: лишние программы закрыты, громкость 25 процентов, открыты VS Code и чистый Chrome с двумя вкладками Gemini во весь экран."


def _run_chill_mode() -> str:
    # 1. Закрываем абсолютно все приложения, кроме WhatsApp и Проводника
    allowed = {
        "whatsapp.exe",
        "whatsapp.root.exe",
        "explorer.exe",
    }
    _close_apps_except(allowed)

    # 2. Закрываем старый Chrome (если был открыт) и открываем чистый только с сайтом Anistar во весь экран
    _restart_chrome_with_urls([ASTAR_ONGOING_SCHEDULE_URL])

    return "Режим отдыха активирован: все лишние программы и старые вкладки закрыты, открыт сайт Anistar во весь экран."


@register_tool
def run_macro(macro_name: str) -> str:
    """
    Запускает сценарий автоматизации (макрос) по названию.
    Поддерживаемые сценарии:
    - 'режим кодинга' (или 'кодинг', 'за работу')
    - 'отдыхаем' (или 'отдых', 'чилл')
    """
    name = (macro_name or "").strip().lower()

    if any(k in name for k in ("кодинг", "за работу", "учеб", "coding", "work", "программир")):
        return _run_coding_mode()

    if any(k in name for k in ("отдых", "отдыхаем", "чилл", "chill", "аниме", "анистар")):
        return _run_chill_mode()

    if MACROS_FILE.exists():
        try:
            with open(MACROS_FILE, "r", encoding="utf-8") as f:
                custom = json.load(f)
            if name in custom:
                for cmd in custom[name]:
                    subprocess.Popen(cmd, shell=True)
                return f"Сценарий «{name}» выполнен."
        except Exception:
            pass

    return f"Сценарий «{macro_name}» не найден. Доступны сценарии: «Режим кодинга» и «Отдыхаем»."


@register_tool
def list_macros() -> str:
    """Возвращает список всех доступных макросов и сценариев."""
    base = [
        "1. «Режим кодинга» — закрывает лишнее, ставит звук на 25%, запускает VS Code и перезапускает Chrome ровно с 2 вкладками Gemini во весь экран.",
        "2. «Отдыхаем» — закрывает всё кроме WhatsApp и перезапускает Chrome во весь экран с расписанием серий на Anistar.",
    ]
    return "\n".join(base)


@register_tool
def add_custom_macro(name: str, command: str) -> str:
    """Добавляет пользовательский макрос."""
    MACROS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if MACROS_FILE.exists():
        try:
            with open(MACROS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data[name.strip().lower()] = [command]
    with open(MACROS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return f"Пользовательский макрос «{name}» сохранен."