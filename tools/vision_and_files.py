import os
from pathlib import Path
from PIL import ImageGrab
from google import genai
from google.genai import types
from config.settings import LLM_API_KEY

# Основные папки для быстрого поиска
USER_HOME = Path.home()
SEARCH_DIRS = {
    "рабочий стол": USER_HOME / "Desktop",
    "загрузки": USER_HOME / "Downloads",
    "документы": USER_HOME / "Documents",
}


def _get_search_paths(folder_hint: str = "все") -> list[Path]:
    hint = folder_hint.strip().lower()
    for key, path in SEARCH_DIRS.items():
        if key in hint and path.exists():
            return [path]
    return [p for p in SEARCH_DIRS.values() if p.exists()]


def search_local_files(query: str, folder: str = "все") -> str:
    """
    Ищет файлы и папки на компьютере (на Рабочем столе, в Загрузках и Документах) по части названия.
    query: часть имени файла (например, 'отчет', 'лаба', 'презентация').
    folder: где искать ('рабочий стол', 'загрузки', 'документы' или 'все').
    """
    q = query.strip().lower()
    if not q:
        return "Не указано название файла для поиска."

    paths_to_scan = _get_search_paths(folder)
    matches = []

    for base_path in paths_to_scan:
        try:
            for item in base_path.rglob("*"):
                if q in item.name.lower():
                    matches.append(item)
                    if len(matches) >= 5:
                        break
        except PermissionError:
            continue
        if len(matches) >= 5:
            break

    if not matches:
        return f"Файлы по запросу '{query}' не найдены."

    found_names = "; ".join([f"{m.name} (в папке {m.parent.name})" for m in matches])
    return f"Найдено: {found_names}."


def open_local_file(query: str) -> str:
    """
    Находит файл на Рабочем столе, в Загрузках или Документах по названию и сразу открывает его.
    """
    q = query.strip().lower()
    if not q:
        return "Скажи название файла, который нужно открыть."

    for base_path in _get_search_paths("все"):
        try:
            for item in base_path.rglob("*"):
                if item.is_file() and q in item.name.lower():
                    os.startfile(str(item))
                    return f"Открываю файл {item.name}."
        except Exception:
            continue

    return f"Не удалось найти файл '{query}' для открытия."


def analyze_screen_ocr(prompt: str = "Прочитай основной текст на экране или опиши, что открыто.") -> str:
    """
    Делает снимок экрана (скриншот) и анализирует его с помощью зрения ИИ (OCR).
    Используй эту функцию, когда пользователь спрашивает: 'что у меня на экране?',
    'прочитай текст с экрана', 'помоги с ошибкой на экране', 'переведи то, что открыто'.
    """
    if not LLM_API_KEY:
        return "Ключ API не настроен для анализа экрана."

    try:
        screenshot = ImageGrab.grab()
        client = genai.Client(api_key=LLM_API_KEY)

        sys_instruction = (
            "Ты голосовой ассистент Система. Тебе передан скриншот экрана пользователя. "
            "Отвечай кратко, четко, без спецсимволов маркдауна (* и #), чтобы текст легко читался вслух."
        )

        response = client.models.generate_content(
            model="models/gemini-flash-lite-latest",
            contents=[screenshot, prompt],
            config=types.GenerateContentConfig(
                system_instruction=sys_instruction,
                temperature=0.2,
            ),
        )
        reply = (response.text or "Не удалось распознать содержимое экрана.").replace("*", "").replace("#", "").strip()
        return reply
    except Exception as e:
        return f"Ошибка при анализе экрана: {e}"