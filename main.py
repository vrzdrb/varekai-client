#!/usr/bin/env python3
"""
Varekai-client - кросс-платформенный TUI для prizrak-core
"""
import os
import sys
import signal
from pathlib import Path

if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).resolve().parent)
else:
    os.chdir(Path(__file__).resolve().parent)

from utils import (
    setup_console, ensure_dirs, is_admin, restart_as_admin,
    get_os, t, FORCE_ADMIN_AT_START, URL_FILE
)

def request_profile_url():
    if URL_FILE.exists():
        url = URL_FILE.read_text(encoding="utf-8").strip()
        if url:
            return
    print(t("prof_paste"))
    print(t("prof_paste_hint"))
    url = input(f"{t('prof_prompt')}").strip()
    if url:
        URL_FILE.write_text(url, encoding="utf-8")
        print(t("prof_saved"))

def main():
    setup_console()
    ensure_dirs()

    if FORCE_ADMIN_AT_START and get_os() != "linux" and not is_admin():
        print(t("admin_required"))
        print(t("admin_restart"))
        import time
        time.sleep(1)
        if not restart_as_admin():
            print(t("admin_failed"))
            input(t("press_enter_exit"))
            sys.exit(1)

    request_profile_url()

    def signal_handler(sig, frame):
        print(f"\n{t('exiting')}")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    from tui import run_tui
    run_tui()

if __name__ == "__main__":
    main()
