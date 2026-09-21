import time
from utils import (print_purple, print_info, print_success, print_error,
                   clear_screen, print_menu_item)
from constants import ASCII_HEADER, YELLOW, RESET
from core import (get_current_core_info, get_core_pid, update_core, update_zashboard,
                  update_profile, start_core, stop_core, get_available_archives,
                  rollback_to_version, load_profile_url, validate_url)
from config import generate_smart_config
from settings import load_settings, save_settings
from i18n import t, set_language


def show_menu():
    """Показывает главное меню"""
    clear_screen()
    print_purple(ASCII_HEADER)
    print_info(t("current_core", info=get_current_core_info()))
    pid = get_core_pid()
    if pid:
        print_success(t("core_running", pid=pid))
    else:
        print_error(t("core_stopped"))

    print_purple("\n" + "=" * 70)
    print_menu_item("1", t("menu_1"))
    print_menu_item("2", t("menu_2"))
    print_menu_item("3", t("menu_3"))
    print_menu_item("4", t("menu_4"))
    print_menu_item("5", t("menu_5"))
    print_menu_item("6", t("menu_6"))
    print_menu_item("0", t("menu_0"))
    print_purple("=" * 70)


def show_additional_menu():
    """Показывает подменю 'Дополнительные настройки'"""
    clear_screen()
    print_purple(ASCII_HEADER)
    settings = load_settings()
    state = t("smart_on") if settings.get("smart_enabled", True) else t("smart_off")
    print_info(t("add_smart_line", state=state))

    pid = get_core_pid()
    if pid:
        print_success(t("core_running", pid=pid))
    else:
        print_error(t("core_stopped"))

    print_purple("\n" + "=" * 70)
    print_menu_item("1", t("add_1"))
    print_menu_item("2", t("add_2"))
    print_menu_item("3", t("add_3"))
    print_menu_item("4", t("add_4"))
    print_menu_item("5", t("add_5"))
    print_menu_item("6", t("add_6", state=state))
    print_menu_item("7", t("add_7"))
    print_menu_item("0", t("add_0"))
    print_purple("=" * 70)


def menu_update_and_run_with_dashboard():
    """Пункт 1: Обновление и запуск VPN с панелью управления"""
    from dashboard import open_dashboard
    from constants import CONFIG_CLEAN
    core_updated = update_core()
    update_zashboard()
    if core_updated:
        if not CONFIG_CLEAN.exists():
            update_profile()
        if start_core():
            time.sleep(3)
            update_profile()
            open_dashboard()


def menu_run_with_dashboard_no_update():
    """Пункт 2: [Без обновления] Запуск VPN с панелью управления"""
    from dashboard import open_dashboard
    if start_core():
        time.sleep(2)
        open_dashboard()


def menu_open_dashboard_only():
    """Пункт 3: [Без обновления и запуска VPN] Только открыть панель"""
    from dashboard import open_dashboard
    open_dashboard()


def menu_additional():
    """Пункт 4: подменю 'Дополнительные настройки'"""
    while True:
        show_additional_menu()
        choice = input(f"{YELLOW}{t('choose_action')}{RESET}").strip()

        if choice == "1":
            menu_update_and_run_without_dashboard()
        elif choice == "2":
            menu_run_without_dashboard_no_update()
        elif choice == "3":
            menu_update_only()
        elif choice == "4":
            menu_change_profile_url()
        elif choice == "5":
            menu_rollback()
        elif choice == "6":
            menu_toggle_smart()
        elif choice == "7":
            menu_regenerate_smart()
        elif choice == "0":
            return
        else:
            print_error(t("invalid_choice"))
            time.sleep(1)


def menu_update_and_run_without_dashboard():
    """Доп. 1: [Без панели] Обновление и запуск VPN"""
    from constants import CONFIG_CLEAN
    core_updated = update_core()
    if core_updated:
        if not CONFIG_CLEAN.exists():
            update_profile()
        if start_core():
            time.sleep(3)
            update_profile()


def menu_run_without_dashboard_no_update():
    """Доп. 2: [Без обновления и панели] Только запуск VPN"""
    start_core()


def menu_update_only():
    """Доп. 3: [Без панели и запуска VPN] Только обновление"""
    update_core()
    update_zashboard()
    update_profile()


def menu_change_profile_url():
    """Доп. 4: Изменить ссылку на профиль"""
    from constants import URL_FILE
    current_url = load_profile_url()
    print_info(t("prof_current", url=current_url or t("prof_not_set")))
    new_url = input(f"{YELLOW}{t('prof_new_prompt')}{RESET}").strip()
    if new_url:
        valid, error = validate_url(new_url)
        if valid:
            URL_FILE.write_text(new_url, encoding="utf-8")
            print_success(t("prof_url_updated"))
        else:
            print_error(error)


def menu_rollback():
    """Доп. 5: Откат на предыдущую версию"""
    archives = get_available_archives()
    if not archives:
        print_error(t("rb_none"))
        return

    print_info(t("rb_available"))
    for i, archive in enumerate(archives, 1):
        print_purple(f"  {i}. {archive.name}")
    print_purple(t("rb_cancel"))

    choice = input(f"{YELLOW}{t('rb_choose')}{RESET}").strip()
    if choice == "0":
        return

    try:
        index = int(choice) - 1
        if 0 <= index < len(archives):
            rollback_to_version(archives[index])
        else:
            print_error(t("invalid_choice"))
    except ValueError:
        print_error(t("invalid_choice"))


def menu_toggle_smart():
    """Доп. 6: Переключатель смарт-стратегий"""
    settings = load_settings()
    settings["smart_enabled"] = not settings.get("smart_enabled", True)
    save_settings(settings)

    if settings["smart_enabled"]:
        print_success(t("smart_enabled_msg"))
    else:
        print_success(t("smart_disabled_msg"))

    if generate_smart_config() and get_core_pid():
        print_info(t("restart_hint"))


def menu_regenerate_smart():
    """Доп. 7: Ручная перегенерация smart-config.yaml"""
    if generate_smart_config() and get_core_pid():
        print_info(t("restart_hint"))


def menu_toggle_language():
    """Пункт 6 главного меню: переключение языка ru/en одним нажатием"""
    settings = load_settings()
    new_lang = "en" if settings.get("language", "ru") == "ru" else "ru"
    settings["language"] = new_lang
    save_settings(settings)
    set_language(new_lang)
    print_success(t("language_set"))


def menu_stop_vpn():
    """Пункт 5: Остановить VPN"""
    stop_core()
