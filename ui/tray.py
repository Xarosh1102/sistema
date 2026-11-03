import threading
from typing import Callable
import pystray
from PIL import Image, ImageDraw


class SystemTrayIcon:
    def __init__(
        self,
        on_toggle_mute: Callable[[], bool],
        on_clear_memory: Callable[[], None],
        on_exit: Callable[[], None],
    ):
        self.on_toggle_mute = on_toggle_mute
        self.on_clear_memory = on_clear_memory
        self.on_exit = on_exit
        self.is_muted = False
        self.icon = None

    @staticmethod
    def _create_image(active: bool = True) -> Image.Image:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        color = (0, 210, 255, 255) if active else (220, 60, 60, 255)
        draw.ellipse((6, 6, 58, 58), outline=color, width=5)
        draw.ellipse((22, 22, 42, 42), fill=color)
        return img

    def _toggle_mute_clicked(self, icon, item):
        self.is_muted = self.on_toggle_mute()
        icon.icon = self._create_image(active=not self.is_muted)

    def _clear_memory_clicked(self, icon, item):
        self.on_clear_memory()

    def _exit_clicked(self, icon, item):
        icon.stop()
        self.on_exit()

    def start_in_background(self):
        menu = pystray.Menu(
            pystray.MenuItem(
                lambda item: "Включить микрофон" if self.is_muted else "Пауза (Режим тишины)",
                self._toggle_mute_clicked,
            ),
            pystray.MenuItem("Очистить память диалога", self._clear_memory_clicked),
            pystray.MenuItem("Выход", self._exit_clicked),
        )
        self.icon = pystray.Icon(
            "Sistema",
            self._create_image(active=True),
            "Система (Jarvis)",
            menu,
        )
        thread = threading.Thread(target=self.icon.run, daemon=True)
        thread.start()