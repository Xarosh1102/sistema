import ctypes
import time
import urllib.parse
import webbrowser
import win32clipboard
import win32con
import win32gui

from tools.base import register_tool

SITES_MAP = {
    "ютуб": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "гитхаб": "https://github.com",
    "github": "https://github.com",
    "гугл": "https://www.google.com",
    "яндекс": "https://ya.ru",
    "почта": "https://mail.google.com",
}

BROWSER_KEYWORDS = ("chrome", "edge", "браузер", "яндекс", "yandex", "opera", "firefox", "brave", "youtube", "google")

VK_CONTROL = 0x11
VK_L = 0x4C
VK_V = 0x56
VK_RETURN = 0x0D
VK_MENU = 0x12

# Память последнего действия в браузере (для автозамены при повторном запросе)
_last_browser_action_time: float = 0.0
_last_search_platform: str = "google"


def _copy_to_clipboard(text: str):
    """Копирует строку в буфер обмена Windows."""
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def _send_combo(*vk_codes: int):
    for vk in vk_codes:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.02)
    for vk in reversed(vk_codes):
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.02)


def _find_and_focus_browser() -> bool:
    """Ищет открытое окно браузера на экране и переводит фокус на него."""
    fg_hwnd = win32gui.GetForegroundWindow()
    fg_title = (win32gui.GetWindowText(fg_hwnd) or "").lower()
    if any(k in fg_title for k in BROWSER_KEYWORDS):
        return True

    found_hwnd = None

    def enum_cb(hwnd, _):
        nonlocal found_hwnd
        if win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd):
            title = (win32gui.GetWindowText(hwnd) or "").lower()
            if any(k in title for k in BROWSER_KEYWORDS):
                found_hwnd = hwnd

    win32gui.EnumWindows(enum_cb, None)
    if not found_hwnd:
        return False

    try:
        # Разрешаем перехват фокуса в Windows через короткий импульс Alt
        ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
        win32gui.SetForegroundWindow(found_hwnd)
        ctypes.windll.user32.keybd_event(VK_MENU, 0, 2, 0)
        time.sleep(0.15)
        return True
    except Exception:
        return False


def _navigate_in_current_tab(url: str) -> bool:
    """Открывает URL прямо в текущей активной вкладке браузера (Ctrl+L -> Ctrl+V -> Enter)."""
    if not _find_and_focus_browser():
        return False

    try:
        _copy_to_clipboard(url)
        _send_combo(VK_CONTROL, VK_L)  # Выделяем адресную строку текущей вкладки
        time.sleep(0.08)
        _send_combo(VK_CONTROL, VK_V)  # Вставляем новый URL
        time.sleep(0.05)
        _send_combo(VK_RETURN)         # Переходим по ссылке в этой же вкладке
        return True
    except Exception:
        return False


@register_tool
def open_website(site_name_or_url: str, in_current_tab: bool = True) -> str:
    """
    Открывает сайт в браузере ('ютуб', 'гитхаб', 'гугл', 'почта' или URL).
    :param site_name_or_url: Название сайта или ссылка.
    :param in_current_tab: True — открыть прямо в текущей открытой вкладке на экране, False — в новой вкладке.
    """
    global _last_browser_action_time, _last_search_platform
    key = site_name_or_url.strip().lower()
    if key in ("ютуб", "youtube"):
        _last_search_platform = "youtube"

    url = SITES_MAP.get(key, key)
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    if in_current_tab and _navigate_in_current_tab(url):
        _last_browser_action_time = time.time()
        return f"Открываю {site_name_or_url} в текущей вкладке."

    webbrowser.open(url)
    _last_browser_action_time = time.time()
    return f"Открываю сайт {site_name_or_url}."


@register_tool
def search_in_browser(query: str, platform: str = "", in_current_tab: bool = True) -> str:
    """
    Выполняет поиск в браузере (Google или YouTube).
    По умолчанию выполняет поиск прямо в ТЕКУЩЕЙ открытой на экране вкладке Chrome, чтобы не плодить лишние вкладки.
    Если пользователь исправляет предыдущий запрос — всегда используй in_current_tab=True.
    :param query: Поисковый запрос.
    :param platform: 'google' или 'youtube' (если не указано, используется платформа последнего поиска).
    :param in_current_tab: True — искать в текущей открытой вкладке, False — открыть новую вкладку.
    """
    global _last_browser_action_time, _last_search_platform

    plat = platform.strip().lower() if platform else _last_search_platform
    if plat in ("youtube", "ютуб"):
        _last_search_platform = "youtube"
        encoded = urllib.parse.quote_plus(query.strip())
        url = f"https://www.youtube.com/results?search_query={encoded}"
    else:
        _last_search_platform = "google"
        encoded = urllib.parse.quote_plus(query.strip())
        url = f"https://www.google.com/search?q={encoded}"

    # Если браузер открыт на экране или мы недавно уже искали — обновляем текущую вкладку
    recent_search = (time.time() - _last_browser_action_time) < 90
    if (in_current_tab or recent_search) and _navigate_in_current_tab(url):
        _last_browser_action_time = time.time()
        return f"Ищу {query} в этой же вкладке."

    webbrowser.open(url)
    _last_browser_action_time = time.time()
    return f"Открыт поиск по запросу: {query}."
