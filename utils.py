import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def get_script_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_os():
    os_name = platform.system().lower()
    if os_name == "windows":
        return "windows"
    if os_name == "darwin":
        return "darwin"
    return "linux"


def get_arch():
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise RuntimeError(f"Unsupported architecture: {machine or 'unknown'}")


APP_DIR = get_script_dir()

# === КОНСТАНТЫ ===
URL_FILE = APP_DIR / "URL.txt"
CORE_BINARY = "prizrak-core.exe" if get_os() == "windows" else "prizrak-core"
CORE_LOG = APP_DIR / "VPN.log"
CORE_VERSION_FILE = APP_DIR / "core-version.txt"
ARCHIVES_DIR = APP_DIR / "archives"
CONFIG_CLEAN = APP_DIR / "config.yaml"
CONFIG_SMART = APP_DIR / "smart-config.yaml"
MIRRORS_FILE = APP_DIR / "mirrors.txt"
SETTINGS_FILE = APP_DIR / "settings.json"

CORE_REPO = "legiz-ru/Prizrak-Core"
MAX_ARCHIVES = 3
FORCE_ADMIN_AT_START = True


def _read_app_version():
    """Версия приложения из pyproject.toml — при разработке читаем файл
    рядом с исходниками, в PyInstaller-сборке — из временного каталога
    бандла (pyproject.toml кладётся туда через --add-data)."""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "pyproject.toml")
    candidates.append(get_script_dir() / "pyproject.toml")
    for path in candidates:
        try:
            if path.exists():
                match = re.search(
                    r'^version\s*=\s*"([^"]+)"',
                    path.read_text(encoding="utf-8"),
                    re.M,
                )
                if match:
                    return match.group(1)
        except Exception:
            continue
    return "0.0.0"


try:
    # Файл генерируется CI перед PyInstaller: 'BUILD_VERSION = "0.9.7"'
    from _build_version import BUILD_VERSION as _BUILD_VERSION
except Exception:
    _BUILD_VERSION = None

APP_VERSION = _BUILD_VERSION or _read_app_version()

DEFAULT_MIRRORS = [
    "https://ghproxy.net/",
    "https://ghfast.top/",
    "https://gh-proxy.org/",
]

DEFAULT_SETTINGS = {"language": "ru"}

# === ЛОКАЛИЗАЦИЯ ===
STRINGS = {
    "ru": {
        "not_installed": "не установлено",
        "status_running": "VPN: ЗАПУЩЕН",
        "quit_dialog_msg": "Оставить ли VPN работающим в фоне?",
        "quit_dialog_yes": "Да",
        "quit_dialog_no": "Нет",
        "status_stopped": "VPN: ОСТАНОВЛЕН",
        "btn_toggle_on": "Запустить VPN",
        "btn_toggle_off": "Остановить VPN",
        "btn_update_run": "Обновить и запустить",
        "btn_logs": "Логи",
        "brief_starting": "Запуск VPN...",
        "brief_stopping": "Остановка VPN...",
        "brief_checking": "Проверка обновлений ядра...",
        "brief_updating_profile": "Обновление профиля...",
        "brief_refreshed": "Статус обновлён",
        "brief_lang_changed": "Язык изменён на: {lang}",
        "tab_groups": "Группы:",
        "tab_nodes": "Ноды:",
        "col_group": "Группа",
        "col_type": "Тип",
        "col_current": "Текущая",
        "col_node": "Сервер",
        "col_latency": "Задержка",
        "col_status": "Статус",
        "col_domain": "Адрес / домен",
        "col_sport": "Исх. порт",
        "col_dport": "Порт хоста",
        "col_server": "Сервер",
        "col_rule": "Правило",
        "col_dspeed": "↓ Скорость",
        "col_dtotal": "↓ Загружено",
        "col_uspeed": "↑ Скорость",
        "col_utotal": "↑ Выгружено",
        "col_terminate": "Прервать",
        "label_group": "Группа:",
        "select_prompt": "Выберите группу",
        "current_country": "Текущая страна: {country}",
        "country_unknown": "не определена",
        "switch_ok": "{group}: выбрана нода {node}",
        "switch_fail": "Не удалось переключить группу {group}",
        "reset_auto": "⟳ Вернуть автовыбор",
        "status_alive": "доступен",
        "status_dead": "недоступен",
        "reset_auto_ok": "Автовыбор восстановлен",
        "reset_auto_fail": "Не удалось восстановить автовыбор",
        "no_connection": "VPN выключен",
        "log_app": "Лог приложения",
        "log_core": "Лог ядра",
        "conn_title": "Активные подключения",
        "conn_close": "[X] Закрыть",
        "conn_close_all": "[X] Прервать все",
        "conn_empty": "Нет активных подключений",
        "conn_del_fail": "Не удалось закрыть соединение",
        "key_quit": "Выход",
        "key_toggle": "Вкл / Выкл VPN",
        "key_rollback": "Версии ядра",
        "key_connections": "Подключения",
        "key_close_conn": "Закрыть",
        "key_lang": "Язык",
        "key_log_scroll": "Прокрутка лога",
        "lang_current_name": "Русский",
        "admin_required": "Для работы программы требуются права администратора (TUN-режим).",
        "admin_restart": "Перезапуск с правами администратора...",
        "admin_failed": "Не удалось получить права администратора.",
        "press_enter_exit": "Нажмите Enter для выхода...",
        "exiting": "Выход...",
        "elev_no_mech": "Не найден механизм для запуска с правами администратора",
        "elev_error": "Ошибка при запросе прав администратора: {error}",
        "prof_not_found": "Файл конфигурации не найден.",
        "prof_paste": "Вставьте ссылку на профиль с настройками.",
        "prof_paste_hint": "Для вставки используйте правую кнопку мыши или Ctrl+Shift+V",
        "prof_prompt": "Ссылка на профиль: ",
        "prof_saved": "Ссылка сохранена в URL.txt",
        "val_empty": "Ссылка не задана",
        "val_bad": "Некорректная ссылка",
        "val_scheme": "Ссылка должна начинаться с http:// или https://",
        "gh_all_fail": "Все источники скачивания недоступны",
        "gh_tag_fail": "Не удалось определить версию последнего релиза",
        "core_not_found": "Ядро не найдено. Нажмите 'Обновить и запустить'",
        "brief_updating_rules": "Обновление провайдеров правил...",
        "rule_providers_ok": "Провайдеры правил обновлены",
        "rule_providers_fail": "Ошибка обновления провайдеров правил",
        "vpn_start_ok": "VPN успешно запущен",
        "vpn_start_fail": "Не удалось запустить VPN",
        "vpn_stop_ok": "VPN успешно остановлен",
        "vpn_stop_fail": "Не удалось остановить VPN",
        "core_already_latest": "Ядро уже актуально",
        "core_updated": "Ядро обновлено до версии {version}",
        "core_update_fail": "Ошибка обновления ядра",
        "profile_updated": "Профиль обновлён",
        "profile_update_fail": "Ошибка обновления профиля",
        "rule_provider_ok": "Провайдер правил '{name}' обновлён",
        "rule_provider_fail": "Ошибка обновления провайдера '{name}'",
        "core_running_update": "Обновление невозможно: сначала остановите VPN",
        "core_update_in_progress": "Обновление уже выполняется, подождите...",
        "core_running_rollback": "Откат невозможен: сначала остановите VPN",
        "rollback_title": "Версии ядра",
        "rollback_empty": "Нет архивов для отката",
        "rollback_current": "текущая",
        "rollback_cancel": "[X] Отмена",
        "core_rollback_ok": "Ядро откачено на версию {version}",
        "core_rollback_fail": "Не удалось откатить ядро",
        "arch_broken": "Архив ядра повреждён или пуст",
        "no_asset": "Не найден подходящий ассет релиза для этой платформы",
    },
    "en": {
        "not_installed": "not installed",
        "status_running": "VPN: RUNNING",
        "quit_dialog_msg": "Leave VPN running in the background?",
        "quit_dialog_yes": "Yes",
        "quit_dialog_no": "No",
        "status_stopped": "VPN: STOPPED",
        "btn_toggle_on": "Start VPN",
        "btn_toggle_off": "Stop VPN",
        "btn_update_run": "Update & Start",
        "btn_logs": "Logs",
        "brief_starting": "Starting VPN...",
        "brief_stopping": "Stopping VPN...",
        "brief_checking": "Checking core updates...",
        "brief_updating_profile": "Updating profile...",
        "brief_refreshed": "Status refreshed",
        "brief_lang_changed": "Language changed to: {lang}",
        "tab_groups": "Groups:",
        "tab_nodes": "Nodes:",
        "col_group": "Group",
        "col_type": "Type",
        "col_current": "Current",
        "col_node": "Server",
        "col_latency": "Latency",
        "col_status": "Status",
        "col_domain": "Address / domain",
        "col_sport": "Src port",
        "col_dport": "Dst port",
        "col_server": "Server",
        "col_rule": "Rule",
        "col_dspeed": "↓ Speed",
        "col_dtotal": "↓ Downloaded",
        "col_uspeed": "↑ Speed",
        "col_utotal": "↑ Uploaded",
        "col_terminate": "Close",
        "label_group": "Group:",
        "select_prompt": "Select group",
        "current_country": "Current country: {country}",
        "country_unknown": "unknown",
        "switch_ok": "{group}: node {node} selected",
        "switch_fail": "Failed to switch group {group}",
        "reset_auto": "⟳ Restore auto-select",
        "status_alive": "alive",
        "status_dead": "dead",
        "reset_auto_ok": "Auto-select restored",
        "reset_auto_fail": "Failed to restore auto-select",
        "no_connection": "VPN OFF",
        "log_app": "App log",
        "log_core": "Core log",
        "conn_title": "Active connections",
        "conn_close": "[X] Close",
        "conn_close_all": "[X] Close all",
        "conn_empty": "No active connections",
        "conn_del_fail": "Failed to close connection",
        "key_quit": "Quit",
        "key_toggle": "On / Off VPN",
        "key_rollback": "Core versions",
        "key_connections": "Connections",
        "key_close_conn": "Close",
        "key_lang": "Lang",
        "key_log_scroll": "Log scroll",
        "lang_current_name": "English",
        "admin_required": "Administrator rights are required (TUN mode).",
        "admin_restart": "Restarting with admin rights...",
        "admin_failed": "Could not obtain admin rights.",
        "press_enter_exit": "Press Enter to exit...",
        "exiting": "Exiting...",
        "elev_no_mech": "No mechanism to elevate privileges",
        "elev_error": "Elevation error: {error}",
        "prof_not_found": "Config file not found.",
        "prof_paste": "Paste your subscription profile URL.",
        "prof_paste_hint": "To paste: right mouse button or Ctrl+Shift+V",
        "prof_prompt": "Profile URL: ",
        "prof_saved": "URL saved to URL.txt",
        "val_empty": "No URL provided",
        "val_bad": "Invalid URL",
        "val_scheme": "URL must start with http:// or https://",
        "gh_all_fail": "All download sources unavailable",
        "gh_tag_fail": "Could not determine the latest release version",
        "core_not_found": "Core not found. Press 'Update & Start'",
        "brief_updating_rules": "Updating rule providers...",
        "rule_providers_ok": "Rule providers updated",
        "rule_providers_fail": "Failed to update rule providers",
        "vpn_start_ok": "VPN started successfully",
        "vpn_start_fail": "Failed to start VPN",
        "vpn_stop_ok": "VPN stopped successfully",
        "vpn_stop_fail": "Failed to stop VPN",
        "core_already_latest": "Core is already up to date",
        "core_updated": "Core updated to version {version}",
        "core_update_fail": "Failed to update core",
        "profile_updated": "Profile updated",
        "profile_update_fail": "Failed to update profile",
        "rule_provider_ok": "Rule provider '{name}' updated",
        "rule_provider_fail": "Failed to update rule provider '{name}'",
        "core_running_update": "Update is not possible: stop the VPN first",
        "core_update_in_progress": "Update already in progress, please wait...",
        "core_running_rollback": "Rollback is not possible: stop the VPN first",
        "rollback_title": "Core versions",
        "rollback_empty": "No archives to roll back",
        "rollback_current": "current",
        "rollback_cancel": "[X] Cancel",
        "core_rollback_ok": "Core rolled back to version {version}",
        "core_rollback_fail": "Failed to roll back core",
        "arch_broken": "Core archive is broken or empty",
        "no_asset": "No suitable release asset found for this platform",
    },
}

_language = None


def get_language():
    global _language
    if _language is None:
        _language = "ru"
        try:
            if SETTINGS_FILE.exists():
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    _language = json.load(f).get("language", "ru")
        except Exception:
            _language = "ru"
    return _language


def set_language(lang):
    global _language
    _language = lang


def t(key, **kwargs):
    lang = get_language()
    table = STRINGS.get(lang, STRINGS["ru"])
    template = table.get(key) or STRINGS["ru"].get(key, key)
    try:
        return template.format(**kwargs)
    except Exception:
        return template


def _windows_cpuid():
    """Возвращает callable cpuid(leaf, subleaf) -> (eax, ebx, ecx, edx)
    через исполняемую страницу памяти (ctypes, без внешних утилит).
    Windows x64 ABI: аргументы в RCX, RDX, R8."""
    import ctypes

    # push rbx; mov eax,ecx; mov ecx,edx; cpuid;
    # mov [r8],eax; mov [r8+4],ebx; mov [r8+8],ecx; mov [r8+12],edx;
    # pop rbx; ret
    code = (
        b"\x53\x89\xc8\x89\xd1\x0f\xa2"
        b"\x41\x89\x00\x41\x89\x58\x04"
        b"\x41\x89\x48\x08\x41\x89\x50\x0c"
        b"\x5b\xc3"
    )
    kernel32 = ctypes.windll.kernel32
    # КРИТИЧНО: без restype=c_void_p ctypes обрезает адрес до 32 бит,
    # memmove падает с access violation и AVX2 молча считается отсутствующим.
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]
    kernel32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
    kernel32.VirtualFree.restype = ctypes.c_int
    MEM_COMMIT, PAGE_RWX = 0x1000, 0x40
    addr = kernel32.VirtualAlloc(None, len(code), MEM_COMMIT, PAGE_RWX)
    if not addr:
        raise RuntimeError("VirtualAlloc failed")
    try:
        ctypes.memmove(addr, code, len(code))
        fn_type = ctypes.CFUNCTYPE(
            None, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)
        )
        fn = fn_type(addr)

        def cpuid(leaf, subleaf=0):
            regs = (ctypes.c_uint32 * 4)()
            fn(leaf, subleaf, regs)
            return regs[0], regs[1], regs[2], regs[3]

        return cpuid
    except Exception:
        kernel32.VirtualFree(addr, 0, 0x8000)
        raise


def _windows_has_avx2():
    """Прямая аппаратная проверка AVX2: CPUID + XGETBV.
    Не зависит от wmic/PowerShell и маркетингового имени CPU."""
    cpuid = _windows_cpuid()
    # Leaf 1: ECX bit 27 = OSXSAVE (ОС сохраняет расширенные регистры),
    #         ECX bit 28 = AVX (процессор умеет AVX)
    _, _, ecx, _ = cpuid(1)
    if not (ecx & (1 << 27)) or not (ecx & (1 << 28)):
        return False
    # XCR0: биты 1 и 2 — ОС сохраняет состояние XMM и YMM
    # xgetbv: читает XCR0, номер в RCX; результат в EDX:EAX
    import ctypes

    code = b"\x0f\x01\xd0\xc3"  # xgetbv; ret
    kernel32 = ctypes.windll.kernel32
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong, ctypes.c_ulong]
    kernel32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_ulong]
    kernel32.VirtualFree.restype = ctypes.c_int
    addr = kernel32.VirtualAlloc(None, len(code), 0x1000, 0x40)
    if not addr:
        return False
    try:
        ctypes.memmove(addr, code, len(code))
        fn_type = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_uint32)
        xcr0 = fn_type(addr)(0)
    finally:
        kernel32.VirtualFree(addr, 0, 0x8000)
    if (xcr0 & 0x6) != 0x6:
        return False
    # Leaf 7 subleaf 0: EBX bit 5 = AVX2
    _, ebx7, _, _ = cpuid(7, 0)
    return bool(ebx7 & (1 << 5))


def _windows_has_avx2_name_fallback():
    """Запасной вариант: по имени CPU через PowerShell CIM
    (wmic в Windows 11 отсутствует). Старые бренды без AVX2."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
            capture_output=True, text=True, timeout=10,
        )
        name = (result.stdout or "").lower()
        return not any(old in name for old in ("pentium", "celeron", "atom"))
    except Exception:
        return False


def check_avx2_support():
    arch = get_arch()
    if arch != "amd64":
        return False
    try:
        if get_os() == "linux":
            with open("/proc/cpuinfo", "r") as f:
                return "avx2" in f.read().lower()
        elif get_os() == "windows":
            try:
                return _windows_has_avx2()
            except Exception:
                # CPUID недоступен (политики безопасности и т.п.) — пробуем по имени CPU
                return _windows_has_avx2_name_fallback()
        elif get_os() == "darwin":
            return True
    except Exception:
        pass
    return False


def is_admin():
    try:
        if platform.system().lower() == "windows":
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.getuid() == 0
    except Exception:
        return False


def restart_as_admin():
    if is_admin():
        return True
    try:
        if platform.system().lower() == "windows":
            import ctypes
            params = subprocess.list2cmdline(sys.argv[1:]) if len(sys.argv) > 1 else None
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
            sys.exit(0)
        elif platform.system().lower() == "darwin":
            shell_cmd = " ".join(
                [shlex.quote(sys.executable)] + [shlex.quote(a) for a in sys.argv]
            )
            applescript_cmd = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen([
                "osascript", "-e",
                f'do shell script "{applescript_cmd}" with administrator privileges'
            ])
            sys.exit(0)
        else:
            if shutil.which("sudo"):
                os.execvp("sudo", ["sudo", "-E"] + sys.argv)
            elif shutil.which("pkexec"):
                os.execvp("pkexec", ["pkexec"] + sys.argv)
            else:
                return False
    except Exception:
        return False
    return True


def ensure_dirs():
    ARCHIVES_DIR.mkdir(exist_ok=True)


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings.update(json.load(f))
    except Exception:
        pass
    return settings


def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def setup_console():
    if platform.system().lower() != "windows":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)

        # Прячем мигающий текстовый курсор (иначе в углу TUI моргает "_")
        class _CURSORINFO(ctypes.Structure):
            _fields_ = [("dwSize", ctypes.c_ulong), ("bVisible", ctypes.c_bool)]

        info = _CURSORINFO()
        if kernel32.GetConsoleCursorInfo(handle, ctypes.byref(info)):
            info.bVisible = False
            kernel32.SetConsoleCursorInfo(handle, ctypes.byref(info))
    except Exception:
        pass


# Диапазоны эмодзи/сервисных символов, вычищаемых на Windows
# (классическая консоль их не рендерит — рисуются пустые квадраты).
# Стрелки (2190-21FF) и геометрические фигуры (25A0-25FF) НЕ трогаем:
# используются в разметке интерфейса (→, ■) и рисуются везде.
_EMOJI_STRIP_RANGES = (
    (0x1F000, 0x1FAFF),  # пиктограммы, флаги-индикаторы, 🅰️ и пр.
    (0x2300, 0x23FF),    # misc technical: ⌚ ⌛ ⏰ ...
    (0x2600, 0x26FF),    # misc symbols: ✅ ⚡ ⭐ ...
    (0x2700, 0x27BF),    # dingbats: ✂ ✉ ...
    (0x2B00, 0x2BFF),    # ⭐ ⬆ и пр.
    (0xFE00, 0xFE0F),    # variation selectors
    (0x200D, 0x200D),    # ZWJ
    (0x20E3, 0x20E3),    # keycap
)


def replace_flag_emojis(text: str) -> str:
    """На Windows: флаги (пары региональных индикаторов) заменяет на
    текстовые коды стран вроде [CZ], остальные эмодзи вычищает —
    классическая консоль Windows их не рендерит.
    Устойчив к вариантному селектору FE0F между/после индикаторами."""
    if get_os() != "windows":
        return text
    out = []
    i = 0
    n = len(text)
    VS = 0xFE0F

    def _skip_vs(pos):
        while pos < n and ord(text[pos]) == VS:
            pos += 1
        return pos

    while i < n:
        cp = ord(text[i])
        if 0x1F1E6 <= cp <= 0x1F1FF:
            j = _skip_vs(i + 1)
            if j < n:
                cp2 = ord(text[j])
                if 0x1F1E6 <= cp2 <= 0x1F1FF:
                    code = chr(cp - 0x1F1E6 + 65) + chr(cp2 - 0x1F1E6 + 65)
                    out.append(f"[{code}]")
                    i = _skip_vs(j + 1)
                    # Имя ноды часто дублирует флаг текстовым кодом:
                    # "🇷🇺 RU >> 🇨🇭 CH" -> "[RU] >> [CH]", а не "[RU] RU >> [CH] CH".
                    # Код может не совпадать с флагом из-за опечаток в конфиге
                    # ("🇩🇪 GE" — флаг Германии, код Грузии): отбрасываем
                    # первое отдельное слово из двух латинских букв
                    # (обе заглавные или обе строчные), побеждает флаг.
                    # "My"/"CZNET"/кириллица не трогаются.
                    if (
                        i + 3 <= n
                        and text[i] == " "
                        and (i + 3 == n or not text[i + 3].isalpha())
                    ):
                        word = text[i + 1 : i + 3]
                        if (
                            word.isascii()
                            and word.isalpha()
                            and (word.isupper() or word.islower())
                        ):
                            i += 3
                    continue
        out.append(text[i])
        i += 1

    result = "".join(out)
    return "".join(
        ch for ch in result
        if not any(lo <= ord(ch) <= hi for lo, hi in _EMOJI_STRIP_RANGES)
    )


def format_group_name(name: str, is_smart: bool = False, force_icon: str = "") -> str:
    """Windows: имя группы для селектора. Начальное эмодзи заменяется на
    ☻ для авто/smart-групп и на ● для остальных; флаги → [XX].
    Если эмодзи в имени нет — имя возвращается без изменений.
    force_icon: иконка принудительно, даже без эмодзи (таблица нод)."""
    if get_os() != "windows":
        return name
    stripped = replace_flag_emojis(name)
    low = stripped.lstrip().lower()
    auto = is_smart or low.startswith("авто") or low.startswith("auto")
    icon = force_icon or ("☻" if auto else "●")
    if stripped != name:
        return f"{icon} {stripped.lstrip()}"
    if force_icon:
        return f"{icon} {name}"
    return name

