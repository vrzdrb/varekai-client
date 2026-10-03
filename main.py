#!/usr/bin/env python3
"""
Varekai-client - кросс-платформенный TUI для prizrak-core
"""
import os
import signal
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).resolve().parent)
else:
    os.chdir(Path(__file__).resolve().parent)

from utils import (
    FORCE_ADMIN_AT_START,
    URL_FILE,
    ensure_dirs,
    get_os,
    is_admin,
    restart_as_admin,
    setup_console,
    t,
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

_close_handler_ref = None


def install_close_handler():
    """Windows: при нажатии крестика консоли спросить, оставить ли VPN
    работающим в фоне. Нативный MessageBox — Textual-диалог в этот момент
    показать уже нельзя, консоль уничтожается."""
    global _close_handler_ref
    if get_os() != "windows":
        return
    try:
        import ctypes

        from core import get_core_pid, stop_vpn

        handler_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong)
        CTRL_CLOSE_EVENT = 2

        def _on_ctrl(ctrl_type):
            try:
                if ctrl_type == CTRL_CLOSE_EVENT and get_core_pid():
                    answer = ctypes.windll.user32.MessageBoxW(
                        None,
                        t("quit_dialog_msg"),
                        "varekai",
                        0x4 | 0x20,  # MB_YESNO | MB_ICONQUESTION
                    )
                    if answer == 7:  # «Нет» — остановить VPN перед выходом
                        stop_vpn()
            except Exception:
                pass
            return True

        _close_handler_ref = handler_type(_on_ctrl)
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_close_handler_ref, True)
    except Exception:
        pass


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

    install_close_handler()

    from tui import run_tui
    run_tui()

if __name__ == "__main__":
    main()

