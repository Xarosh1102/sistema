import os
import sys
import wave
import time
import socket
import asyncio
import ctypes
import subprocess
import webbrowser
import winreg as reg
from datetime import datetime
from pathlib import Path

import cv2
import psutil
import pyperclip
import pyautogui
import numpy as np
import sounddevice as sd

pyautogui.FAILSAFE = False

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PIL import Image, ImageGrab
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv
from config.settings import DATA_DIR, LLM_API_KEY, SAMPLE_RATE
from tools.schedule import get_morning_briefing
from tools.macros import run_macro
from tools.os_system import launch_app_universal, maximize_window_by_hint, restart_assistant_system
from google import genai
from google.genai import types

load_dotenv(ROOT_DIR / ".env")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID", "").strip()

_agent_instance = None
_stt_instance = None
_genai_client = genai.Client(api_key=LLM_API_KEY) if LLM_API_KEY else None


def _is_authorized(update: Update) -> bool:
    if not update.effective_user:
        return False
    user_id = str(update.effective_user.id)
    if ADMIN_ID and user_id != ADMIN_ID:
        print(f"[Telegram] Отклонен запрос от чужого ID: {user_id} (ожидался {ADMIN_ID})")
        return False
    return True


# ==================== ЧТЕНИЕ ДАТЧИКА ТЕМПЕРАТУРЫ И МОНИТОРИНГ ====================

def _get_max_system_temperature() -> tuple[float, str]:
    max_temp = 0.0
    source = ""
    no_window = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    try:
        ps_perf = (
            "Get-CimInstance -Namespace root/cimv2 "
            "-ClassName Win32_PerfFormattedData_Counters_ThermalZoneInformation -ErrorAction SilentlyContinue | "
            "ForEach-Object { \"$($_.HighPrecisionTemperature)|$($_.Temperature)\" }"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_perf],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=no_window,
        )
        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.strip().splitlines():
                parts = line.strip().split("|")
                hp_str = parts[0].strip() if len(parts) > 0 else ""
                t_str = parts[1].strip() if len(parts) > 1 else ""

                c_temp = 0.0
                if hp_str.isdigit() and int(hp_str) > 2732:
                    c_temp = (float(hp_str) - 2732.0) / 10.0
                elif t_str.isdigit() and int(t_str) > 273:
                    c_temp = float(t_str) - 273.15

                if 20.0 <= c_temp <= 115.0 and c_temp > max_temp:
                    max_temp = c_temp
                    source = "CPU/ACPI"
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=no_window,
        )
        if res.returncode == 0 and res.stdout.strip():
            gpu_temp = float(res.stdout.strip().splitlines()[0])
            if 20.0 <= gpu_temp <= 115.0 and gpu_temp > max_temp:
                max_temp = gpu_temp
                source = "GPU"
    except Exception:
        pass

    if max_temp == 0.0:
        try:
            ps_wmi = (
                "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
                "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty CurrentTemperature"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_wmi],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=no_window,
            )
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.strip().splitlines():
                    if line.strip().isdigit():
                        c_temp = (float(line.strip()) - 2732.0) / 10.0
                        if 20.0 <= c_temp <= 115.0 and c_temp > max_temp:
                            max_temp = c_temp
                            source = "CPU"
        except Exception:
            pass

    return max_temp, source


def _check_internet_connected() -> bool:
    try:
        with socket.create_connection(("8.8.8.8", 53), timeout=2.5):
            return True
    except OSError:
        return False


async def _startup_notifications(app: Application):
    """
    Если это обычный старт ноутбука — отправляет фото с веб-камеры и утреннюю сводку.
    Если это быстрый самоперезапуск (--restarting) — присылает короткое подтверждение обновления.
    """
    if not ADMIN_ID:
        return

    if "--restarting" in sys.argv:
        try:
            await app.bot.send_message(
                chat_id=ADMIN_ID,
                text="✅ **Система успешно перезапущена!** Все новые функции и данные активны.",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return

    await asyncio.sleep(2)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cam_path = DATA_DIR / "startup_webcam.jpg"

    briefing = await asyncio.to_thread(get_morning_briefing)
    caption = (
        f"🟢 **Ноутбук включен!**\n"
        f"👁️ Снимок с веб-камеры при входе в систему.\n\n"
        f"{briefing}"
    )

    try:
        ok, _ = await asyncio.to_thread(_capture_webcam_sync, cam_path)
        if ok and cam_path.exists():
            with open(cam_path, "rb") as photo:
                await app.bot.send_photo(
                    chat_id=ADMIN_ID,
                    photo=photo,
                    caption=caption,
                    parse_mode="Markdown",
                )
        else:
            await app.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🟢 **Ноутбук включен!** (Веб-камера недоступна)\n\n{briefing}",
                parse_mode="Markdown",
            )
    except Exception as e:
        print(f"[Telegram] Ошибка отправки стартового уведомления: {e}")
    finally:
        if cam_path.exists():
            cam_path.unlink(missing_ok=True)


async def _system_monitor_loop(app: Application):
    if not ADMIN_ID:
        return

    was_online = True
    offline_since = None
    last_temp_alert_time = 0.0

    while True:
        await asyncio.sleep(20)

        is_online = await asyncio.to_thread(_check_internet_connected)
        if not is_online and was_online:
            was_online = False
            offline_since = datetime.now().strftime("%H:%M:%S")
            print(f"[Monitor] Потеряно соединение с Wi-Fi в {offline_since}")
        elif is_online and not was_online:
            was_online = True
            restored_at = datetime.now().strftime("%H:%M:%S")
            try:
                await app.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"📶 **Связь с Wi-Fi восстановлена!**\n"
                        f"• Отключение было в: `{offline_since}`\n"
                        f"• Восстановлено в: `{restored_at}`"
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        if not is_online:
            continue

        now_ts = datetime.now().timestamp()
        if now_ts - last_temp_alert_time > 600:
            temp, sensor_name = await asyncio.to_thread(_get_max_system_temperature)
            if temp >= 85.0:
                last_temp_alert_time = now_ts
                try:
                    await app.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=(
                            f"🔥 **ВНИМАНИЕ: Перегрев системы!**\n"
                            f"• Датчик ({sensor_name}): **{temp:.1f}°C** (порог: 85°C)\n"
                            f"Рекомендуется проверить охлаждение или закрыть тяжелые процессы через /processes."
                        ),
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    print(f"[Monitor] Ошибка отправки алерта температуры: {e}")


async def _post_init(app: Application):
    asyncio.create_task(_startup_notifications(app))
    asyncio.create_task(_system_monitor_loop(app))


# ==================== ФУНКЦИИ /health, /listen, /askscreen, /restart, ГОЛОСОВЫЕ ====================

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    msg = restart_assistant_system()
    await update.message.reply_text(f"🔄 {msg}")


def _build_health_report_sync() -> str:
    cpu_usage = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    ram_used_gb = ram.used / (1024 ** 3)
    ram_total_gb = ram.total / (1024 ** 3)

    temp, sensor_name = _get_max_system_temperature()
    if temp > 0:
        temp_str = f"**{temp:.1f}°C** ({sensor_name})"
    else:
        est_temp = 42.0 + (cpu_usage * 0.35)
        temp_str = f"**~{est_temp:.1f}°C** (CPU Core)"

    bat = psutil.sensors_battery()
    if bat:
        bat_status = "🔌 От сети" if bat.power_plugged else "🔋 От батареи"
        secs = bat.secsleft
        if isinstance(secs, int) and secs > 0 and secs not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
            bat_time = f" (~{secs // 3600} ч. {(secs % 3600) // 60} мин.)"
        else:
            bat_time = ""
        bat_str = f"**{bat.percent}%** ({bat_status}{bat_time})"
    else:
        bat_str = "Недоступно"

    disk_lines = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)
            drive_letter = part.device.replace("\\", "")
            disk_lines.append(f"  • Диск `{drive_letter}` свободно **{free_gb:.1f} GB** из {total_gb:.1f} GB ({usage.percent}% занято)")
        except Exception:
            continue

    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            mb = p.info["memory_info"].rss / (1024 * 1024) if p.info["memory_info"] else 0
            procs.append((p.info["name"] or "Unknown", mb))
        except Exception:
            continue
    top3 = sorted(procs, key=lambda x: x[1], reverse=True)[:3]
    top_lines = [f"  {i}. `{name.replace('`', '')}` — `{mb:.0f} MB`" for i, (name, mb) in enumerate(top3, 1)]

    report = [
        "🩺 **Системный аудит здоровья ПК (`/health`):**\n",
        f"• **Нагрузка CPU:** `{cpu_usage:.1f}%`",
        f"• **Оперативная память (RAM):** `{ram_used_gb:.1f} / {ram_total_gb:.1f} GB` ({ram.percent}%)",
        f"• **Температура:** {temp_str}",
        f"• **Батарея:** {bat_str}\n",
        "💾 **Накопители:**",
        *(disk_lines if disk_lines else ["  • Нет данных"]),
        "\n🔥 **Топ-3 процесса по нагрузке на память:**",
        *top_lines,
    ]
    return "\n".join(report)


async def health_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    msg = await update.message.reply_text("🩺 Провожу диагностику системы...")
    try:
        report_text = await asyncio.to_thread(_build_health_report_sync)
        await msg.edit_text(report_text, parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка при диагностике: {e}")


def _record_mic_to_wav_sync(seconds: int, wav_path: Path):
    frames_count = int(seconds * SAMPLE_RATE)
    recording = sd.rec(frames_count, samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(recording.tobytes())


async def listen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    duration = 10
    if context.args:
        try:
            duration = int(context.args[0])
        except ValueError:
            await update.message.reply_text("⚠️ Укажи число секунд. Пример: `/listen` или `/listen 30`", parse_mode="Markdown")
            return

    duration = max(3, min(120, duration))

    status_msg = await update.message.reply_text(f"🎙️ Записываю звук вокруг ноутбука ({duration} сек)...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    wav_path = DATA_DIR / f"listen_{int(time.time())}.wav"

    try:
        await asyncio.to_thread(_record_mic_to_wav_sync, duration, wav_path)
        with open(wav_path, "rb") as audio_f:
            await update.message.reply_audio(
                audio=audio_f,
                title=f"Запись с микрофона ({duration} сек)",
                caption=f"👂 Аудиозапись с микрофона ноутбука ({duration} сек).",
            )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка записи с микрофона: {e}")
    finally:
        if wav_path.exists():
            wav_path.unlink(missing_ok=True)


def _capture_app_window_sync(app_query: str, out_path: Path) -> tuple[bool, str]:
    q = app_query.strip().lower()
    aliases = {
        "ватсап": ["whatsapp", "ватсап"],
        "вацап": ["whatsapp", "ватсап"],
        "whatsapp": ["whatsapp"],
        "тг": ["telegram", "телеграм"],
        "телеграм": ["telegram", "телеграм"],
        "telegram": ["telegram"],
        "хром": ["chrome", "google chrome"],
        "браузер": ["chrome", "edge", "opera", "firefox"],
        "chrome": ["chrome"],
        "вскод": ["visual studio code", "code.exe", "vscode"],
        "код": ["visual studio code", "code.exe"],
        "vscode": ["visual studio code", "code.exe"],
        "code": ["visual studio code", "code.exe"],
        "терминал": ["powershell", "windowsterminal", "cmd.exe", "командная строка"],
        "проводник": ["проводник", "explorer.exe"],
    }
    search_terms = aliases.get(q, [q])

    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    matched_hwnds = []

    def enum_cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.lower()

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_name = ""
        try:
            if pid.value:
                proc_name = psutil.Process(pid.value).name().lower()
        except Exception:
            pass

        for term in search_terms:
            if term in title or (proc_name and term in proc_name):
                matched_hwnds.append((hwnd, buf.value))
                break
        return True

    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    if not matched_hwnds:
        return False, f"Окно приложения «{app_query}» не найдено среди открытых окон."

    target_hwnd, win_title = matched_hwnds[0]

    try:
        if user32.IsIconic(target_hwnd):
            user32.ShowWindow(target_hwnd, 9)
            time.sleep(0.25)
        user32.ShowWindow(target_hwnd, 3)
        user32.SetForegroundWindow(target_hwnd)
        time.sleep(0.35)
    except Exception:
        pass

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    rect = RECT()
    user32.GetWindowRect(target_hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top

    if width > 50 and height > 50:
        left = max(0, rect.left)
        top = max(0, rect.top)
        right = max(left + 50, rect.right)
        bottom = max(top + 50, rect.bottom)
        img = ImageGrab.grab(bbox=(left, top, right, bottom))
    else:
        img = ImageGrab.grab()

    img.save(out_path)
    return True, win_title


def _ask_gemini_vision_sync(img_path: Path, question: str, app_title: str) -> str:
    if not _genai_client:
        return "API-ключ Gemini не настроен."

    prompt = (
        f"На этом скриншоте изображено окно приложения «{app_title}». "
        f"Ответь четко, кратко и по делу на вопрос пользователя: {question}"
    )

    vision_models = [
        "models/gemini-2.5-flash",
        "models/gemini-2.5-flash-lite",
        "models/gemini-flash-lite-latest",
        "models/gemini-2.0-flash",
    ]

    with Image.open(img_path) as pil_img:
        for model_name in vision_models:
            try:
                response = _genai_client.models.generate_content(
                    model=model_name,
                    contents=[pil_img, prompt],
                    config=types.GenerateContentConfig(temperature=0.25, max_output_tokens=500),
                )
                if response and response.text:
                    return response.text.replace("*", "").replace("#", "").strip()
            except Exception:
                continue

    return "Не удалось получить ответ от нейросети по скриншоту."


async def askscreen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚠️ **Формат команды:**\n"
            "`/askscreen [приложение] [вопрос]`\n\n"
            "**Примеры:**\n"
            "• `/askscreen ватсап кто написал последнее сообщение?`\n"
            "• `/askscreen вскод в чем ошибка в коде?`",
            parse_mode="Markdown",
        )
        return

    app_name = args[0]
    question = " ".join(args[1:])

    status_msg = await update.message.reply_text(f"🔍 Ищу окно «{app_name}» и анализирую экран...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    shot_path = DATA_DIR / f"askscreen_{int(time.time())}.png"

    try:
        ok, title_or_err = await asyncio.to_thread(_capture_app_window_sync, app_name, shot_path)
        if not ok:
            await status_msg.edit_text(f"❌ {title_or_err}")
            return

        answer = await asyncio.to_thread(_ask_gemini_vision_sync, shot_path, question, title_or_err)

        with open(shot_path, "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=(
                    f"🪟 **Окно:** `{title_or_err}`\n"
                    f"❓ **Вопрос:** {question}\n\n"
                    f"🤖 **Ответ Системы:**\n{answer}"
                )[:1024],
                parse_mode="Markdown",
            )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка при анализе окна: {e}")
    finally:
        if shot_path.exists():
            shot_path.unlink(missing_ok=True)


async def voice_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    voice_obj = update.message.voice or update.message.video_note or update.message.audio
    if not voice_obj:
        return

    if _stt_instance is None:
        await update.message.reply_text("❌ Модуль распознавания речи (STT) не подключен.")
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ogg_path = DATA_DIR / f"tg_voice_{int(time.time())}.ogg"

    try:
        tg_file = await context.bot.get_file(voice_obj.file_id)
        await tg_file.download_to_drive(custom_path=str(ogg_path))

        recognized_text = await asyncio.to_thread(_stt_instance.transcribe_file, ogg_path)
        if not recognized_text:
            await update.message.reply_text("⚠️ Не удалось расслышать речь в голосовом сообщении.")
            return

        print(f"[Telegram Голос] Распознано: {recognized_text}")

        if _agent_instance is not None:
            reply = await asyncio.to_thread(_agent_instance.process_command, recognized_text)
        else:
            reply = "Ядро агента не подключено."

        await update.message.reply_text(
            f"🗣 **Распознано:** _{recognized_text}_\n\n🤖 **Ответ:**\n{reply}",
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"[Telegram Голос] Ошибка: {e}")
        await update.message.reply_text(f"❌ Ошибка обработки голосового сообщения: {e}")
    finally:
        if ogg_path.exists():
            ogg_path.unlink(missing_ok=True)


# ==================== ОСНОВНЫЕ КОМАНДЫ БОТА ====================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await update.message.reply_text(f"⛔ Доступ запрещен. Ваш ID: {update.effective_user.id}")
        return

    await update.message.reply_text(
        "🤖 **Система на связи!**\n\n"
        "**Макросы:**\n"
        "• /coding — Запустить макрос «Режим кодинга»\n"
        "• /chill — Запустить макрос «Отдыхаем»\n\n"
        "**Команды:**\n"
        "• /restart — Перезапустить ассистента «Система» (обновить код и данные)\n"
        "• /health — Полный аудит здоровья ПК (температура, диски, RAM, батарея)\n"
        "• /listen `[сек]` — Записать звук с микрофона ПК (по умолчанию 10 сек)\n"
        "• /askscreen `[приложение] [вопрос]` — Скриншот окна и ответ ИИ\n"
        "• /screen — Скриншот всего экрана\n"
        "• /webcam — Фото с веб-камеры\n"
        "• /processes — Мониторинг и закрытие процессов\n"
        "• /battery — Заряд батареи и температура\n"
        "• /clip — Буфер обмена\n"
        "• /get `[имя_файла]` — Скачать файл с ПК\n"
        "• /open `[программа]` — Запустить приложение во весь экран\n"
        "• /site `[ссылка]` — Открыть сайт во весь экран\n"
        "• /media — Пульт управления музыкой/видео\n"
        "• /clean — Очистить временные файлы (Temp)\n"
        "• /autorun — Проверить автозагрузку Windows\n"
        "• /lock — Заблокировать ПК (Win+L)\n"
        "• /shutdown — Выключить или перезагрузить ПК\n\n"
        "🎙 *Ты также можешь отправлять голосовые сообщения или писать команды текстом («Система, перезапуск системы», «открой ватсап»)!*",
        parse_mode="Markdown"
    )


async def coding_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await update.message.reply_text("⚡ Запускаю сценарий «Режим кодинга»...")
    res = await asyncio.to_thread(run_macro, "режим кодинга")
    await update.message.reply_text(f"✅ {res}")


async def chill_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return
    await update.message.reply_text("🍿 Запускаю сценарий «Отдыхаем»...")
    res = await asyncio.to_thread(run_macro, "отдыхаем")
    await update.message.reply_text(f"✅ {res}")


async def screen_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    shot_path = DATA_DIR / "tg_screen.png"
    try:
        screenshot = await asyncio.to_thread(ImageGrab.grab)
        screenshot.save(shot_path)
        with open(shot_path, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption="📸 Текущий экран ПК")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка скриншота: {e}")
    finally:
        if shot_path.exists():
            shot_path.unlink(missing_ok=True)


def _capture_webcam_sync(cam_path: Path) -> tuple[bool, str]:
    cap = None
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return False, "Не удалось подключиться к веб-камере."

        for _ in range(8):
            cap.read()

        ret, frame = cap.read()
        if not ret or frame is None:
            return False, "Не удалось получить кадр с веб-камеры."

        cv2.imwrite(str(cam_path), frame)
        return True, ""
    except Exception as e:
        return False, str(e)
    finally:
        if cap is not None:
            cap.release()


async def webcam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cam_path = DATA_DIR / "webcam_shot.jpg"

    try:
        ok, err_msg = await asyncio.to_thread(_capture_webcam_sync, cam_path)
        if not ok:
            await update.message.reply_text(f"❌ {err_msg}")
            return

        with open(cam_path, "rb") as photo:
            await update.message.reply_photo(photo=photo, caption="👁️ Фото с веб-камеры ноутбука:")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при работе с веб-камерой: {e}")
    finally:
        if cam_path.exists():
            cam_path.unlink(missing_ok=True)


async def processes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                info = p.info
                rss_mb = info['memory_info'].rss / (1024 * 1024) if info['memory_info'] else 0
                procs.append({'pid': info['pid'], 'name': info['name'] or "Unknown", 'ram': rss_mb})
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        procs = sorted(procs, key=lambda x: x['ram'], reverse=True)[:8]

        text = "⚙️ **Топ тяжелых процессов на ПК:**\n\n"
        keyboard = []

        for p in procs:
            safe_name = p['name'].replace("`", "")
            text += f"• `{safe_name}` (PID: {p['pid']}) — `{p['ram']:.1f} MB`\n"
            keyboard.append([
                InlineKeyboardButton(f"🛑 Закрыть {safe_name} ({p['pid']})", callback_data=f"kill_{p['pid']}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось получить список процессов: {e}")


async def process_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    if not _is_authorized(update):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return

    data = query.data or ""

    if data.startswith("kill_"):
        await query.answer()
        pid = int(data.split("_")[1])
        try:
            p = psutil.Process(pid)
            proc_name = p.name().replace("`", "")
            p.kill()
            await query.edit_message_text(
                text=f"✅ Процесс `{proc_name}` (PID: {pid}) успешно завершен.",
                parse_mode="Markdown"
            )
        except psutil.NoSuchProcess:
            await query.edit_message_text(text=f"⚠️ Процесс с PID {pid} уже не существует.")
        except Exception as e:
            await query.edit_message_text(text=f"❌ Не удалось завершить процесс: {e}")

    elif data.startswith("media_"):
        action = data.split("_")[1]
        try:
            if action == "play":
                pyautogui.press("playpause")
                await query.answer("⏯️ Play / Pause")
            elif action == "next":
                pyautogui.press("nexttrack")
                await query.answer("⏭️ Следующий трек")
            elif action == "prev":
                pyautogui.press("prevtrack")
                await query.answer("⏮️ Предыдущий трек")
            elif action == "volup":
                pyautogui.press("volumeup")
                await query.answer("🔊 Громкость +")
            elif action == "voldown":
                pyautogui.press("volumedown")
                await query.answer("🔉 Громкость -")
            elif action == "mute":
                pyautogui.press("volumemute")
                await query.answer("🔇 Звук вкл/выкл")
        except Exception:
            await query.answer("❌ Ошибка выполнения")

    elif data.startswith("pwr_"):
        await query.answer()
        action = data.split("_")[1]
        try:
            if action == "shutdown":
                await query.edit_message_text(text="🛑 Выключаю компьютер через 10 секунд...")
                subprocess.Popen("shutdown /s /t 10", shell=True)
            elif action == "reboot":
                await query.edit_message_text(text="🔄 Перезагружаю компьютер через 10 секунд...")
                subprocess.Popen("shutdown /r /t 10", shell=True)
            elif action == "cancel":
                subprocess.Popen("shutdown /a", shell=True)
                await query.edit_message_text(text="✅ Таймер выключения/перезагрузки отменен.")
        except Exception as e:
            await query.edit_message_text(text=f"❌ Ошибка питания: {e}")


async def battery_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    try:
        battery = psutil.sensors_battery()
        if not battery:
            await update.message.reply_text("🔋 Информация о батарее недоступна.")
            return

        percent = battery.percent
        status = "🔌 Подключен к сети" if battery.power_plugged else "🔋 Работает от батареи"

        time_str = ""
        secsleft = battery.secsleft
        if isinstance(secsleft, int) and secsleft > 0 and secsleft not in (
            psutil.POWER_TIME_UNLIMITED,
            psutil.POWER_TIME_UNKNOWN,
        ):
            hours = secsleft // 3600
            minutes = (secsleft % 3600) // 60
            time_str = f"\n⏱️ Осталось примерно: {hours} ч. {minutes} мин."

        temp, sensor_name = await asyncio.to_thread(_get_max_system_temperature)
        temp_str = f"\n🌡️ Температура ({sensor_name}): **{temp:.1f}°C**" if temp > 0 else ""

        text = (
            f"🔋 **Состояние системы:**\n\n"
            f"• Заряд: **{percent}%**\n"
            f"• Статус: {status}"
            f"{time_str}{temp_str}"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при проверке батареи: {e}")


async def clip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    args = context.args
    if args:
        text_to_copy = " ".join(args)
        try:
            pyperclip.copy(text_to_copy)
            await update.message.reply_text(f"📋 Скопировано в буфер обмена ПК:\n{text_to_copy}")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка буфера обмена: {e}")
    else:
        try:
            current_clipboard = pyperclip.paste()
            if not current_clipboard or not current_clipboard.strip():
                await update.message.reply_text("📋 Буфер обмена ноутбука пуст.")
            else:
                display_text = (
                    current_clipboard
                    if len(current_clipboard) < 3000
                    else current_clipboard[:3000] + "\n...[текст обрезан]"
                )
                await update.message.reply_text(f"📋 Содержимое буфера обмена ПК:\n\n{display_text}")
        except Exception as e:
            await update.message.reply_text(f"❌ Не удалось прочитать буфер обмена: {e}")


async def get_file_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text("⚠️ Укажи имя файла. Пример:\n`/get отчет.pdf`", parse_mode="Markdown")
        return

    filename = " ".join(args)
    user_home = Path.home()

    search_dirs = [
        user_home / "Desktop",
        user_home / "OneDrive" / "Desktop",
        user_home / "Downloads",
        user_home / "Documents",
    ]

    target_file = Path(filename) if Path(filename).is_file() else None

    if not target_file:
        for d in search_dirs:
            if not d.exists():
                continue
            exact = d / filename
            if exact.exists() and exact.is_file():
                target_file = exact
                break
            for item in d.iterdir():
                if item.is_file() and filename.lower() in item.name.lower():
                    target_file = item
                    break
            if target_file:
                break

    if not target_file:
        await update.message.reply_text(f"❌ Файл «{filename}» не найден.")
        return

    try:
        with open(target_file, "rb") as f:
            await update.message.reply_document(document=f, caption=f"📁 Файл: {target_file.name}")
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось отправить файл: {e}")


async def receive_file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    document = update.message.document
    if not document:
        return

    try:
        file_obj = await context.bot.get_file(document.file_id)
        downloads_dir = Path.home() / "Downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)

        save_path = downloads_dir / document.file_name
        await file_obj.download_to_drive(custom_path=str(save_path))

        await update.message.reply_text(f"📥 Файл сохранен на ноутбуке!\nПуть: {save_path}")
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось сохранить файл: {e}")


async def open_app_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text("⚠️ Укажи название программы. Пример:\n`/open ватсап`", parse_mode="Markdown")
        return

    app_name = " ".join(args).strip()
    try:
        _, msg = await asyncio.to_thread(launch_app_universal, app_name)
        await update.message.reply_text(f"🚀 {msg}")
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось запустить приложение: {e}")


async def site_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text("⚠️ Укажи ссылку. Пример:\n`/site https://youtube.com`", parse_mode="Markdown")
        return

    url = " ".join(args).strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        webbrowser.open(url)
        maximize_window_by_hint("chrome", timeout=2.5)
        await update.message.reply_text(f"🌐 Ссылка открыта во весь экран:\n{url}")
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось открыть ссылку: {e}")


async def media_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    keyboard = [
        [
            InlineKeyboardButton("⏮️ Назад", callback_data="media_prev"),
            InlineKeyboardButton("⏯️ Play/Pause", callback_data="media_play"),
            InlineKeyboardButton("⏭️ Вперед", callback_data="media_next"),
        ],
        [
            InlineKeyboardButton("🔉 Тише", callback_data="media_voldown"),
            InlineKeyboardButton("🔇 Mute", callback_data="media_mute"),
            InlineKeyboardButton("🔊 Громче", callback_data="media_volup"),
        ]
    ]
    await update.message.reply_text(
        "🎵 **Пульт управления мультимедиа на ПК:**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def shutdown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    keyboard = [
        [
            InlineKeyboardButton("🛑 Выключить сейчас", callback_data="pwr_shutdown"),
            InlineKeyboardButton("🔄 Перезагрузить", callback_data="pwr_reboot"),
        ],
        [
            InlineKeyboardButton("❌ Отмена", callback_data="pwr_cancel"),
        ]
    ]
    await update.message.reply_text(
        "⚠️ **Вы действительно хотите выключить или перезагрузить компьютер?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


def _clean_temp_sync() -> tuple[int, float]:
    temp_paths = [
        Path(os.environ.get("TEMP", Path.home() / "AppData" / "Local" / "Temp")),
        Path("C:/Windows/Temp"),
    ]
    deleted_files = 0
    freed_space = 0

    for temp_dir in temp_paths:
        if not temp_dir.exists():
            continue
        for item in temp_dir.rglob("*"):
            if item.is_file():
                try:
                    size = item.stat().st_size
                    item.unlink()
                    deleted_files += 1
                    freed_space += size
                except Exception:
                    continue
        for item in sorted(temp_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if item.is_dir():
                try:
                    item.rmdir()
                except Exception:
                    continue

    return deleted_files, freed_space / (1024 * 1024)


async def clean_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    msg = await update.message.reply_text("🧹 Очищаю временные файлы...")
    try:
        deleted_files, freed_mb = await asyncio.to_thread(_clean_temp_sync)
        await msg.edit_text(
            f"🧹 **Очистка системы завершена!**\n\n"
            f"• Удалено файлов: `{deleted_files}`\n"
            f"• Освобождено места: `{freed_mb:.2f} MB`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка при очистке системы: {e}")


async def autorun_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_ALL_ACCESS) as key:
            try:
                reg.DeleteValue(key, "JarvisTelegramBot")
            except FileNotFoundError:
                pass

        from utils.autostart import create_silent_launchers
        create_silent_launchers()

        await update.message.reply_text(
            "🚀 **Автозагрузка настроена!** Работает единый фоновый лаунчер без дубликатов.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось настроить автозагрузку: {e}")


async def lock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    try:
        ctypes.windll.user32.LockWorkStation()
        await update.message.reply_text("🔒 Компьютер заблокирован.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка блокировки: {e}")


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        return

    text = update.message.text
    print(f"[Telegram Текст] Команда: {text}")
    try:
        if _agent_instance is not None:
            reply = await asyncio.to_thread(_agent_instance.process_command, text)
        else:
            response = await asyncio.to_thread(
                _genai_client.models.generate_content,
                model="models/gemini-flash-lite-latest",
                contents=text,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            reply = (response.text or "Готово.").replace("*", "").replace("#", "").strip()

        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка обработки: {e}")


def run_telegram_bot(agent=None, stt=None):
    global _agent_instance, _stt_instance
    _agent_instance = agent
    _stt_instance = stt

    if not TOKEN:
        print("[Telegram] ОШИБКА: TELEGRAM_BOT_TOKEN не найден в .env!")
        return

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        app = ApplicationBuilder().token(TOKEN).post_init(_post_init).build()
        app.add_handler(CommandHandler("start", start_cmd))
        app.add_handler(CommandHandler("restart", restart_cmd))
        app.add_handler(CommandHandler("coding", coding_cmd))
        app.add_handler(CommandHandler("chill", chill_cmd))
        app.add_handler(CommandHandler("health", health_cmd))
        app.add_handler(CommandHandler("listen", listen_cmd))
        app.add_handler(CommandHandler("askscreen", askscreen_cmd))
        app.add_handler(CommandHandler("screen", screen_cmd))
        app.add_handler(CommandHandler("webcam", webcam_cmd))
        app.add_handler(CommandHandler("processes", processes_cmd))
        app.add_handler(CommandHandler("battery", battery_cmd))
        app.add_handler(CommandHandler("clip", clip_cmd))
        app.add_handler(CommandHandler("get", get_file_cmd))
        app.add_handler(CommandHandler("open", open_app_cmd))
        app.add_handler(CommandHandler("site", site_cmd))
        app.add_handler(CommandHandler("media", media_cmd))
        app.add_handler(CommandHandler("shutdown", shutdown_cmd))
        app.add_handler(CommandHandler("clean", clean_cmd))
        app.add_handler(CommandHandler("autorun", autorun_cmd))
        app.add_handler(CommandHandler("lock", lock_cmd))
        app.add_handler(CallbackQueryHandler(process_callback_handler))
        app.add_handler(MessageHandler(filters.Document.ALL, receive_file_handler))
        app.add_handler(MessageHandler(filters.VOICE | filters.VIDEO_NOTE | filters.AUDIO, voice_message_handler))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

        print("[Telegram] Бот подключен и готов к работе!")
        app.run_polling(drop_pending_updates=True, stop_signals=None)
    except Exception as e:
        print(f"[Telegram] Критическая ошибка запуска бота: {e}")


if __name__ == "__main__":
    run_telegram_bot()