import re
import threading
from datetime import datetime
from google import genai
from google.genai import types
from config.settings import LLM_API_KEY
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
            return "История диалога очищена, сэр."
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

    def _warmup_connection(self):
        """Открывает соединение с серверами Google заранее при старте."""
        for model_name in self.model_candidates:
            try:
                self.client.models.generate_content(
                    model=model_name,
                    contents="ping",
                    config=types.GenerateContentConfig(max_output_tokens=5),
                )
                self.active_model = model_name
                print(f"[Джарвис] Соединение с ИИ прогрето ({model_name}).")
                break
            except Exception:
                continue

    def _build_system_instruction(self) -> str:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        facts_str = ""
        if self.memory:
            try:
                facts = self.memory.get_all_facts()
                if facts:
                    facts_str = "\nИзвестные факты о пользователе:\n" + "\n".join(
                        f"- {f}" for f in facts
                    )
            except Exception:
                pass

        return (
            f"Ты — «Джарвис» (J.A.R.V.I.S.), сверхбыстрый голосовой и текстовый ИИ-ассистент "
            f"в стиле оригинального Джарвиса Тони Старка для управления ПК на Windows. "
            f"Текущее время: {now_str}. "
            f"Общайся сдержанно, вежливо, с достоинством и легким интеллектуальным шармом, "
            f"уместно обращаясь к пользователю «сэр». "
            f"У тебя есть инструменты для открытия/закрытия любых программ (open_application, "
            f"close_application, close_all_applications), перезапуска самого ассистента "
            f"(restart_assistant_system), запуска макросов (run_macro), проверки расписания пар "
            f"(get_schedule) и управления системой. "
            f"Отвечай максимально кратко (1-2 предложения), четко, без символов разметки (* и #)."
            f"{facts_str}"
        )

    @staticmethod
    def _try_fast_local_command(cmd_text: str) -> str | None:
        low = cmd_text.lower().strip(" .,!?")

        if any(
            p in low
            for p in (
                "перезапусти джарвиса",
                "перезагрузи джарвиса",
                "обнови джарвиса",
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

        if any(
            p in low
            for p in ("режим кодинга", "запусти кодинг", "сценарий кодинга", "за работу")
        ):
            return run_macro("режим кодинга")

        if any(
            p in low
            for p in ("отдыхаем", "режим отдыха", "время отдыха", "запусти отдых")
        ):
            return run_macro("отдыхаем")

        if any(
            p in low
            for p in (
                "закрой все приложения",
                "закрыть все приложения",
                "закрой все программы",
                "закрой все окна",
                "закрой всё",
                "закрой все",
            )
        ):
            return close_all_applications()

        if any(
            p in low
            for p in (
                "сверни все окна",
                "сверни всё",
                "сверни все",
                "чистый стол",
                "покажи рабочий стол",
            )
        ):
            return minimize_all_windows()

        if any(
            p in low
            for p in (
                "заблокируй компьютер",
                "заблокируй пк",
                "заблокируй экран",
                "блок пк",
            )
        ):
            return lock_workstation()

        m_vol = re.search(r"(?:громкость|звук)\s*(?:на)?\s*(\d{1,3})", low)
        if m_vol:
            return adjust_system_volume(int(m_vol.group(1)))

        m_close = re.match(r"^(?:закрой|закрыть|заверши|выключи|убей)\s+(.+)$", low)
        if m_close:
            target = m_close.group(1).strip()
            if target not in ("все", "всё", "все окна", "все программы", "все приложения"):
                return close_application(target)

        m_open = re.match(r"^(?:открой|открыть|запусти|запустить|включи)\s+(.+)$", low)
        if m_open:
            target = m_open.group(1).strip()
            return open_application(target)

        if any(
            p in low
            for p in ("расписание", "какие пары", "какие сегодня пары", "пары на завтра")
        ):
            day = "завтра" if "завтра" in low else "сегодня"
            return get_schedule(day)

        return None

    def process_command(self, user_text: str) -> str:
        clean_input = (user_text or "").strip()
        if not clean_input:
            return "Я вас слушаю, сэр."

        # 1. Мгновенный локальный перехват без задержек API
        fast_result = self._try_fast_local_command(clean_input)
        if fast_result is not None:
            if self.memory:
                self.memory.add_message("user", clean_input)
                self.memory.add_message("model", fast_result)
            return fast_result

        # 2. Запрос к Gemini с Function Calling
        contents = []
        if self.memory:
            for msg in self.memory.get_recent_messages(limit=8):
                role = "user" if msg["role"] == "user" else "model"
                contents.append(
                    types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])])
                )
        contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text=clean_input)])
        )

        tool_map = {getattr(t, "__name__", str(t)): t for t in self.tools}

        for model_name in self.model_candidates:
            try:
                local_contents = list(contents)
                for _ in range(5):
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=local_contents,
                        config=types.GenerateContentConfig(
                            system_instruction=self._build_system_instruction(),
                            tools=self.tools if self.tools else None,
                            temperature=0.3,
                        ),
                    )

                    if response.function_calls:
                        local_contents.append(response.candidates[0].content)
                        for fn_call in response.function_calls:
                            fn_name = fn_call.name
                            fn_args = dict(fn_call.args) if fn_call.args else {}
                            print(f"[Инструмент] Вызов {fn_name}({fn_args})")
                            if fn_name in tool_map:
                                try:
                                    res_val = tool_map[fn_name](**fn_args)
                                except Exception as tool_err:
                                    res_val = f"Ошибка выполнения {fn_name}: {tool_err}"
                            else:
                                res_val = f"Инструмент {fn_name} не найден."

                            local_contents.append(
                                types.Content(
                                    role="tool",
                                    parts=[
                                        types.Part.from_function_response(
                                            name=fn_name,
                                            response={"result": str(res_val)},
                                        )
                                    ],
                                )
                            )
                        continue

                    reply = (response.text or "Выполнено, сэр.").strip()
                    break
                else:
                    reply = "Превышен лимит вызовов инструментов, сэр."

                reply = reply.replace("*", "").replace("#", "")
                if self.memory:
                    self.memory.add_message("user", clean_input)
                    self.memory.add_message("model", reply)
                return reply

            except Exception as e:
                print(f"[AgentCore] Ошибка на модели {model_name}: {e}")
                continue

        return "Прошу прощения, сэр, возникла временная ошибка связи с сервером."