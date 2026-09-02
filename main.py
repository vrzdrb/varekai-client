#!/usr/bin/env python3
"""
Varekai-client
"""

import os
import sys
import platform
import subprocess
import shutil
import zipfile
import gzip
import time
import signal
import threading
import urllib.parse
import requests
from pathlib import Path
from datetime import datetime

# При запуске из бинарника PyInstaller меняем рабочую директорию
# на папку бинарника, чтобы все относительные пути (config.yaml, URL.txt и т.д.)
# работали правильно, а не относительно папки _internal
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).resolve().parent)
else:
    os.chdir(Path(__file__).resolve().parent)

# Сохраняем критические переменные окружения GUI-сессии при старте
# (они могут потеряться при sudo -E)
_gui_env_snapshot = {}
if platform.system().lower() == "linux":
    for var in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_RUNTIME_DIR",
                "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE", "GDK_BACKEND"):
        val = os.environ.get(var)
        if val:
            _gui_env_snapshot[var] = val
    # На Linux принудительно используем PySide6 для Qt-бэкенда
    os.environ.setdefault("QT_API", "pyside6")

# === КОНСТАНТЫ ===
URL_FILE = Path("URL.txt")
CORE_BINARY = "mihomo-core.exe" if platform.system().lower() == "windows" else "mihomo-core"
CORE_LOG = Path("mihomo-core.log")
DASHBOARD_LOG = Path("zashboard.log")
PROFILE_DIR = Path("zashboard-profile")
ZASHBOARD_DIR = Path("zashboard")
ARCHIVES_DIR = Path("archives")
MAX_ARCHIVES = 3  # Хранить latest + 2 предыдущих

# Принудительный запрос прав администратора на старте (только не на Linux:
# там скрипт работает от пользователя, а ядро поднимается через pkexec)
FORCE_ADMIN_AT_START = True

# Шаблоны шумных строк Chromium, которые не пишем в лог панели
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

# Глобальная переменная для хранения процесса ядра (если запущен из этого экземпляра)
core_process = None


# === УТИЛИТЫ ===
def print_success(msg):
    print(f"{GREEN}[+] {msg}{RESET}")

def print_error(msg):
    print(f"{RED}[-] {msg}{RESET}")

def print_info(msg):
    print(f"{YELLOW}{msg}{RESET}")

def print_purple(msg):
    print(f"{PURPLE}{msg}{RESET}")

def print_menu_item(number, text):
    """Выводит пункт меню: цифра фиолетовая, текст жёлтый"""
    print(f"{PURPLE} {number}.{RESET} {YELLOW}{text}{RESET}")

def clear_screen():
    if platform.system().lower() == "windows":
        os.system('cls')
    else:
        # ANSI-коды вместо os.system('clear'): не запускаем sh,
        # чтобы избежать конфликта упакованного в бинарник libreadline
        # с системным (ошибка "undefined symbol: rl_print_keybinding")
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

def get_script_dir():
    """Возвращает директорию, где лежит скрипт (или бинарник)"""
    if getattr(sys, "frozen", False):
        # sys.executable указывает на бинарник, а не на _internal
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


# === ПРОВЕРКА ПРАВ АДМИНИСТРАТОРА ===
def is_admin():
    """Проверяет, запущен ли скрипт с правами администратора"""
    try:
        if platform.system().lower() == "windows":
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.getuid() == 0
    except:
        return False

def restart_as_admin():
    """Перезапускает скрипт с правами администратора"""
    if is_admin():
        return True

    try:
        if platform.system().lower() == "windows":
            import ctypes
            params = subprocess.list2cmdline(sys.argv[1:]) if len(sys.argv) > 1 else None
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, None, 1
            )
            sys.exit(0)
        elif platform.system().lower() == "darwin":
            args_str = " ".join(sys.argv)
            script = (
                'do shell script "'
                + sys.executable + " " + args_str +
                '" with administrator privileges'
            )
            subprocess.Popen(["osascript", "-e", script])
            sys.exit(0)
        else:
            # Linux: sudo с явной передачей GUI-переменных
            if shutil.which("sudo"):
                os.execvp("sudo", ["sudo", "-E", "env"] +
                          [f"{k}={v}" for k, v in _gui_env_snapshot.items()] +
                          sys.argv)
            elif shutil.which("pkexec"):
                os.execvp("pkexec", ["pkexec"] + sys.argv)
            else:
                print_error("Не найден механизм для запуска с правами администратора")
                return False
    except Exception as e:
        print_error(f"Ошибка при запросе прав администратора: {e}")
        return False

    return True


# === ОКРУЖЕНИЕ GUI ===
def setup_gui_environment():
    """Настраивает переменные окружения для панели на Linux"""
    if get_os() != "linux":
        return
    os.environ.setdefault("QT_API", "pyside6")
    # Подавляем отладочный шум Qt
    os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")


# === ОПРЕДЕЛЕНИЕ АРХИТЕКТУРЫ ===
def get_os():
    """Определяет операционную систему"""
    os_name = platform.system().lower()
    if os_name == "windows":
        return "windows"
    elif os_name == "darwin":
        return "darwin"
    elif os_name == "linux":
        return "linux"
    return "linux"

def get_arch():
    """Определяет архитектуру процессора"""
    machine = platform.machine().lower()

    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("x86", "i386", "i686"):
        return "386" if get_os() == "windows" else "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"

    return "amd64"

def check_avx2_support():
    """Проверяет поддержку AVX2 на процессоре"""
    try:
        if get_os() == "linux":
            with open("/proc/cpuinfo", "r") as f:
                return "avx2" in f.read().lower()
        elif get_os() == "windows":
            try:
                result = subprocess.run(
                    ["wmic", "cpu", "get", "name"],
                    capture_output=True, text=True, timeout=5
                )
                cpu_name = result.stdout.lower()
                old_cpus = ["pentium", "celeron", "atom"]
                return not any(old in cpu_name for old in old_cpus)
            except:
                return True
        elif get_os() == "darwin":
            return True
    except:
        pass
    return False

def get_latest_archived_version():
    """Возвращает тег версии последнего архива ядра для текущей платформы"""
    prefix = f"mihomo-{get_os()}-{get_arch()}-"
    archives = [a for a in ARCHIVES_DIR.glob("mihomo-*") if a.name.startswith(prefix)]
    if not archives:
        return None

    latest = max(archives, key=lambda x: x.stat().st_mtime)
    tag = latest.name[len(prefix):]
    for ext in (".gz", ".zip"):
        if tag.endswith(ext):
            tag = tag[:-len(ext)]
    return tag

def get_current_core_info():
    """Возвращает информацию о текущем ядре (ОС, архитектура, версия)"""
    os_name = get_os()
    arch = get_arch()
    avx2 = check_avx2_support()

    if os_name == "windows" and arch == "amd64":
        variant = "compatible" if not avx2 else "v3"
    else:
        variant = "v3"

    version = get_latest_archived_version() or "не установлено"
    return f"mihomo | {os_name}-{arch} | {variant} | {version}"


# === УПРАВЛЕНИЕ АРХИВАМИ ===
def ensure_dirs():
    """Создаёт необходимые директории"""
    ARCHIVES_DIR.mkdir(exist_ok=True)
    ZASHBOARD_DIR.mkdir(exist_ok=True)

def save_archive(archive_path, version_tag):
    """Сохраняет архив в папку архивов"""
    ensure_dirs()

    ext = archive_path.suffix
    archive_name = f"mihomo-{get_os()}-{get_arch()}-{version_tag}{ext}"
    dest_path = ARCHIVES_DIR / archive_name

    if not dest_path.exists():
        shutil.copy2(archive_path, dest_path)

    cleanup_old_archives()

def cleanup_old_archives():
    """Удаляет старые архивы, оставляя только MAX_ARCHIVES последних"""
    archives = sorted(
        ARCHIVES_DIR.glob("mihomo-*"),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )

    for old_archive in archives[MAX_ARCHIVES:]:
        try:
            old_archive.unlink()
        except:
            pass

def get_available_archives():
    """Возвращает список доступных архивов для отката"""
    if not ARCHIVES_DIR.exists():
        return []

    return sorted(
        ARCHIVES_DIR.glob("mihomo-*"),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )

def find_archived_archive(version_tag):
    """Ищет архив ядра с указанным тегом версии"""
    prefix = f"mihomo-{get_os()}-{get_arch()}-{version_tag}"
    for a in ARCHIVES_DIR.glob("mihomo-*"):
        if a.name.startswith(prefix):
            return a
    return None

def extract_archive(archive_path, extract_to):
    """Распаковывает архив"""
    try:
        if str(archive_path).endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                zip_ref.extractall(extract_to)
        elif str(archive_path).endswith(".gz"):
            with gzip.open(archive_path, "rb") as f_in:
                binary_name = Path(archive_path).stem
                binary_path = Path(extract_to) / binary_name
                with open(binary_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        return True, None
    except Exception as e:
        return False, str(e)

def rollback_to_version(archive_path):
    """Откатывает ядро на выбранную версию из архива"""
    try:
        current_binary = Path(CORE_BINARY)
        if current_binary.exists():
            current_binary.unlink()

        temp_dir = Path("temp_extract")
        temp_dir.mkdir(exist_ok=True)

        success, error = extract_archive(archive_path, temp_dir)
        if not success:
            print_error(f"Ошибка распаковки архива: {error}")
            return False

        binary_found = False
        for f in temp_dir.rglob("*"):
            if f.is_file() and not f.name.endswith(('.zip', '.gz')):
                shutil.copy2(f, CORE_BINARY)
                binary_found = True
                break

        shutil.rmtree(temp_dir, ignore_errors=True)

        if binary_found:
            if get_os() != "windows":
                os.chmod(CORE_BINARY, 0o755)
            print_success(f"Откат выполнен: {archive_path.name}")
            return True
        else:
            print_error("Бинарник не найден в архиве")
            return False

    except Exception as e:
        print_error(f"Ошибка при откате: {e}")
        return False


# === СКАЧИВАНИЕ ЯДРА ===
def get_latest_release_info():
    """Получает информацию о последнем релизе mihomo с GitHub"""
    try:
        response = requests.get(
            "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest",
            timeout=10,
            headers={"User-Agent": "Mihomo-Launcher"}
        )
        if response.status_code != 200:
            return None, "Нет связи с GitHub"

        return response.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Нет связи с GitHub"
    except Exception as e:
        return None, f"Ошибка: {e}"

def find_asset_for_platform(assets):
    """Ищет подходящий бинарник для текущей платформы"""
    os_name = get_os()
    arch = get_arch()
    avx2_supported = check_avx2_support()

    if arch == "amd64":
        target_microarch = "v3" if avx2_supported else "v1"
    else:
        target_microarch = None

    package_extensions = ('.deb', '.rpm', '.pkg.tar.zst')
    candidates = []

    for asset in assets:
        name = asset["name"].lower()

        if os_name not in name:
            continue
        if arch not in name:
            continue
        if any(name.endswith(ext) for ext in package_extensions):
            continue
        if os_name == "windows" and not name.endswith(".zip"):
            continue
        if os_name != "windows" and not name.endswith(".gz"):
            continue
        if "compatible" in name:
            continue

        if arch == "amd64" and target_microarch:
            if target_microarch == "v3":
                if "-v3-" not in name:
                    continue
            elif target_microarch == "v1":
                if "-v2-" in name or "-v3-" in name:
                    continue

        # Приоритет: 3 = без суффикса версии Go, 2 = с суффиксом версии Go
        has_go_suffix = any(f"-go{ver}-" in name for ver in ["120", "121", "122", "123", "124"])
        priority = 2 if has_go_suffix else 3

        candidates.append((priority, asset))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

def update_core():
    """Обновляет ядро mihomo до последней версии (только при наличии новой)"""
    print_info("Проверка обновлений ядра...")

    release, error = get_latest_release_info()
    if error:
        print_error(error)
        return False

    version_tag = release.get("tag_name", "unknown")

    # Сравниваем с последней сохранённой версией в archives/
    local_tag = get_latest_archived_version()
    if local_tag == version_tag:
        if Path(CORE_BINARY).exists():
            print_info(f"Ядро актуально (версия {version_tag}), скачивание не требуется")
            return True
        archived = find_archived_archive(version_tag)
        if archived:
            print_info("Бинарник не найден, разворачиваем из существующего архива...")
            return rollback_to_version(archived)

    assets = release.get("assets", [])
    if not assets:
        print_error("Последняя версия не содержит бинарных файлов")
        return False

    asset = find_asset_for_platform(assets)
    if not asset:
        print_error(f"Последняя версия не содержит бинарных файлов для {get_os()}-{get_arch()}")
        return False

    archive_path = Path(asset["name"])
    print_info(f"Скачивание {asset['name']}...")

    try:
        response = requests.get(asset["browser_download_url"], stream=True, timeout=30)
        if response.status_code != 200:
            print_error("Ошибка при скачивании файла")
            return False

        with open(archive_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    except Exception as e:
        print_error(f"Ошибка при скачивании: {e}")
        return False

    save_archive(archive_path, version_tag)

    temp_dir = Path("temp_extract")
    temp_dir.mkdir(exist_ok=True)

    success, error = extract_archive(archive_path, temp_dir)
    if not success:
        print_error(f"Ошибка распаковки: {error}")
        return False

    binary_found = False
    for f in temp_dir.rglob("*"):
        if f.is_file() and not f.name.endswith(('.zip', '.gz')):
            current_binary = Path(CORE_BINARY)
            if current_binary.exists():
                current_binary.unlink()

            shutil.copy2(f, CORE_BINARY)
            binary_found = True
            break

    shutil.rmtree(temp_dir, ignore_errors=True)
    archive_path.unlink()

    if binary_found:
        if get_os() != "windows":
            os.chmod(CORE_BINARY, 0o755)
        print_success(f"Ядро обновлено до версии {version_tag}")
        return True
    else:
        print_error("Бинарник не найден в архиве")
        return False


# === СКАЧИВАНИЕ ZASHBOARD ===
def get_zashboard_version():
    """Получает текущую версию zashboard из локального файла"""
    version_file = ZASHBOARD_DIR / "version.txt"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return None

def is_zashboard_valid():
    """Проверяет, что панель корректно распакована (index.html в корне папки)"""
    return (ZASHBOARD_DIR / "index.html").exists()

def get_latest_zashboard_release():
    """Получает информацию о последнем релизе zashboard"""
    try:
        response = requests.get(
            "https://api.github.com/repos/Zephyruso/zashboard/releases/latest",
            timeout=10,
            headers={"User-Agent": "Mihomo-Launcher"}
        )
        if response.status_code != 200:
            return None, "Нет связи с GitHub"

        return response.json(), None
    except requests.exceptions.ConnectionError:
        return None, "Нет связи с GitHub"
    except Exception as e:
        return None, f"Ошибка: {e}"

def update_zashboard():
    """Обновляет zashboard до последней версии"""
    print_info("Проверка обновлений zashboard...")

    release, error = get_latest_zashboard_release()
    if error:
        print_error(error)
        return False

    latest_version = release.get("tag_name", "unknown")
    current_version = get_zashboard_version()

    if current_version == latest_version and is_zashboard_valid():
        print_info(f"zashboard актуален (версия {current_version})")
        return True

    assets = release.get("assets", [])
    asset = None
    for a in assets:
        if "dist" in a["name"].lower() and a["name"].endswith(".zip"):
            asset = a
            break

    if not asset:
        print_error("Не найден архив с панелью управления")
        return False

    archive_path = Path("zashboard_temp.zip")
    print_info(f"Скачивание zashboard {latest_version}...")

    try:
        response = requests.get(asset["browser_download_url"], stream=True, timeout=30)
        if response.status_code != 200:
            print_error("Ошибка при скачивании панели")
            return False

        with open(archive_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    except Exception as e:
        print_error(f"Ошибка при скачивании панели: {e}")
        return False

    try:
        if ZASHBOARD_DIR.exists():
            shutil.rmtree(ZASHBOARD_DIR)
        ZASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            zip_ref.extractall(ZASHBOARD_DIR)

        # Файлы панели лежат внутри подпапки dist/, а ядро mihomo ожидает
        # их напрямую в корне папки external-ui. Перемещаем содержимое.
        dist_dir = ZASHBOARD_DIR / "dist"
        if dist_dir.exists() and dist_dir.is_dir():
            for item in list(dist_dir.iterdir()):
                dest = ZASHBOARD_DIR / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(item), str(dest))
            dist_dir.rmdir()

        (ZASHBOARD_DIR / "version.txt").write_text(latest_version, encoding="utf-8")

        archive_path.unlink()
        print_success(f"zashboard обновлён до версии {latest_version}")
        return True
    except Exception as e:
        print_error(f"Ошибка распаковки панели: {e}")
        return False


# === СКАЧИВАНИЕ ПРОФИЛЯ ===
def load_profile_url():
    """Загружает ссылку на профиль из URL.txt или запрашивает у пользователя"""
    if URL_FILE.exists():
        url = URL_FILE.read_text(encoding="utf-8").strip()
        if url:
            return url

    print_info("Файл конфигурации не найден.")
    print_info("Вставьте ссылку на профиль с настройками.")
    print_info("Для вставки используйте: Ctrl+Shift+V или Shift+Insert")

    url = input(f"{YELLOW}Ссылка на профиль: {RESET}").strip()

    if url:
        URL_FILE.write_text(url, encoding="utf-8")
        print_success("Ссылка сохранена в URL.txt")
        return url
    else:
        return ""

def validate_url(url):
    """Проверяет валидность URL"""
    if not url or not url.strip():
        return False, "Ссылка не задана"

    parsed = urllib.parse.urlparse(url)

    if not all([parsed.scheme, parsed.netloc]):
        return False, "Некорректная ссылка"

    if parsed.scheme not in ['http', 'https']:
        return False, "Ссылка должна начинаться с http:// или https://"

    return True, None

def update_profile():
    """Скачивает и обновляет пользовательский профиль"""
    profile_url = load_profile_url()

    if not profile_url:
        print_error("Ссылка на профиль не задана")
        return False

    valid, error = validate_url(profile_url)
    if not valid:
        print_error(error)
        return False

    print_info("Скачивание профиля...")

    try:
        response = requests.get(profile_url, timeout=15)

        if response.status_code == 401 or response.status_code == 403:
            print_error("Удалённый ресурс требует авторизации")
            return False

        if response.status_code != 200:
            print_error("Удалённый ресурс недоступен")
            return False

        Path("config.yaml").write_text(response.text, encoding="utf-8")
        print_success("Профиль успешно обновлён")
        return True

    except requests.exceptions.ConnectionError:
        print_error("Нет связи с удалённым ресурсом")
        return False
    except Exception as e:
        print_error(f"Ошибка при скачивании профиля: {e}")
        return False


# === УПРАВЛЕНИЕ ЯДРОМ ===
def get_core_pid():
    """Возвращает PID запущенного ядра или None"""
    try:
        if get_os() == "windows":
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {CORE_BINARY}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            lines = [l for l in result.stdout.splitlines() if CORE_BINARY.lower() in l.lower()]
            if lines:
                fields = lines[0].replace('"', '').split(',')
                return fields[1].strip() if len(fields) > 1 else None
            return None
        else:
            result = subprocess.run(
                ["pgrep", "-x", CORE_BINARY],
                capture_output=True, text=True, timeout=5
            )
            pids = result.stdout.split()
            return pids[0] if pids else None
    except:
        return None

def start_core():
    """Запускает ядро mihomo в фоне (отвязано от скрипта)"""
    global core_process

    # Если ядро уже работает - не запускаем второй экземпляр
    pid = get_core_pid()
    if pid:
        print_info(f"Ядро уже запущено (PID: {pid})")
        return True

    if not Path(CORE_BINARY).exists():
        print_error("Бинарник ядра не найден. Сначала выполните обновление.")
        return False

    if not Path("config.yaml").exists():
        print_error("Файл конфигурации не найден. Сначала обновите профиль.")
        return False

    try:
        script_dir = get_script_dir()
        binary_path = script_dir / CORE_BINARY
        config_path = script_dir / "config.yaml"
        ui_path = script_dir / "zashboard"

        # Логи ядра пишем в файл
        log_path = script_dir / CORE_LOG

        # Формируем базовую команду запуска
        base_cmd = [str(binary_path), "-f", str(config_path), "-ext-ui", str(ui_path)]

        # Если мы не root, нужно повысить права
        if not is_admin():
            if get_os() == "linux":
                # Linux: пробуем pkexec (графический запрос пароля через polkit)
                if shutil.which("pkexec"):
                    print_info("Запрос прав администратора через pkexec...")
                    # pkexec запускает команду от root с графическим запросом пароля
                    cmd = ["pkexec", "env", f"SAFE_PATHS={ui_path}"] + base_cmd
                    # pkexec не поддерживает start_new_session, но это нормально
                    with open(log_path, "wb") as core_log:
                        core_process = subprocess.Popen(
                            cmd,
                            stdout=core_log,
                            stderr=core_log,
                            cwd=str(script_dir)
                        )
                elif shutil.which("sudo"):
                    # sudo требует терминал для ввода пароля
                    print_error("sudo не может запросить пароль в этом контексте.")
                    print_info("Варианты решения:")
                    print_info("  1. Установите pkexec: sudo pacman -S polkit")
                    print_info("  2. Запустите скрипт через sudo: sudo python ./main.py")
                    return False
                else:
                    print_error("Не найден механизм для запуска от root")
                    print_info("Установите polkit: sudo pacman -S polkit")
                    return False
            elif get_os() == "windows":
                print_error("Для запуска ядра на Windows требуется запуск скрипта от администратора")
                print_info("Запустите скрипт через правый клик -> Запуск от имени администратора")
                return False
            else:  # macOS
                print_error("Для запуска ядра на macOS требуется запуск скрипта от администратора")
                print_info("Запустите скрипт через sudo: sudo python ./main.py")
                return False
        else:
            # Мы уже root
            env = os.environ.copy()
            env["SAFE_PATHS"] = str(ui_path)
            cmd = base_cmd

            with open(log_path, "wb") as core_log:
                if get_os() == "windows":
                    core_process = subprocess.Popen(
                        cmd,
                        stdout=core_log,
                        stderr=core_log,
                        env=env,
                        cwd=str(script_dir),
                        creationflags=(
                            subprocess.CREATE_NO_WINDOW
                            | subprocess.DETACHED_PROCESS
                            | subprocess.CREATE_NEW_PROCESS_GROUP
                        )
                    )
                else:
                    core_process = subprocess.Popen(
                        cmd,
                        stdout=core_log,
                        stderr=core_log,
                        env=env,
                        cwd=str(script_dir),
                        start_new_session=True
                    )

        # Даём ядру немного времени на старт
        time.sleep(2)

        # Проверяем, что процесс всё ещё жив
        if core_process.poll() is not None:
            error_output = log_path.read_text(errors="replace").strip()
            print_error(f"Ядро не запустилось. Ошибка: {error_output}")
            return False

        print_success(f"Ядро запущено (PID: {core_process.pid})")
        return True
    except PermissionError:
        print_error("Нет прав на исполнение бинарника ядра.")
        if get_os() != "windows":
            print_info("Попробуйте выполнить: chmod +x " + CORE_BINARY)
        return False
    except Exception as e:
        print_error(f"Не удалось запустить ядро: {e}")
        return False

def stop_core():
    """Останавливает процесс ядра (с запросом прав, если ядро работает от root)"""
    global core_process

    if get_core_pid() is None and core_process is None:
        print_info("Ядро не было запущено")
        return

    if get_os() == "windows":
        # На Windows скрипт работает от администратора (UAC), taskkill работает напрямую
        subprocess.run(["taskkill", "/F", "/IM", CORE_BINARY], capture_output=True)
    else:
        pkill_path = shutil.which("pkill") or "/usr/bin/pkill"
        if is_admin():
            subprocess.run([pkill_path, "-x", CORE_BINARY], capture_output=True)
        else:
            # Ядро запущено от root - для остановки нужны права
            print_info("Запрос прав администратора для остановки ядра...")
            if shutil.which("pkexec"):
                subprocess.run(["pkexec", pkill_path, "-x", CORE_BINARY], capture_output=True)
            elif shutil.which("sudo"):
                # sudo спросит пароль прямо в терминале
                subprocess.run(["sudo", pkill_path, "-x", CORE_BINARY])
            else:
                print_error("Не найден механизм для остановки ядра от root (pkexec/sudo)")
                return

    core_process = None

    # Проверяем реальный результат, а не верим себе на слово
    time.sleep(0.5)
    if get_core_pid() is None:
        print_info("Ядро остановлено")
    else:
        print_error("Не удалось остановить ядро")


# === ПАНЕЛЬ УПРАВЛЕНИЯ ===
def _start_stderr_filter(log_path):
    """Пропускает stderr Chromium через фильтр: шум отбрасывается,
    остальные строки пишутся в файл с нашей временной меткой"""
    try:
        read_fd, write_fd = os.pipe()
        os.dup2(write_fd, 2)
        os.close(write_fd)

        log_file = open(log_path, "ab", buffering=0)

        def pump():
            with os.fdopen(read_fd, "rb") as r:
                for line in r:
                    text = line.decode("utf-8", errors="replace")
                    if any(noise in text for noise in DASHBOARD_NOISE):
                        continue
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log_file.write(f"[{timestamp}] {text}".encode("utf-8"))
                    log_file.flush()

        t = threading.Thread(target=pump, daemon=True)
        t.start()
    except Exception:
        pass

def open_dashboard():
    """Открывает панель в окне самого скрипта.
    Закрытие окна панели = выход из программы (ядро продолжает работать)."""
    script_dir = get_script_dir()

    # Шум Chromium уходит в файл с временными метками
    _start_stderr_filter(script_dir / DASHBOARD_LOG)

    setup_gui_environment()

    port = 9090
    secret = ""

    try:
        import yaml
        config_path = script_dir / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                external_controller = config.get("external-controller", "127.0.0.1:9090")
                if ":" in external_controller:
                    port = int(external_controller.split(":")[-1])
                secret = config.get("secret", "")
    except ImportError:
        print_info("Модуль yaml не установлен, использую порт по умолчанию (9090)")
    except Exception as e:
        print_error(f"Ошибка чтения конфига: {e}")

    if secret:
        dashboard_url = f"http://127.0.0.1:{port}/ui/#/setup?hostname=127.0.0.1&port={port}&secret={secret}"
    else:
        dashboard_url = f"http://127.0.0.1:{port}/ui/#/setup?hostname=127.0.0.1&port={port}"

    print_info(f"Открытие панели управления: {dashboard_url}")

    try:
        import webview
        webview.create_window(
            title="Mihomo Dashboard",
            url=dashboard_url,
            width=1200,
            height=800,
            resizable=True
        )
        print_info("Панель открыта. Закрытие окна завершит программу.")
        webview.start(
            gui="qt" if get_os() == "linux" else None,
            private_mode=False,
            storage_path=str(script_dir / PROFILE_DIR)
        )
    except ImportError:
        print_error("Библиотека pywebview не найдена.")
        return
    except Exception as e:
        print_error(f"Ошибка открытия панели: {e}")
        return

    # Окно закрыли — выходим (ядро НЕ трогаем, оно работает независимо)
    print_info("Панель закрыта. Выход...")
    sys.exit(0)


# === ФУНКЦИИ МЕНЮ ===
def menu_update_and_run_with_dashboard():
    """Пункт 1: Обновление и запуск VPN с панелью управления"""
    core_updated = update_core()
    update_zashboard()

    if core_updated:
        # Если конфига нет вообще (первый запуск) - пытаемся скачать
        # до запуска ядра: без VPN может не получиться, но другого шанса нет
        if not Path("config.yaml").exists():
            update_profile()

        if start_core():
            time.sleep(3)  # даём TUN-интерфейсу время поднять маршрутизацию
            # Профиль обновляем ПОСЛЕ запуска ядра: запросы уже идут через
            # VPN, поэтому заблокированный ресурс доступен.
            # Новый конфиг применится при следующем запуске ядра.
            update_profile()
            open_dashboard()

    input(f"\n{YELLOW}Нажмите Enter для продолжения...{RESET}")

def menu_run_with_dashboard_no_update():
    """Пункт 2: [Без обновления] Запуск VPN с панелью управления"""
    if start_core():
        time.sleep(2)
        open_dashboard()

    input(f"\n{YELLOW}Нажмите Enter для продолжения...{RESET}")

def menu_open_dashboard_only():
    """Пункт 3: [Без обновления и запуска VPN] Только открыть панель управления"""
    open_dashboard()

    input(f"\n{YELLOW}Нажмите Enter для продолжения...{RESET}")

def menu_update_and_run_without_dashboard():
    """Пункт 4: [Без панели] Обновление и запуск VPN"""
    core_updated = update_core()

    if core_updated:
        if not Path("config.yaml").exists():
            update_profile()

        if start_core():
            time.sleep(3)
            update_profile()

    input(f"\n{YELLOW}Нажмите Enter для продолжения...{RESET}")

def menu_run_without_dashboard_no_update():
    """Пункт 5: [Без обновления и панели] Только запуск VPN"""
    start_core()

    input(f"\n{YELLOW}Нажмите Enter для продолжения...{RESET}")

def menu_update_only():
    """Пункт 6: [Без панели и запуска VPN] Только обновление"""
    update_core()
    update_zashboard()
    update_profile()

    input(f"\n{YELLOW}Нажмите Enter для продолжения...{RESET}")

def menu_change_profile_url():
    """Пункт 7: Изменить ссылку на профиль"""
    current_url = load_profile_url()
    print_info(f"Текущая ссылка: {current_url or 'не задана'}")

    new_url = input(f"{YELLOW}Введите новую ссылку (или пусто для отмены): {RESET}").strip()

    if new_url:
        valid, error = validate_url(new_url)
        if valid:
            URL_FILE.write_text(new_url, encoding="utf-8")
            print_success("Ссылка обновлена")
        else:
            print_error(error)

    input(f"\n{YELLOW}Нажмите Enter для продолжения...{RESET}")

def menu_rollback():
    """Пункт 8: Откат на предыдущую версию"""
    archives = get_available_archives()

    if not archives:
        print_error("Нет доступных архивов для отката")
        input(f"\n{YELLOW}Нажмите Enter для продолжения...{RESET}")
        return

    print_info("Доступные версии для отката:")
    for i, archive in enumerate(archives, 1):
        print_purple(f"  {i}. {archive.name}")

    print_purple("  0. Отмена")

    choice = input(f"{YELLOW}Выберите версию: {RESET}").strip()

    if choice == "0":
        return

    try:
        index = int(choice) - 1
        if 0 <= index < len(archives):
            rollback_to_version(archives[index])
        else:
            print_error("Неверный выбор")
    except ValueError:
        print_error("Неверный выбор")

    input(f"\n{YELLOW}Нажмите Enter для продолжения...{RESET}")

def menu_stop_vpn():
    """Пункт 9: Остановить VPN"""
    stop_core()

    input(f"\n{YELLOW}Нажмите Enter для продолжения...{RESET}")


# === ГЛАВНОЕ МЕНЮ ===
def show_menu():
    """Показывает главное меню"""
    clear_screen()

    print_purple(ASCII_HEADER)

    core_info = get_current_core_info()
    print_info(f"Текущее ядро: {core_info}")

    pid = get_core_pid()
    if pid:
        print_success(f"Статус ядра: запущено (PID: {pid})")
    else:
        print_error("Статус ядра: не запущено")

    print_purple("\n" + "=" * 70)
    print_menu_item("1", "Обновление и запуск VPN с панелью управления")
    print_menu_item("2", "[Без обновления] Запуск VPN с панелью управления")
    print_menu_item("3", "[Без обновления и запуска VPN] Только открыть панель управления")
    print_purple("+" * 70)
    print_menu_item("4", "[Без панели] Обновление и запуск VPN")
    print_menu_item("5", "[Без обновления и панели] Только запуск VPN")
    print_menu_item("6", "[Без панели и запуска VPN] Только обновление")
    print_menu_item("7", "Изменить ссылку на профиль с настройками")
    print_menu_item("8", "Откат на предыдущую версию")
    print_menu_item("9", "Остановить VPN")
    print_menu_item("0", "Выход")
    print_purple("=" * 70)


# === ГЛАВНАЯ ФУНКЦИЯ ===
def main():
    """Главная функция программы"""
    global core_process

    # Создаём необходимые директории
    ensure_dirs()

    # Принудительный запрос прав администратора (только не на Linux:
    # там GUI должен работать от пользователя, а ядро поднимается через pkexec)
    if FORCE_ADMIN_AT_START and get_os() != "linux" and not is_admin():
        print_info("Для работы программы требуются права администратора (TUN-режим).")
        print_info("Перезапуск с правами администратора...")
        time.sleep(1)
        if not restart_as_admin():
            print_error("Не удалось получить права администратора.")
            input(f"\n{YELLOW}Нажмите Enter для выхода...{RESET}")
            sys.exit(1)

    # Проверяем наличие ссылки на профиль при старте
    load_profile_url()

    # Обработчик выхода: ядро НЕ останавливаем - оно работает независимо
    def signal_handler(sig, frame):
        print_info("\nВыход...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while True:
        show_menu()

        choice = input(f"{YELLOW}Выберите действие: {RESET}").strip()

        if choice == "1":
            menu_update_and_run_with_dashboard()
        elif choice == "2":
            menu_run_with_dashboard_no_update()
        elif choice == "3":
            menu_open_dashboard_only()
        elif choice == "4":
            menu_update_and_run_without_dashboard()
        elif choice == "5":
            menu_run_without_dashboard_no_update()
        elif choice == "6":
            menu_update_only()
        elif choice == "7":
            menu_change_profile_url()
        elif choice == "8":
            menu_rollback()
        elif choice == "9":
            menu_stop_vpn()
        elif choice == "0":
            print_info("Выход...")
            # Ядро продолжает работать независимо
            sys.exit(0)
        else:
            print_error("Неверный выбор")
            time.sleep(1)


if __name__ == "__main__":
    main()
