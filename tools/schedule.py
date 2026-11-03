import json
from datetime import datetime, time, timedelta
from config.settings import DATA_DIR
from tools.base import register_tool

SCHEDULE_FILE = DATA_DIR / "schedule.json"

DEFAULT_BELLS = [
    {"pair": 1, "start": "08:00", "end": "08:50"},
    {"pair": 2, "start": "08:55", "end": "09:45"},
    {"pair": 3, "start": "09:55", "end": "10:45"},
    {"pair": 4, "start": "10:50", "end": "11:40"},
    {"pair": 5, "start": "11:50", "end": "12:40"},
    {"pair": 6, "start": "12:45", "end": "13:35"},
]

WEEKDAYS_RU = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]


def _load_schedule_data() -> dict:
    if not SCHEDULE_FILE.exists():
        default_data = {
            "bell_schedule": DEFAULT_BELLS,
            "days": {d: [] for d in WEEKDAYS_RU},
            "tasks": [],
        }
        _save_schedule_data(default_data)
        return default_data

    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "bell_schedule" not in data:
            data["bell_schedule"] = DEFAULT_BELLS
        if "days" not in data:
            data["days"] = {d: [] for d in WEEKDAYS_RU}
        if "tasks" not in data:
            data["tasks"] = []
        return data
    except Exception as e:
        print(f"[Schedule] Ошибка чтения schedule.json: {e}")
        return {"bell_schedule": DEFAULT_BELLS, "days": {d: [] for d in WEEKDAYS_RU}, "tasks": []}


def _save_schedule_data(data: dict):
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_time(t_str: str) -> time:
    h, m = map(int, t_str.split(":"))
    return time(h, m)


def _format_day_schedule(day_name: str, label: str = "") -> str:
    data = _load_schedule_data()
    bell_map = {b["pair"]: (b["start"], b["end"]) for b in data.get("bell_schedule", DEFAULT_BELLS)}
    pairs = data.get("days", {}).get(day_name, [])

    header = f"Расписание на {label} ({day_name}):" if label else f"Расписание на {day_name}:"
    if not pairs:
        return f"{header} пар нет, можно отдыхать!"

    lines = [header]
    for item in sorted(pairs, key=lambda x: x.get("pair", 1) if isinstance(x, dict) else 1):
        if isinstance(item, dict):
            p_num = item.get("pair", 1)
            start_t, end_t = bell_map.get(p_num, ("??:??", "??:??"))
            subj = item.get("subject", "Предмет")
            room = item.get("room", "—")
            p_type = item.get("type", "")
            type_str = f" ({p_type})" if p_type else ""
            lines.append(f"• {p_num}-я пара ({start_t}–{end_t}): {subj}{type_str}, каб. {room}")
        else:
            lines.append(f"• {item}")

    return "\n".join(lines)


def get_current_pair_status() -> str:
    data = _load_schedule_data()
    now = datetime.now()
    day_name = WEEKDAYS_RU[now.weekday()]
    pairs = data.get("days", {}).get(day_name, [])

    if not pairs:
        return f"Сегодня {day_name}, пар по расписанию нет."

    bell_map = {b["pair"]: (b["start"], b["end"]) for b in data.get("bell_schedule", DEFAULT_BELLS)}
    sorted_pairs = sorted(
        [p for p in pairs if isinstance(p, dict) and "pair" in p],
        key=lambda x: x["pair"]
    )
    if not sorted_pairs:
        return _format_day_schedule(day_name, "сегодня")

    now_t = now.time()
    first_p = sorted_pairs[0]
    last_p = sorted_pairs[-1]

    first_start_str, _ = bell_map.get(first_p["pair"], ("08:00", "08:50"))
    _, last_end_str = bell_map.get(last_p["pair"], ("12:45", "13:35"))

    first_start = _parse_time(first_start_str)
    last_end = _parse_time(last_end_str)

    if now_t < first_start:
        mins_before = int((datetime.combine(now.date(), first_start) - now).total_seconds() // 60)
        return (
            f"Пары еще не начались (до 1-й пары {mins_before} мин). "
            f"Первая пара в {first_start_str}: {first_p.get('subject')}, каб. {first_p.get('room', '—')}."
        )

    if now_t > last_end:
        return "Все пары на сегодня уже закончились!"

    for p in sorted_pairs:
        num = p["pair"]
        st_str, end_str = bell_map.get(num, ("08:00", "08:50"))
        st_t, end_t = _parse_time(st_str), _parse_time(end_str)

        if st_t <= now_t <= end_t:
            mins_left = int((datetime.combine(now.date(), end_t) - now).total_seconds() // 60)
            return (
                f"Сейчас идет {num}-я пара ({st_str}–{end_str}): "
                f"{p.get('subject')} ({p.get('type', 'Занятие')}), каб. {p.get('room', '—')}. "
                f"До звонка осталось {mins_left} мин."
            )

    for i in range(len(sorted_pairs) - 1):
        curr_p = sorted_pairs[i]
        next_p = sorted_pairs[i + 1]
        _, prev_end_str = bell_map.get(curr_p["pair"], ("08:00", "08:50"))
        next_start_str, _ = bell_map.get(next_p["pair"], ("08:55", "09:45"))

        prev_end_t = _parse_time(prev_end_str)
        next_start_t = _parse_time(next_start_str)

        if prev_end_t < now_t < next_start_t:
            mins_to_next = int((datetime.combine(now.date(), next_start_t) - now).total_seconds() // 60)
            return (
                f"Сейчас перемена! До {next_p['pair']}-й пары осталось {mins_to_next} мин. "
                f"Следующий предмет в {next_start_str}: {next_p.get('subject')}, каб. {next_p.get('room', '—')}."
            )

    return "Сейчас окно между парами."


def get_morning_briefing() -> str:
    data = _load_schedule_data()
    now = datetime.now()
    day_name = WEEKDAYS_RU[now.weekday()]
    pairs = data.get("days", {}).get(day_name, [])

    if not pairs:
        return f"📅 Сегодня {day_name} — пар по расписанию нет, можно отдыхать!"

    bell_map = {b["pair"]: (b["start"], b["end"]) for b in data.get("bell_schedule", DEFAULT_BELLS)}
    sorted_pairs = sorted(
        [p for p in pairs if isinstance(p, dict) and "pair" in p],
        key=lambda x: x["pair"]
    )
    if not sorted_pairs:
        return f"📅 Сегодня {day_name} — расписание активно."

    first_p = sorted_pairs[0]
    first_start, _ = bell_map.get(first_p["pair"], ("08:00", "08:50"))

    lines = [
        f"☀️ **Утренняя сводка ({day_name}):**",
        f"• Всего пар сегодня: **{len(sorted_pairs)}**",
        f"• Первая пара в **{first_start}** — {first_p.get('subject')} (каб. `{first_p.get('room', '—')}`)\n",
        "**Полное расписание на сегодня:**",
    ]
    for p in sorted_pairs:
        num = p["pair"]
        st_str, end_str = bell_map.get(num, ("??:??", "??:??"))
        lines.append(f"{num}) `{st_str}–{end_str}` — {p.get('subject')} (каб. {p.get('room', '—')})")

    return "\n".join(lines)


@register_tool
def get_schedule(day: str = "сегодня") -> str:
    """
    Возвращает расписание пар в университете.
    Аргумент day может быть: 'сегодня', 'завтра', 'сейчас' (какая пара идет и сколько до звонка),
    либо день недели ('понедельник', 'вторник' и т.д.).
    """
    q = (day or "сегодня").strip().lower()
    now = datetime.now()

    if any(w in q for w in ("сейчас", "текущ", "какая пара", "звонок", "перемен")):
        return get_current_pair_status()

    if "сегодня" in q or "today" in q:
        day_name = WEEKDAYS_RU[now.weekday()]
        return _format_day_schedule(day_name, "сегодня") + "\n\n" + get_current_pair_status()

    if "завтра" in q or "tomorrow" in q:
        tmr = now + timedelta(days=1)
        day_name = WEEKDAYS_RU[tmr.weekday()]
        return _format_day_schedule(day_name, "завтра")

    for w_day in WEEKDAYS_RU:
        if w_day[:4] in q:
            return _format_day_schedule(w_day)

    day_name = WEEKDAYS_RU[now.weekday()]
    return _format_day_schedule(day_name, "сегодня")


@register_tool
def set_day_schedule(day: str, subjects_text: str) -> str:
    """
    Записывает расписание пар на указанный день недели.
    Формат subjects_text: '1: Высшая математика (302), 2: Python (415)'.
    """
    data = _load_schedule_data()
    day_clean = day.strip().lower()
    target_day = next((w for w in WEEKDAYS_RU if w[:4] in day_clean), None)
    if not target_day:
        return f"Не удалось распознать день недели: {day}"

    new_pairs = []
    parts = [p.strip() for p in subjects_text.split(",") if p.strip()]
    for idx, part in enumerate(parts, start=1):
        pair_num = idx
        subj = part
        room = "—"
        if ":" in part:
            num_str, rest = part.split(":", 1)
            if num_str.strip().isdigit():
                pair_num = int(num_str.strip())
                subj = rest.strip()
        if "(" in subj and subj.endswith(")"):
            subj_name, room_part = subj.rsplit("(", 1)
            subj = subj_name.strip()
            room = room_part[:-1].strip()
        new_pairs.append({"pair": pair_num, "subject": subj, "room": room, "type": "Занятие"})

    data["days"][target_day] = new_pairs
    _save_schedule_data(data)
    return f"Расписание на {target_day} успешно обновлено ({len(new_pairs)} пар)."


@register_tool
def add_study_task(task_text: str) -> str:
    """Добавляет учебную задачу или дедлайн в список заданий."""
    data = _load_schedule_data()
    data.setdefault("tasks", []).append({
        "task": task_text.strip(),
        "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })
    _save_schedule_data(data)
    return f"Учебная задача добавлена: {task_text}"


@register_tool
def get_study_tasks() -> str:
    """Возвращает список текущих учебных задач и дедлайнов."""
    data = _load_schedule_data()
    tasks = data.get("tasks", [])
    if not tasks:
        return "Список учебных задач пуст."
    lines = ["Актуальные учебные задачи:"]
    for i, t in enumerate(tasks, 1):
        text = t["task"] if isinstance(t, dict) else str(t)
        lines.append(f"{i}. {text}")
    return "\n".join(lines)


@register_tool
def clear_study_tasks() -> str:
    """Очищает список учебных задач."""
    data = _load_schedule_data()
    data["tasks"] = []
    _save_schedule_data(data)
    return "Все учебные задачи очищены."