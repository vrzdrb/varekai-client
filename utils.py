import os
import sys
import platform
import shutil
import subprocess
from pathlib import Path
from constants import (PURPLE, YELLOW, GREEN, RED, RESET,
                       _gui_env_snapshot, ARCHIVES_DIR, ZASHBOARD_DIR)
from i18n import t


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
        # чтобы избежать конфликта упакованного libreadline с системным
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

def get_script_dir():
    """Возвращает директорию, где лежит скрипт (или бинарник)"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

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
                print_error(t("elev_no_mech"))
                return False
    except Exception as e:
        print_error(t("elev_error", error=e))
        return False
    return True

def setup_gui_environment():
    """Настраивает переменные окружения для панели на Linux"""
    if get_os() != "linux":
        return
    os.environ.setdefault("QT_API", "pyside6")
    # Подавляем отладочный шум Qt
    os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false")

def ensure_dirs():
    """Создаёт необходимые директории"""
    ARCHIVES_DIR.mkdir(exist_ok=True)
    ZASHBOARD_DIR.mkdir(exist_ok=True)

def setup_console():
    """Включает ANSI-цвета в консоли Windows (conhost)"""
    if platform.system().lower() != "windows":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STDOUT
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass
