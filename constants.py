import os
import platform
from pathlib import Path

# Снапшот критических переменных окружения GUI-сессии
# (могут потеряться при sudo/pkexec)
_gui_env_snapshot = {}
if platform.system().lower() == "linux":
    for _var in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_RUNTIME_DIR",
                 "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE", "GDK_BACKEND"):
        _val = os.environ.get(_var)
        if _val:
            _gui_env_snapshot[_var] = _val

# Пути к файлам
URL_FILE = Path("URL.txt")
CORE_BINARY = "prizrak-core.exe" if platform.system().lower() == "windows" else "prizrak-core"
CORE_LOG = Path("VPN.log")
DASHBOARD_LOG = Path("panel.log")
PROFILE_DIR = Path("zashboard-profile")
ZASHBOARD_DIR = Path("zashboard")
ARCHIVES_DIR = Path("archives")
CONFIG_CLEAN = Path("config.yaml")
CONFIG_SMART = Path("smart-config.yaml")
MIRRORS_FILE = Path("mirrors.txt")
SETTINGS_FILE = Path("settings.json")

# Репозитории
CORE_REPO = "legiz-ru/Prizrak-Core"
ZASHBOARD_REPO = "Zephyruso/zashboard"

# Настройки
MAX_ARCHIVES = 3
FORCE_ADMIN_AT_START = True

# Зеркала GitHub по умолчанию
DEFAULT_MIRRORS = [
    "https://ghproxy.net/",
    "https://ghfast.top/",
    "https://gh-proxy.org/",
]

# Дефолтные настройки (language живёт здесь же)
DEFAULT_SETTINGS = {
    "smart_enabled": True,
    "language": "ru",
}

# Шаблоны шумных строк Chromium
DASHBOARD_NOISE = (
    "ResizeObserver",
    "ssl_client_socket_impl.cc",
    "WebGPU",
    "THREE.",
    "Registered new object",
)

# Цвета для вывода
PURPLE = "\033[95m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

# ASCII-арт шапка
ASCII_HEADER = r"""
                                         /$$                 /$$
                                        | $$                |__/
 /$$    /$$ /$$$$$$   /$$$$$$   /$$$$$$ | $$   /$$  /$$$$$$  /$$
|  $$  /$$/|____  $$ /$$__  $$ /$$__  $$| $$  /$$/ |____  $$| $$
 \  $$/$$/  /$$$$$$$| $$  \__/| $$$$$$$$| $$$$$$/   /$$$$$$$| $$
  \  $$$/  /$$__  $$| $$      | $$_____/| $$_  $$  /$$__  $$| $$
   \  $/  |  $$$$$$$| $$      |  $$$$$$$| $$ \  $$|  $$$$$$$| $$
    \_/    \_______/|__/       \_______/|__/  \__/ \_______/|__/
"""
