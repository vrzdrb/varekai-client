#!/usr/bin/env python3
"""
Varekai-client - кросс-платформенный лаунчер для prizrak-core
"""
import os
import sys
import time
import signal
from pathlib import Path

# При запуске из бинарника PyInstaller меняем рабочую директорию
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).resolve().parent)
else:
    os.chdir(Path(__file__).resolve().parent)

from utils import print_info, print_error, is_admin, restart_as_admin, ensure_dirs, get_os
from constants import FORCE_ADMIN_AT_START, YELLOW, RESET
from i18n import t
from core import load_profile_url
from menu import (show_menu, menu_update_and_run_with_dashboard,
                  menu_run_with_dashboard_no_update, menu_open_dashboard_only,
                  menu_additional, menu_stop_vpn, menu_toggle_language)


def main():
    """Главная функция программы"""
    ensure_dirs()

    if FORCE_ADMIN_AT_START and get_os() != "linux" and not is_admin():
        print_info(t("admin_required"))
        print_info(t("admin_restart"))
        time.sleep(1)
        if not restart_as_admin():
            print_error(t("admin_failed"))
            input(f"\n{YELLOW}{t('press_enter_exit')}{RESET}")
            sys.exit(1)

    load_profile_url()

    def signal_handler(sig, frame):
        print_info(f"\n{t('exiting')}")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while True:
        show_menu()
        choice = input(f"{YELLOW}{t('choose_action')}{RESET}").strip()

        if choice == "1":
            menu_update_and_run_with_dashboard()
        elif choice == "2":
            menu_run_with_dashboard_no_update()
        elif choice == "3":
            menu_open_dashboard_only()
        elif choice == "4":
            menu_additional()
        elif choice == "5":
            menu_stop_vpn()
        elif choice == "6":
            menu_toggle_language()
        elif choice == "0":
            print_info(t("exiting"))
            sys.exit(0)
        else:
            print_error(t("invalid_choice"))
            time.sleep(1)


if __name__ == "__main__":
    main()
