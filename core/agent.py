import re
import threading
from datetime import datetime
from google import genai
from google.genai import types
from config.settings import LLM_API_KEY, WAKE_WORDS
from tools.os_system import (
    open_application,
    close_application,
    close_all_applications,
    restart_assistant_system,
    adjust_system_volume,
    minimize_all_windows,
    lock_workstation,
)
from tools.macros import run_macro
from tools.schedule import get_schedule


def create_memory_tools(memory):
    def remember_fact(fact: str) -> str:
        """Сохраняет важный факт о пользователе в долгосрочную память."""
        if memory:
            memory.save_fact(fact)
            return f"Факт сохранен: {fact}"
        return "Память не подключена."

    def clear_dialog_history() -> str:
        """Очищает краткосрочную историю текущего диалога."""
        if memory:
            memory.clear_short_term()
            return "История диалога очищена."
        return "Память не подключена."

    return [remember_fact, clear_dialog_history]


class AgentCore:
    def __init__(self, memory=None, extra_tools=None):
        self.memory = memory
        self.client = genai.Client(api_key=LLM_API_KEY)

        self.tools = []
        if memory is not None:
            self.tools.extend(create_memory_tools(memory))
        if extra_tools:
            existing_names = {getattr(t, "__name__", str(t)) for t in self.tools}
            for tool_fn in extra_tools:
                t_name = getattr(tool_fn, "__name__", str(tool_fn))
                if t_name not in existing_names:
                    self.tools.append(tool_fn)
                    existing_names.add(t_name)

        self.model_candidates = [
            "models/gemini-2.5-flash-lite",
            "models/gemini-flash-lite-latest",
            "models/gemini-2.5-flash",
            "models/gemini-2.0-flash",
        ]
        self.active_model = self.model_candidates[0]

        threading.Thread(target=self._warmup_connection, daemon=True).start()

    def _discover_models(self):
        return self.model_candidates

    def _warmup_connection(self):
        """Прогревает соединение с серверами Google заранее при старте."""
        for model_name in self.model_candidates:
            try:
                self.client.models.generate_content(
                    model=model_name,
                    contents="ok",
                    config=types.GenerateContentConfig(
                        max_output_tokens=1,
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                self.active_model = model_name
                print(f"[Agent] Соединение с ИИ прогрето ({model_name}) — готов к мгновенным ответам!")
                return
            except Exception:
                continue

    @staticmethod
    def _strip_wake_word(text: str) -> str:
        cleaned = text.strip()
        for w in WAKE_WORDS:
            pattern = rf"^\s*{re.escape(w)}[\s,!.:;-]+"
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned if cleaned else text.strip()

    @staticmethod
    def _try_fast_local_command(cmd_text: str) -> str | None:
        """
        Мгновенно (за 0.01 сек без сетевого запроса к LLM) выполняет частые системные команды.
        """
        low = cmd_text.lower().strip(" .,!?")

        # 0. Перезапуск самого ассистента («перезапуск системы», «обнови систему», «перезапусти себя»)
        if any(
            p in low
            for p in (
                "перезапуск системы",
                "перезапусти систему",
                "перезагрузи систему",
                "перезапусти себя",
                "перезапусти бота",
                "перезапусти ассистента",
                "обнови систему",
                "обнови данные",
                "перезапуск",
            )
        ):
            return restart_assistant_system()

        # 1. Макросы
        if any(p in low for p in ("режим кодинга", "запусти кодинг", "сценарий кодинга", "за работу")):
            return run_macro("режим кодинга")
        if any(p in low for p in ("отдыхаем", "режим отдыха", "время отдыха", "запусти отдых")):
            return run_macro("отдыхаем")

        # 2. Закрытие ВСЕХ приложений
        if any(p in low for p in ("закрой все приложения", "закрыть все приложения", "закрой все программы", "закрой все окна", "закрой всё", "закрой все")):
            return close_all_applications()

        # 3. Сворачивание всех окон
        if any(p in low for p in ("сверни все окна", "сверни всё", "сверни все", "чистый стол", "покажи рабочий стол")):
            return minimize_all_windows()

        # 4. Блокировка экрана
        if any(p in low for p in ("заблокируй компьютер", "заблокируй пк", "заблокируй экран", "блок пк")):
            return lock_workstation()

        # 5. Быстрая установка громкости («громкость на 50», «звук 25»)
        m_vol = re.search(r"(?:громкость|звук)\s*(?:на)?\s*(\d{1,3})", low)
        if m_vol:
            return adjust_system_volume(int(m_vol.group(1)))

        # 6. Быстрое закрытие конкретного приложения («закрой телеграм», «закрой приложение телеграм»)
        m_close = re.match(r"^(?:закрой|закрыть|заверши|выключи|убей)\s+(.+)$", low)
        if m_close:
            target = m_close.group(1).strip()
            if not any(x in target for x in ("вкладк",)):
                return close_application(target)

        # 7. Быстрое открытие приложения во весь экран («открой ватсап», «запусти телеграм»)
        m_open = re.match(r"^(?:открой|открыть|запусти|запустить|включи)\s+(.+)$", low)
        if m_open:
            target = m_open.group(1).strip()
            if not any(x in target for x in ("сайт", "файл", "папку", "вкладк", "http", ".ru", ".com", ".kz", ".bz")):
                return open_application(target)

        # 8. Быстрая проверка расписания
        if any(p in low for p in ("какая сейчас пара", "что сейчас по парам", "какие пары завтра", "какие пары сегодня", "расписание")):
            if "завтра" in low:
                return get_schedule("завтра")
            elif "сейчас" in low:
                return get_schedule("сейчас")
            return get_schedule("сегодня")

        return None

    def _build_system_instruction(self) -> str:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        facts_str = ""
        if self.memory:
            try:
                facts = self.memory.get_all_facts()
                if facts:
                    facts_str = "\nИзвестные факты о пользователе:\n" + "\n".join(f"- {f}" for f in facts)
            except Exception:
                pass

        return (
            f"Ты — «Система», сверхбыстрый голосовой и текстовый ИИ-ассистент для управления ПК на Windows. "
            f"Текущее время: {now_str}. "
            f"У тебя есть инструменты для открытия/закрытия любых программ (open_application, close_application, close_all_applications), "
            f"перезапуска самой системы ассистента (restart_assistant_system), "
            f"запуска макросов (run_macro), проверки расписания пар (get_schedule) и управления системой. "
            f"Отвечай максимально кратко (1-2 предложения), четко, без символов разметки (* и #)."
            f"{facts_str}"
        )

    def process_command(self, user_text: str) -> str:
        if not user_text or not user_text.strip():
            return "Я не расслышала команду."

        clean_text = self._strip_wake_word(user_text)

        # Мгновенное выполнение частых команд без сетевой задержки
        fast_result = self._try_fast_local_command(clean_text)
        if fast_result is not None:
            if self.memory:
                try:
                    self.memory.add_message("user", clean_text)
                    self.memory.add_message("model", fast_result)
                except Exception:
                    pass
            return fast_result

        history_contents = []
        if self.memory:
            try:
                recent = self.memory.get_recent_messages(limit=4)
                for msg in recent:
                    role = "user" if msg.get("role") == "user" else "model"
                    content_text = msg.get("content", "")
                    if content_text:
                        history_contents.append(
                            types.Content(role=role, parts=[types.Part.from_text(text=content_text)])
                        )
            except Exception:
                pass

        history_contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text=clean_text)])
        )

        models_to_try = [self.active_model] + [m for m in self.model_candidates if m != self.active_model]
        last_error = None

        for model_name in models_to_try:
            try:
                config = types.GenerateContentConfig(
                    system_instruction=self._build_system_instruction(),
                    temperature=0.2,
                    max_output_tokens=250,
                    tools=self.tools if self.tools else None,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )

                response = self.client.models.generate_content(
                    model=model_name,
                    contents=history_contents,
                    config=config,
                )

                self.active_model = model_name
                reply = (response.text or "Выполнено.").replace("*", "").replace("#", "").strip()

                if self.memory:
                    try:
                        self.memory.add_message("user", clean_text)
                        self.memory.add_message("model", reply)
                    except Exception:
                        pass

                return reply

            except Exception as e:
                last_error = e
                try:
                    fallback_config = types.GenerateContentConfig(
                        system_instruction=self._build_system_instruction(),
                        temperature=0.2,
                        max_output_tokens=250,
                        tools=self.tools if self.tools else None,
                    )
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=history_contents,
                        config=fallback_config,
                    )
                    self.active_model = model_name
                    reply = (response.text or "Выполнено.").replace("*", "").replace("#", "").strip()
                    if self.memory:
                        self.memory.add_message("user", clean_text)
                        self.memory.add_message("model", reply)
                    return reply
                except Exception as inner_e:
                    last_error = inner_e
                    continue

        return f"Ошибка обработки запроса: {last_error}"