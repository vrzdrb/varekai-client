import os
import sys
import threading
from datetime import datetime
from utils import print_info, print_error, get_os, get_script_dir, setup_gui_environment
from config import load_config_rt
from constants import DASHBOARD_LOG, PROFILE_DIR, CONFIG_CLEAN, DASHBOARD_NOISE
from i18n import t


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

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()
    except Exception:
        pass

def open_dashboard():
    """Открывает панель в окне самого скрипта.
    Закрытие окна панели = выход из программы (ядро продолжает работать)."""
    script_dir = get_script_dir()
    _start_stderr_filter(script_dir / DASHBOARD_LOG)
    setup_gui_environment()

    port = 9090
    secret = ""

    try:
        config_path = CONFIG_CLEAN
        if config_path.exists():
            config = load_config_rt(config_path)
            external_controller = config.get("external-controller", "127.0.0.1:9090")
            if ":" in external_controller:
                port = int(external_controller.split(":")[-1])
            secret = config.get("secret", "")
    except Exception as e:
        print_error(t("dash_cfg_error", error=e))

    if secret:
        dashboard_url = f"http://127.0.0.1:{port}/ui/#/setup?hostname=127.0.0.1&port={port}&secret={secret}"
    else:
        dashboard_url = f"http://127.0.0.1:{port}/ui/#/setup?hostname=127.0.0.1&port={port}"

    print_info(t("dash_opening", url=dashboard_url))

    try:
        import webview
        webview.create_window(
            title="Varekai Dashboard",
            url=dashboard_url,
            width=1200,
            height=800,
            resizable=True
        )
        print_info(t("dash_opened"))
        webview.start(
            gui="qt" if get_os() == "linux" else None,
            private_mode=False,
            storage_path=str(script_dir / PROFILE_DIR)
        )
    except ImportError:
        print_error(t("dash_no_webview"))
        return
    except Exception as e:
        print_error(t("dash_error", error=e))
        return

    print_info(t("dash_closed"))
    sys.exit(0)
