from datetime import datetime
import psutil

try:
    import win32gui
except ImportError:
    win32gui = None


class SystemContext:
    @staticmethod
    def get_active_window_title() -> str:
        """Возвращает заголовок текущего активного окна Windows."""
        if win32gui is None:
            return "Неизвестно"
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd)
            return title.strip() if title else "Рабочий стол"
        except Exception:
            return "Неизвестно"

    @classmethod
    def collect_snapshot(cls) -> str:
        """Формирует компактную сводку состояния ПК для системного промпта."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S (%A)")
        cpu_usage = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        battery = psutil.sensors_battery()

        bat_str = "От сети (ПК)"
        if battery is not None:
            status = "заряжается" if battery.power_plugged else "от батареи"
            bat_str = f"{int(battery.percent)}% ({status})"

        active_win = cls.get_active_window_title()

        return (
            f"[ТЕКУЩИЙ КОНТЕКСТ СИСТЕМЫ]\n"
            f"- Время: {now}\n"
            f"- Активное окно: {active_win}\n"
            f"- Нагрузка ЦП: {cpu_usage}% | ОЗУ: {ram.percent}%\n"
            f"- Питание: {bat_str}"
        )