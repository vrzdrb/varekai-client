import os
import sys
import json
import platform
import shutil
import subprocess
from pathlib import Path

# === КОНСТАНТЫ ===
URL_FILE = Path("URL.txt")
CORE_BINARY = "prizrak-core.exe" if platform.system().lower() == "windows" else "prizrak-core"
CORE_LOG = Path("VPN.log")
ARCHIVES_DIR = Path("archives")
CONFIG_CLEAN = Path("config.yaml")
CONFIG_SMART = Path("smart-config.yaml")
MIRRORS_FILE = Path("mirrors.txt")
SETTINGS_FILE = Path("settings.json")

CORE_REPO = "legiz-ru/Prizrak-Core"
MAX_ARCHIVES = 3
FORCE_ADMIN_AT_START = True

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
        "status_stopped": "VPN: ОСТАНОВЛЕН",
        "btn_toggle_on": "▶ ЗАПУСТИТЬ VPN",
        "btn_toggle_off": "■ ОСТАНОВИТЬ VPN",
        "btn_update_run": "🔄 Обновить и запустить",
        "btn_logs": "📜 Логи",
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
        "reset_auto_ok": "Автовыбор восстановлен",
        "reset_auto_fail": "Не удалось восстановить автовыбор",
        "no_connection": "VPN выключен",
        "log_app": "Лог приложения",
        "log_core": "Лог ядра",
        "conn_title": "Активные подключения",
        "conn_close": "✕ Закрыть",
        "conn_close_all": "Прервать все",
        "conn_empty": "Нет активных подключений",
        "conn_del_fail": "Не удалось закрыть соединение",
        "key_quit": "Выход",
        "key_toggle": "Вкл / Выкл VPN",
        "key_refresh": "Обновить",
        "key_connections": "Подключения",
        "key_close_conn": "Закрыть",
        "key_lang": "Язык",
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
    },
    "en": {
        "not_installed": "not installed",
        "status_running": "VPN: RUNNING",
        "status_stopped": "VPN: STOPPED",
        "btn_toggle_on": "▶ START VPN",
        "btn_toggle_off": "■ STOP VPN",
        "btn_update_run": "🔄 Update & Start",
        "btn_logs": "📜 Logs",
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
        "reset_auto_ok": "Auto-select restored",
        "reset_auto_fail": "Failed to restore auto-select",
        "no_connection": "VPN OFF",
        "log_app": "App log",
        "log_core": "Core log",
        "conn_title": "Active connections",
        "conn_close": "✕ Close",
        "conn_close_all": "Close all",
        "conn_empty": "No active connections",
        "conn_del_fail": "Failed to close connection",
        "key_quit": "Quit",
        "key_toggle": "On / Off VPN",
        "key_refresh": "Refresh",
        "key_connections": "Connections",
        "key_close_conn": "Close",
        "key_lang": "Lang",
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
    }
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
    if machine in ("x86", "i386", "i686"):
        return "386"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    return "amd64"


def check_avx2_support():
    arch = get_arch()
    if arch != "amd64":
        return False
    try:
        if get_os() == "linux":
            with open("/proc/cpuinfo", "r") as f:
                return "avx2" in f.read().lower()
        elif get_os() == "windows":
            result = subprocess.run(
                ["wmic", "cpu", "get", "name"],
                capture_output=True, text=True, timeout=5
            )
            cpu_name = result.stdout.lower()
            return not any(old in cpu_name for old in ["pentium", "celeron", "atom"])
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
            args_str = " ".join(sys.argv)
            subprocess.Popen(["osascript", "-e", f'do shell script "{sys.executable} {args_str}" with administrator privileges'])
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
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass
