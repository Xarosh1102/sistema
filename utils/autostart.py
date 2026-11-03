import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def get_startup_vbs_path() -> Path:
    """Возвращает путь к VBS-скрипту в системной папке автозагрузки Windows."""
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup_dir.mkdir(parents=True, exist_ok=True)
    return startup_dir / "Sistema_Voice_Agent.vbs"


def _find_venv_pythonw() -> Path:
    """Находит pythonw.exe внутри виртуального окружения venv проекта."""
    candidates = [
        BASE_DIR / "venv" / "Scripts" / "pythonw.exe",
        BASE_DIR / ".venv" / "Scripts" / "pythonw.exe",
        Path(sys.executable).parent / "pythonw.exe",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return Path(sys.executable).resolve()


def create_silent_launchers() -> str:
    """
    Создает тихий VBS-лаунчер в папке автозагрузки Windows и в папке проекта,
    жестко фиксируя рабочую директорию и виртуальное окружение venv.
    """
    pythonw_exe = _find_venv_pythonw()
    main_py = (BASE_DIR / "main.py").resolve()
    work_dir = str(BASE_DIR.resolve())

    vbs_content = (
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.CurrentDirectory = "{work_dir}"\r\n'
        f'WshShell.Run """{pythonw_exe}"" ""{main_py}""", 0, False\r\n'
        'Set WshShell = Nothing\r\n'
    )

    # 1. Записываем лаунчер в папку автозагрузки Windows (Startup)
    startup_vbs = get_startup_vbs_path()
    with open(startup_vbs, "w", encoding="mbcs", errors="ignore") as f:
        f.write(vbs_content)

    # 2. Записываем копию лаунчера в корень проекта для ручного тихого запуска
    local_vbs = BASE_DIR / "run_silent.vbs"
    with open(local_vbs, "w", encoding="mbcs", errors="ignore") as f:
        f.write(vbs_content)

    return str(startup_vbs)