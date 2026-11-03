import importlib
from pathlib import Path
from tools.base import REGISTERED_TOOLS, register_tool

# Автоматически импортируем все .py файлы в папке tools (кроме __init__ и base)
_tools_dir = Path(__file__).resolve().parent
for _file in sorted(_tools_dir.glob("*.py")):
    if _file.stem not in ("__init__", "base"):
        try:
            importlib.import_module(f"tools.{_file.stem}")
        except Exception as e:
            print(f"[Tools] Предупреждение при импорте tools.{_file.stem}: {e}")

__all__ = ["REGISTERED_TOOLS", "register_tool"]