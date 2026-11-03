import difflib
import os
from pathlib import Path

from config.settings import DATA_DIR
from tools.base import register_tool

USER_HOME = Path.home()
FOLDER_MAP = {
    "загрузки": USER_HOME / "Downloads",
    "рабочий стол": USER_HOME / "Desktop",
    "документы": USER_HOME / "Documents",
    "проект": DATA_DIR.parent,
}


@register_tool
def open_known_folder(folder_name: str) -> str:
    """
    Открывает стандартную папку в проводнике Windows.
    :param folder_name: 'загрузки', 'рабочий стол', 'документы' или 'проект'.
    """
    key = folder_name.strip().lower()
    target = FOLDER_MAP.get(key)
    if target and target.exists():
        os.startfile(str(target))
        return f"Открываю папку {folder_name}."
    return f"Папка {folder_name} не найдена."


@register_tool
def find_files_by_name(query: str, folder_name: str = "все") -> str:
    """
    Ищет файлы или папки по части имени на Рабочем столе, в Загрузках и Документах.
    :param query: Название или часть названия файла.
    :param folder_name: 'все', 'рабочий стол', 'загрузки' или 'документы'.
    """
    key = folder_name.strip().lower()
    search_roots = (
        [FOLDER_MAP[key]]
        if key in FOLDER_MAP
        else [USER_HOME / "Desktop", USER_HOME / "Downloads", USER_HOME / "Documents"]
    )

    q = query.strip().lower()
    matches = []

    for root in search_roots:
        if not root.exists():
            continue
        try:
            for item in root.iterdir():
                if q in item.name.lower():
                    matches.append(item.name)
                    if len(matches) >= 5:
                        break
        except Exception:
            continue

    if not matches:
        return f"Файлы по запросу {query} не найдены."
    return f"Найдены файлы: {', '.join(matches[:5])}."


@register_tool
def open_file_by_name(query: str) -> str:
    """
    Находит файл по названию (даже при неточном совпадении) на Рабочем столе, в Загрузках или Документах и сразу ОТКРЫВАЕТ его.
    Используй эту функцию, когда пользователь просит 'открой файл...', 'запусти документ...', 'открой отчет...'.
    :param query: Название файла, который нужно найти и открыть.
    """
    search_roots = [USER_HOME / "Desktop", USER_HOME / "Downloads", USER_HOME / "Documents"]
    q = query.strip().lower()

    candidates = []
    for root in search_roots:
        if not root.exists():
            continue
        try:
            for item in root.iterdir():
                if item.name.startswith("."):
                    continue
                name_low = item.stem.lower()
                if q in name_low:
                    candidates.append((1.0, item))
                else:
                    ratio = difflib.SequenceMatcher(None, q, name_low).ratio()
                    if ratio >= 0.55:
                        candidates.append((ratio, item))
        except Exception:
            continue

    if not candidates:
        return f"Файл, похожий на {query}, не найден."

    candidates.sort(key=lambda x: x[0], reverse=True)
    best_file = candidates[0][1]
    try:
        os.startfile(str(best_file))
        return f"Открываю файл {best_file.name}."
    except Exception as e:
        return f"Не удалось открыть файл {best_file.name}: {e}"


@register_tool
def create_quick_note(filename: str, content: str) -> str:
    """
    Создает текстовую заметку в папке data/notes.
    :param filename: Название заметки.
    :param content: Текст заметки.
    """
    notes_dir = DATA_DIR / "notes"
    notes_dir.mkdir(exist_ok=True)
    safe_name = "".join(c for c in filename if c.isalnum() or c in (" ", "_", "-")).strip() or "note"
    path = notes_dir / f"{safe_name}.txt"
    path.write_text(content, encoding="utf-8")
    return f"Заметка {safe_name} сохранена."
