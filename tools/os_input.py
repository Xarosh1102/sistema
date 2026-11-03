import ctypes
import time
import win32gui
from tools.base import register_tool

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12      # Alt
VK_TAB = 0x09
VK_W = 0x57
VK_T = 0x54
VK_R = 0x52
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_PRIOR = 0x21     # Page Up
VK_NEXT = 0x22      # Page Down

BROWSER_KEYWORDS = ("chrome", "edge", "браузер", "яндекс", "yandex", "opera", "firefox", "brave", "youtube", "google")


def _tap_vk(vk_code: int):
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)


def _send_combo(*vk_codes: int):
    for vk in vk_codes:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.02)
    for vk in reversed(vk_codes):
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.02)


def _focus_browser_window() -> bool:
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
    if found_hwnd:
        try:
            ctypes.windll.user32.keybd_event(VK_MENU, 0, 0, 0)
            win32gui.SetForegroundWindow(found_hwnd)
            ctypes.windll.user32.keybd_event(VK_MENU, 0, 2, 0)
            time.sleep(0.15)
            return True
        except Exception:
            return False
    return False


@register_tool
def control_browser_tabs(action: str) -> str:
    """
    Управляет текущей открытой вкладкой и навигацией в браузере (Chrome, Edge, Яндекс и др.).
    :param action:
      'close_tab' — закрыть текущую вкладку (Ctrl+W),
      'reopen_tab' — вернуть закрытую вкладку (Ctrl+Shift+T),
      'new_tab' — открыть новую вкладку (Ctrl+T),
      'next_tab' — следующая вкладка (Ctrl+Tab),
      'prev_tab' — предыдущая вкладка (Ctrl+Shift+Tab),
      'refresh' — обновить текущую вкладку (Ctrl+R),
      'back' — вернуться на предыдущую страницу в этой вкладке (Alt+Left),
      'forward' — перейти вперед в этой вкладке (Alt+Right),
      'scroll_down' — прокрутить страницу вниз (PageDown),
      'scroll_up' — прокрутить страницу вверх (PageUp).
    """
    if not _focus_browser_window():
        return "Открытое окно браузера не найдено."

    act = action.strip().lower()
    if act == "close_tab":
        _send_combo(VK_CONTROL, VK_W)
        return "Вкладка закрыта."
    elif act == "reopen_tab":
        _send_combo(VK_CONTROL, VK_SHIFT, VK_T)
        return "Закрытая вкладка восстановлена."
    elif act == "new_tab":
        _send_combo(VK_CONTROL, VK_T)
        return "Открыта новая вкладка."
    elif act == "next_tab":
        _send_combo(VK_CONTROL, VK_TAB)
        return "Следующая вкладка."
    elif act == "prev_tab":
        _send_combo(VK_CONTROL, VK_SHIFT, VK_TAB)
        return "Предыдущая вкладка."
    elif act == "refresh":
        _send_combo(VK_CONTROL, VK_R)
        return "Страница обновлена."
    elif act == "back":
        _send_combo(VK_MENU, VK_LEFT)
        return "Возвращаюсь назад."
    elif act == "forward":
        _send_combo(VK_MENU, VK_RIGHT)
        return "Перехожу вперед."
    elif act == "scroll_down":
        _tap_vk(VK_NEXT)
        return "Прокручено вниз."
    elif act == "scroll_up":
        _tap_vk(VK_PRIOR)
        return "Прокручено вверх."

    return f"Неизвестное действие для вкладки: {action}."


@register_tool
def adjust_system_volume(direction: str, steps: int = 5) -> str:
    """
    Изменяет громкость звука в Windows или выключает звук.
    :param direction: 'up' (громче), 'down' (тише) или 'mute' (выключить/включить звук).
    :param steps: На сколько шагов изменить громкость (по умолчанию 5, что равно 10%).
    """
    d = direction.strip().lower()
    steps = max(1, min(int(steps), 50))

    if d == "mute":
        _tap_vk(VK_VOLUME_MUTE)
        return "Переключен режим без звука."
    elif d == "up":
        for _ in range(steps):
            _tap_vk(VK_VOLUME_UP)
        return f"Громкость увеличена на {steps * 2} процентов."
    elif d == "down":
        for _ in range(steps):
            _tap_vk(VK_VOLUME_DOWN)
        return f"Громкость уменьшена на {steps * 2} процентов."
    return "Неизвестная команда громкости."


@register_tool
def media_control(command: str) -> str:
    """
    Управляет воспроизведением музыки или видео (пауза, продолжить, следующий или предыдущий трек).
    :param command: 'play_pause' (пауза/пуск), 'next' (следующий трек), 'prev' (предыдущий трек).
    """
    cmd = command.strip().lower()
    if cmd == "play_pause":
        _tap_vk(VK_MEDIA_PLAY_PAUSE)
        return "Воспроизведение переключено."
    elif cmd == "next":
        _tap_vk(VK_MEDIA_NEXT_TRACK)
        return "Включен следующий трек."
    elif cmd == "prev":
        _tap_vk(VK_MEDIA_PREV_TRACK)
        return "Включен предыдущий трек."
    return "Неизвестная медиа-команда."
