import os
import re
import sys
import time
import ctypes
import threading
import subprocess
import webbrowser
from pathlib import Path
import psutil
import pyautogui

from tools.base import register_tool

pyautogui.FAILSAFE = False

BASE_DIR = Path(__file__).resolve().parent.parent

CORE_SYSTEM_PROCESSES = {
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe",
    "lsass.exe", "svchost.exe", "fontdrvhost.exe", "winlogon.exe", "dwm.exe",
    "explorer.exe", "taskhostw.exe", "sihost.exe", "ctfmon.exe", "conhost.exe",
    "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "shellexperiencehost.exe", "textinputhost.exe", "audiodg.exe", "dllhost.exe",
    "securityhealthsystray.exe", "securityhealthservice.exe", "spoolsv.exe",
    "python.exe", "pythonw.exe",
}


def maximize_window_by_hint(hint: str = "", timeout: float = 3.0):
    """Ждет появления окна приложения и разворачивает его во весь экран (SW_MAXIMIZE = 3)."""
    def _worker():
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        deadline = time.time() + timeout
        hint_low = (hint or "").lower()

        search_keywords = []
        if any(w in hint_low for w in ("whatsapp", "ватсап", "вацап")):
            search_keywords = ["whatsapp", "ватсап"]
        elif any(w in hint_low for w in ("telegram", "телеграм", "тг")):
            search_keywords = ["telegram", "телеграм"]
        elif any(w in hint_low for w in ("chrome", "хром", "браузер")):
            search_keywords = ["chrome", "google chrome"]
        elif any(w in hint_low for w in ("code", "vscode", "вскод")):
            search_keywords = ["visual studio code", "code.exe"]
        elif hint_low:
            search_keywords = [hint_low]

        while time.time() < deadline:
            time.sleep(0.35)
            found_hwnd = None

            if search_keywords:
                def enum_cb(hwnd, lparam):
                    nonlocal found_hwnd
                    if not user32.IsWindowVisible(hwnd):
                        return True
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length <= 0:
                        return True
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    title = buf.value.lower()

                    pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    pname = ""
                    try:
                        if pid.value:
                            pname = psutil.Process(pid.value).name().lower()
                    except Exception:
                        pass

                    for kw in search_keywords:
                        if kw in title or (pname and kw in pname):
                            found_hwnd = hwnd
                            return False
                    return True

                user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
            else:
                found_hwnd = user32.GetForegroundWindow()

            if found_hwnd:
                try:
                    if user32.IsIconic(found_hwnd):
                        user32.ShowWindow(found_hwnd, 9)
                        time.sleep(0.1)
                    user32.ShowWindow(found_hwnd, 3)  # SW_MAXIMIZE = 3
                    user32.SetForegroundWindow(found_hwnd)
                    break
                except Exception:
                    pass

    threading.Thread(target=_worker, daemon=True).start()


def launch_app_universal(app_name: str) -> tuple[bool, str]:
    """Универсальный поиск, запуск и разворот приложения во весь экран."""
    clean = (app_name or "").strip().lower()
    clean = re.sub(r"\b(приложение|программу|программа|окно|быстро|пожалуйста)\b", "", clean).strip()
    if not clean:
        return False, "Не указано название приложения, сэр."

    # 1. WhatsApp
    if any(w in clean for w in ("whatsapp", "ватсап", "вацап", "ватсапп")):
        subprocess.Popen("start shell:AppsFolder\\5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App", shell=True)
        maximize_window_by_hint("whatsapp", timeout=3.5)
        return True, "Открываю WhatsApp во весь экран, сэр."

    # 2. Telegram
    if any(w in clean for w in ("telegram", "телеграм", "телегу", "тг")):
        tg_paths = [
            Path.home() / "AppData" / "Roaming" / "Telegram Desktop" / "Telegram.exe",
            Path("C:/Program Files/Telegram Desktop/Telegram.exe"),
        ]
        launched = False
        for p in tg_paths:
            if p.exists():
                subprocess.Popen([str(p)])
                launched = True
                break
        if not launched:
            subprocess.Popen("start tg:", shell=True)
        maximize_window_by_hint("telegram", timeout=3.5)
        return True, "Открываю Telegram во весь экран, сэр."

    # 3. Chrome
    if any(w in clean for w in ("chrome", "хром", "браузер")):
        subprocess.Popen("start chrome --start-maximized", shell=True)
        maximize_window_by_hint("chrome", timeout=2.5)
        return True, "Открываю Google Chrome во весь экран, сэр."

    # 4. Стандартные программы
    shortcuts = {
        "code": "code",
        "vscode": "code",
        "вскод": "code",
        "vs code": "code",
        "notepad": "notepad",
        "блокнот": "notepad",
        "calc": "calc",
        "калькулятор": "calc",
        "explorer": "explorer",
        "проводник": "explorer",
        "cmd": "cmd",
        "терминал": "powershell",
        "powershell": "powershell",
    }
    for key, cmd in shortcuts.items():
        if clean == key or key in clean:
            subprocess.Popen(f"start /max {cmd}", shell=True)
            maximize_window_by_hint(key, timeout=3.0)
            return True, f"Запускаю {app_name} во весь экран, сэр."

    # 5. Поиск ярлыков на Рабочем столе и в меню «Пуск»
    search_folders = [
        Path.home() / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
        Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Desktop",
        Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]

    for folder in search_folders:
        if not folder.exists():
            continue
        for item in folder.rglob("*"):
            if item.is_file() and item.suffix.lower() in (".lnk", ".url", ".exe"):
                if clean in item.stem.lower():
                    os.startfile(str(item))
                    maximize_window_by_hint(item.stem, timeout=3.5)
                    return True, f"Запускаю {item.stem} во весь экран, сэр."

    subprocess.Popen(f'start /max "" "{clean}"', shell=True)
    maximize_window_by_hint(clean, timeout=3.0)
    return True, f"Запускаю {app_name} во весь экран, сэр."


@register_tool
def open_application(app_name: str) -> str:
    """
    Открывает приложение или игру и разворачивает окно во весь экран.
    Примеры app_name: 'ватсап', 'телеграм', 'хром', 'вскод', 'калькулятор', 'проводник'.
    """
    _, msg = launch_app_universal(app_name)
    return msg


@register_tool
def close_all_applications() -> str:
    """
    Закрывает абсолютно все открытые пользовательские приложения, включая Терминал, Диспетчер задач, браузеры и мессенджеры.
    """
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    WM_CLOSE = 0x0010
    current_pid = os.getpid()

    visible_pids = set()

    def enum_cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd) > 0:
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value and pid.value != current_pid:
                visible_pids.add(pid.value)
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return True

    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    target_exes = {
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
            if not name or pid == current_pid or name in CORE_SYSTEM_PROCESSES:
                continue
            if pid in visible_pids or name in target_exes:
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    no_win = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for exe in ("Taskmgr.exe", "WindowsTerminal.exe", "Telegram.exe", "WhatsApp.exe", "chrome.exe", "Code.exe"):
        subprocess.run(f"taskkill /F /IM {exe} /T", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=no_win)

    return "Все открытые приложения закрыты, сэр."


@register_tool
def close_application(app_name: str) -> str:
    """
    Принудительно закрывает указанное приложение по названию.
    Примеры app_name: 'телеграм', 'ватсап', 'хром', 'терминал', 'диспетчер задач', 'вскод', 'все приложения'.
    """
    clean = (app_name or "").strip().lower()
    if any(w in clean for w in ("все приложения", "все программы", "все окна", "вообще все", "всё")):
        return close_all_applications()

    clean = re.sub(r"\b(приложение|программу|программа|окно|быстро|пожалуйста)\b", "", clean).strip()

    alias_groups = [
        (("телеграм", "телегу", "тг", "telegram"), ["Telegram.exe"]),
        (("ватсап", "вацап", "ватсапп", "whatsapp"), ["WhatsApp.exe", "WhatsApp.Root.exe"]),
        (("хром", "браузер", "chrome", "гугл"), ["chrome.exe"]),
        (("вскод", "vscode", "vs code", "code", "код"), ["Code.exe"]),
        (("терминал", "консоль", "powershell", "cmd", "командная строка"), ["WindowsTerminal.exe", "powershell.exe", "cmd.exe", "OpenConsole.exe"]),
        (("диспетчер", "taskmgr", "диспетчер задач"), ["Taskmgr.exe"]),
        (("блокнот", "notepad"), ["notepad.exe"]),
        (("роблокс", "roblox"), ["RobloxPlayerBeta.exe"]),
        (("стим", "steam"), ["steam.exe"]),
    ]

    target_exes = []
    for keywords, exes in alias_groups:
        if any(k in clean for k in keywords):
            target_exes.extend(exes)
            break

    no_win = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    killed_count = 0
    current_pid = os.getpid()

    for exe in target_exes:
        res = subprocess.run(
            f"taskkill /F /IM {exe} /T",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=no_win,
        )
        if res.returncode == 0:
            killed_count += 1

    search_token = target_exes[0].replace(".exe", "").lower() if target_exes else clean
    for p in psutil.process_iter(["pid", "name"]):
        try:
            pname = (p.info["name"] or "").lower()
            if p.info["pid"] != current_pid and "python" not in pname:
                if search_token in pname or any(exe.lower() == pname for exe in target_exes):
                    p.kill()
                    killed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    WM_CLOSE = 0x0010

    def enum_cb(hwnd, lparam):
        nonlocal killed_count
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.lower()
                if clean in title or search_token in title:
                    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                    killed_count += 1
        return True

    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    if killed_count > 0:
        return f"Приложение «{app_name.strip()}» закрыто, сэр."
    return f"Запущенное приложение «{app_name.strip()}» не найдено, сэр."


@register_tool
def shutdown_computer() -> str:
    """Выключает компьютер (ноутбук) через завершение работы Windows с таймером 10 секунд."""
    no_win = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen("shutdown /s /t 10", shell=True, creationflags=no_win)
    return "Выполняю завершение работы компьютера, сэр. Отключение через 10 секунд."


@register_tool
def reboot_computer() -> str:
    """Перезапускает (перезагружает) компьютер (Windows) с таймером 10 секунд."""
    no_win = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen("shutdown /r /t 10", shell=True, creationflags=no_win)
    return "Выполняю перезагрузку компьютера, сэр. Перезапуск через 10 секунд."


@register_tool
def cancel_shutdown() -> str:
    """Отменяет запланированное выключение или перезагрузку компьютера."""
    no_win = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen("shutdown /a", shell=True, creationflags=no_win)
    return "Выключение или перезагрузка компьютера отменены, сэр."


@register_tool
def restart_assistant_system() -> str:
    """Перезапускает сам голосовой ассистент «Джарвис» и Telegram-бота для применения нового кода."""
    def _delayed_restart():
        time.sleep(2.0)

        pythonw_candidates = [
            BASE_DIR / "venv" / "Scripts" / "pythonw.exe",
            BASE_DIR / ".venv" / "Scripts" / "pythonw.exe",
            Path(sys.executable).parent / "pythonw.exe",
            Path(sys.executable),
        ]
        exe_path = next((p.resolve() for p in pythonw_candidates if p.exists()), Path(sys.executable).resolve())
        main_py = (BASE_DIR / "main.py").resolve()

        creation_flags = 0
        if os.name == "nt":
            creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

        subprocess.Popen(
            [str(exe_path), str(main_py), "--restarting"],
            cwd=str(BASE_DIR),
            creationflags=creation_flags,
            close_fds=True,
        )
        os._exit(0)

    threading.Thread(target=_delayed_restart, daemon=True).start()
    return "Выполняю перезапуск системы Джарвиса, сэр. Вернусь через пару секунд."


@register_tool
def adjust_system_volume(level_percent: int) -> str:
    """Устанавливает громкость звука компьютера в процентах (от 0 до 100)."""
    target = max(0, min(100, int(level_percent)))
    try:
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMute(0, None)
        volume.SetMasterVolumeLevelScalar(target / 100.0, None)
        return f"Громкость установлена на {target} процентов, сэр."
    except Exception:
        for _ in range(50):
            pyautogui.press("volumedown")
        for _ in range(round(target / 2)):
            pyautogui.press("volumeup")
        return f"Громкость выставлена на {target} процентов, сэр."


@register_tool
def minimize_all_windows() -> str:
    """
    Сворачивает все открытые окна на рабочий стол через аппаратные виртуальные коды клавиш Win + D.
    Работает безотказно на Windows 11 независимо от текущей раскладки клавиатуры (РУС/ENG).
    """
    user32 = ctypes.windll.user32
    VK_LWIN = 0x5B
    VK_D = 0x44
    KEYEVENTF_KEYUP = 0x0002

    user32.keybd_event(VK_LWIN, 0, 0, 0)
    user32.keybd_event(VK_D, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(VK_D, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
    return "Все окна свернуты, сэр."


@register_tool
def open_website(url: str) -> str:
    """Открывает указанный сайт в браузере во весь экран."""
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        clean_url = "https://" + clean_url
    webbrowser.open(clean_url)
    maximize_window_by_hint("chrome", timeout=2.5)
    return f"Открываю сайт во весь экран, сэр: {clean_url}"


@register_tool
def lock_workstation() -> str:
    """Блокирует экран компьютера (Win + L)."""
    ctypes.windll.user32.LockWorkStation()
    return "Рабочая станция заблокирована, сэр."