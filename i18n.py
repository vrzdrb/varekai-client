"""Локализация: строки интерфейса ru/en и функция t()."""
import json
from constants import SETTINGS_FILE

_language = None

STRINGS = {
    "ru": {
        # Главное меню
        "not_installed": "не установлено",
        "current_core": "Текущее ядро: {info}",
        "core_running": "Статус ядра: запущено (PID: {pid})",
        "core_stopped": "Статус ядра: не запущено",
        "menu_1": "Обновление и запуск VPN с панелью управления",
        "menu_2": "[Без обновления] Запуск VPN с панелью управления",
        "menu_3": "[Без обновления и запуска VPN] Только открыть панель управления",
        "menu_4": "Дополнительные настройки",
        "menu_5": "Остановить VPN",
        "menu_6": "Язык / Language: русский",
        "menu_0": "Выход",
        # Подменю
        "add_smart_line": "Смарт-стратегии: {state}",
        "add_1": "[Без панели] Обновление и запуск VPN",
        "add_2": "[Без обновления и панели] Только запуск VPN",
        "add_3": "[Без панели и запуска VPN] Только обновление",
        "add_4": "Изменить ссылку на профиль с настройками",
        "add_5": "Откат на предыдущую версию",
        "add_6": "Смарт-стратегии: {state} (переключить)",
        "add_7": "Перегенерировать smart-config.yaml сейчас",
        "add_0": "Назад",
        "smart_on": "вкл",
        "smart_off": "выкл",
        "smart_enabled_msg": "Смарт-стратегии включены",
        "smart_disabled_msg": "Смарт-стратегии выключены",
        "restart_hint": "Применится после перезапуска VPN (п.5 → п.2)",
        "language_set": "Язык интерфейса: русский",
        # Общие prompts
        "choose_action": "Выберите действие: ",
        "invalid_choice": "Неверный выбор",
        # Профиль подписки
        "prof_not_found": "Файл конфигурации не найден.",
        "prof_paste": "Вставьте ссылку на профиль с настройками.",
        "prof_paste_hint": "Для вставки используйте: Ctrl+Shift+V или Shift+Insert",
        "prof_prompt": "Ссылка на профиль: ",
        "prof_saved": "Ссылка сохранена в URL.txt",
        "prof_current": "Текущая ссылка: {url}",
        "prof_not_set": "не задана",
        "prof_new_prompt": "Введите новую ссылку (или пусто для отмены): ",
        "prof_url_updated": "Ссылка обновлена",
        "prof_url_missing": "Ссылка на профиль не задана",
        "val_empty": "Ссылка не задана",
        "val_bad": "Некорректная ссылка",
        "val_scheme": "Ссылка должна начинаться с http:// или https://",
        "prof_downloading": "Скачивание профиля...",
        "prof_auth": "Удалённый ресурс требует авторизации",
        "prof_unavailable": "Удалённый ресурс недоступен",
        "prof_ok": "Профиль успешно обновлён",
        "prof_noconn": "Нет связи с удалённым ресурсом",
        "prof_error": "Ошибка при скачивании профиля: {error}",
        # Ядро: обновление
        "core_checking": "Проверка обновлений ядра...",
        "core_release_fail": "Не удалось получить информацию о релизе: {error}",
        "core_local": "Используем локальную версию ядра",
        "core_uptodate": "Ядро актуально (версия {tag}), скачивание не требуется",
        "core_restore": "Бинарник не найден, разворачиваем из существующего архива...",
        "core_build_name": "Список ассетов недоступен, собираем имя: {name}",
        "downloading": "Скачивание {name}...",
        "core_download_fail": "Не удалось скачать ядро: {error}",
        "extract_fail": "Ошибка распаковки: {error}",
        "core_updated": "Ядро обновлено до версии {tag}",
        "binary_not_in_archive": "Бинарник не найден в архиве",
        # zashboard
        "zb_checking": "Проверка обновлений zashboard...",
        "zb_local": "Используем локальную версию zashboard",
        "zb_uptodate": "zashboard актуален (версия {version})",
        "zb_no_archive": "Не найден архив с панелью управления",
        "zb_download_fail": "Не удалось скачать zashboard: {error}",
        "zb_extract_fail": "Ошибка распаковки панели: {error}",
        "zb_updated": "zashboard обновлён до версии {version}",
        # Запуск ядра
        "start_already": "Ядро уже запущено (PID: {pid})",
        "start_no_binary": "Бинарник ядра не найден. Сначала выполните обновление.",
        "start_gen_smart": "smart-config.yaml не найден, генерируем...",
        "start_no_config": "Файл конфигурации не найден. Сначала обновите профиль.",
        "start_pkexec": "Запрос прав администратора через pkexec...",
        "start_sudo_noprompt": "sudo не может запросить пароль в этом контексте.",
        "start_options": "Варианты решения:",
        "start_opt1": "  1. Установите pkexec: sudo pacman -S polkit",
        "start_opt2": "  2. Запустите скрипт через sudo: sudo python ./main.py",
        "start_no_root_mech": "Не найден механизм для запуска от root",
        "start_install_polkit": "Установите polkit: sudo pacman -S polkit",
        "start_win_admin": "Для запуска ядра на Windows требуется запуск скрипта от администратора",
        "start_win_hint": "Запустите скрипт через правый клик -> Запуск от имени администратора",
        "start_mac_admin": "Для запуска ядра на macOS требуется запуск скрипта от администратора",
        "start_mac_hint": "Запустите скрипт через sudo: sudo python ./main.py",
        "start_failed_log": "Ядро не запустилось. Последние строки лога:",
        "started": "Ядро запущено (PID: {pid})",
        "start_no_perm": "Нет прав на исполнение бинарника ядра.",
        "start_chmod": "Попробуйте выполнить: chmod +x {binary}",
        "start_error": "Не удалось запустить ядро: {error}",
        # Остановка ядра
        "stop_not_running": "Ядро не было запущено",
        "stop_pkexec": "Запрос прав администратора для остановки ядра...",
        "stop_no_mech": "Не найден механизм для остановки ядра от root (pkexec/sudo)",
        "stopped": "Ядро остановлено",
        "stop_failed": "Не удалось остановить ядро",
        # Откат
        "rb_extract_fail": "Ошибка распаковки архива: {error}",
        "rb_done": "Откат выполнен: {name}",
        "rb_error": "Ошибка при откате: {error}",
        "rb_none": "Нет доступных архивов для отката",
        "rb_available": "Доступные версии для отката:",
        "rb_cancel": "  0. Отмена",
        "rb_choose": "Выберите версию: ",
        # GitHub / зеркала
        "gh_mirror": "Скачивание через зеркало: {prefix}",
        "gh_all_fail": "Все источники скачивания недоступны",
        "gh_tag_fail": "Не удалось определить версию последнего релиза",
        "gh_api_fail": "GitHub API недоступен, получаем версию через редирект...",
        # Генерация конфига
        "cfg_no_clean": "Чистый конфиг (config.yaml) не найден",
        "cfg_generated": "Сгенерирован {path}",
        "cfg_error": "Ошибка генерации smart-config: {error}",
        # Панель
        "dash_cfg_error": "Ошибка чтения конфига: {error}",
        "dash_opening": "Открытие панели управления: {url}",
        "dash_opened": "Панель открыта. Закрытие окна завершит программу.",
        "dash_no_webview": "Библиотека pywebview не найдена.",
        "dash_error": "Ошибка открытия панели: {error}",
        "dash_closed": "Панель закрыта. Выход...",
        # Права администратора
        "admin_required": "Для работы программы требуются права администратора (TUN-режим).",
        "admin_restart": "Перезапуск с правами администратора...",
        "admin_failed": "Не удалось получить права администратора.",
        "press_enter_exit": "Нажмите Enter для выхода...",
        "exiting": "Выход...",
        "elev_no_mech": "Не найден механизм для запуска с правами администратора",
        "elev_error": "Ошибка при запросе прав администратора: {error}",
    },
    "en": {
        # Main menu
        "not_installed": "not installed",
        "current_core": "Current core: {info}",
        "core_running": "Core status: running (PID: {pid})",
        "core_stopped": "Core status: not running",
        "menu_1": "Update and start VPN with dashboard",
        "menu_2": "[No update] Start VPN with dashboard",
        "menu_3": "[No update/start] Open dashboard only",
        "menu_4": "Additional settings",
        "menu_5": "Stop VPN",
        "menu_6": "Язык / Language: English",
        "menu_0": "Exit",
        # Submenu
        "add_smart_line": "Smart strategies: {state}",
        "add_1": "[No dashboard] Update and start VPN",
        "add_2": "[No update/dashboard] Start VPN only",
        "add_3": "[No dashboard/start] Update only",
        "add_4": "Change subscription profile URL",
        "add_5": "Roll back to previous version",
        "add_6": "Smart strategies: {state} (toggle)",
        "add_7": "Regenerate smart-config.yaml now",
        "add_0": "Back",
        "smart_on": "on",
        "smart_off": "off",
        "smart_enabled_msg": "Smart strategies enabled",
        "smart_disabled_msg": "Smart strategies disabled",
        "restart_hint": "Will apply after VPN restart (item 5 -> item 2)",
        "language_set": "Interface language: English",
        # Common prompts
        "choose_action": "Choose an action: ",
        "invalid_choice": "Invalid choice",
        # Subscription profile
        "prof_not_found": "Config file not found.",
        "prof_paste": "Paste your subscription profile URL.",
        "prof_paste_hint": "To paste: Ctrl+Shift+V or Shift+Insert",
        "prof_prompt": "Profile URL: ",
        "prof_saved": "URL saved to URL.txt",
        "prof_current": "Current URL: {url}",
        "prof_not_set": "not set",
        "prof_new_prompt": "Enter new URL (empty to cancel): ",
        "prof_url_updated": "URL updated",
        "prof_url_missing": "Profile URL not set",
        "val_empty": "No URL provided",
        "val_bad": "Invalid URL",
        "val_scheme": "URL must start with http:// or https://",
        "prof_downloading": "Downloading profile...",
        "prof_auth": "Remote resource requires authentication",
        "prof_unavailable": "Remote resource unavailable",
        "prof_ok": "Profile updated successfully",
        "prof_noconn": "Cannot reach remote resource",
        "prof_error": "Profile download error: {error}",
        # Core update
        "core_checking": "Checking core updates...",
        "core_release_fail": "Could not fetch release info: {error}",
        "core_local": "Using local core version",
        "core_uptodate": "Core is up to date (version {tag}), no download needed",
        "core_restore": "Binary missing, restoring from existing archive...",
        "core_build_name": "Asset list unavailable, building name: {name}",
        "downloading": "Downloading {name}...",
        "core_download_fail": "Could not download core: {error}",
        "extract_fail": "Extraction error: {error}",
        "core_updated": "Core updated to version {tag}",
        "binary_not_in_archive": "Binary not found in archive",
        # zashboard
        "zb_checking": "Checking zashboard updates...",
        "zb_local": "Using local zashboard version",
        "zb_uptodate": "zashboard is up to date (version {version})",
        "zb_no_archive": "Dashboard archive not found",
        "zb_download_fail": "Could not download zashboard: {error}",
        "zb_extract_fail": "Dashboard extraction error: {error}",
        "zb_updated": "zashboard updated to version {version}",
        # Core start
        "start_already": "Core already running (PID: {pid})",
        "start_no_binary": "Core binary not found. Update first.",
        "start_gen_smart": "smart-config.yaml missing, generating...",
        "start_no_config": "Config file not found. Update your profile first.",
        "start_pkexec": "Requesting admin rights via pkexec...",
        "start_sudo_noprompt": "sudo cannot prompt for a password here.",
        "start_options": "Options:",
        "start_opt1": "  1. Install pkexec: sudo pacman -S polkit",
        "start_opt2": "  2. Run via sudo: sudo python ./main.py",
        "start_no_root_mech": "No mechanism to run as root",
        "start_install_polkit": "Install polkit: sudo pacman -S polkit",
        "start_win_admin": "On Windows the script must run as administrator",
        "start_win_hint": "Right-click the script -> Run as administrator",
        "start_mac_admin": "On macOS the script must run with sudo",
        "start_mac_hint": "Run via sudo: sudo python ./main.py",
        "start_failed_log": "Core failed to start. Last log lines:",
        "started": "Core started (PID: {pid})",
        "start_no_perm": "No permission to execute the core binary.",
        "start_chmod": "Try: chmod +x {binary}",
        "start_error": "Could not start core: {error}",
        # Core stop
        "stop_not_running": "Core was not running",
        "stop_pkexec": "Requesting admin rights to stop the core...",
        "stop_no_mech": "No mechanism to stop the root core (pkexec/sudo)",
        "stopped": "Core stopped",
        "stop_failed": "Could not stop the core",
        # Rollback
        "rb_extract_fail": "Archive extraction error: {error}",
        "rb_done": "Rolled back to: {name}",
        "rb_error": "Rollback error: {error}",
        "rb_none": "No archives available for rollback",
        "rb_available": "Available versions to roll back:",
        "rb_cancel": "  0. Cancel",
        "rb_choose": "Select version: ",
        # GitHub / mirrors
        "gh_mirror": "Downloading via mirror: {prefix}",
        "gh_all_fail": "All download sources unavailable",
        "gh_tag_fail": "Could not determine the latest release version",
        "gh_api_fail": "GitHub API unavailable, fetching version via redirect...",
        # Config generation
        "cfg_no_clean": "Clean config (config.yaml) not found",
        "cfg_generated": "Generated {path}",
        "cfg_error": "smart-config generation error: {error}",
        # Dashboard
        "dash_cfg_error": "Config read error: {error}",
        "dash_opening": "Opening dashboard: {url}",
        "dash_opened": "Dashboard opened. Closing the window exits the program.",
        "dash_no_webview": "pywebview library not found.",
        "dash_error": "Dashboard error: {error}",
        "dash_closed": "Dashboard closed. Exiting...",
        # Admin rights
        "admin_required": "Administrator rights are required (TUN mode).",
        "admin_restart": "Restarting with admin rights...",
        "admin_failed": "Could not obtain admin rights.",
        "press_enter_exit": "Press Enter to exit...",
        "exiting": "Exiting...",
        "elev_no_mech": "No mechanism to elevate privileges",
        "elev_error": "Elevation error: {error}",
    },
}


def get_language():
    """Текущий язык интерфейса (кешируется на процесс)"""
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
    """Обновляет кеш языка после переключения"""
    global _language
    _language = lang


def t(key, **kwargs):
    """Возвращает строку интерфейса на текущем языке с подстановкой {имя}"""
    lang = get_language()
    table = STRINGS.get(lang, STRINGS["ru"])
    template = table.get(key) or STRINGS["ru"].get(key, key)
    return template.format(**kwargs)
