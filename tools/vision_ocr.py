from PIL import ImageGrab
from google import genai
from google.genai import types

from config.settings import LLM_API_KEY
from tools.base import register_tool


@register_tool
def analyze_screen(question: str = "Кратко опиши, что сейчас открыто на экране, или прочитай важный текст.") -> str:
    """
    Делает снимок экрана (OCR / компьютерное зрение), читает текст на экране и отвечает на вопрос пользователя.
    Обязательно вызывай эту функцию, когда пользователь спрашивает:
    'что у меня на экране?', 'прочитай с экрана', 'какая тут ошибка?', 'посмотри на экран'.
    :param question: Вопрос пользователя о содержимом экрана.
    """
    if not LLM_API_KEY:
        return "Ключ API не настроен для анализа экрана."

    try:
        screenshot = ImageGrab.grab()
        screenshot.thumbnail((1280, 720))

        client = genai.Client(api_key=LLM_API_KEY)
        prompt = (
            f"Ты голосовой ассистент Система. Пользователь просит посмотреть на его экран: '{question}'. "
            "Ответь кратко (1-3 предложения), по существу, без символов разметки Markdown и звездочек, "
            "чтобы ответ легко читался вслух."
        )
        response = client.models.generate_content(
            model="models/gemini-flash-lite-latest",
            contents=[screenshot, prompt],
            config=types.GenerateContentConfig(temperature=0.2),
        )
        return (response.text or "Экран проанализирован.").replace("*", "").replace("#", "").strip()
    except Exception as e:
        return f"Не удалось прочитать экран: {e}"
