import os
import sys
import shutil
import subprocess
import time
import zipfile
import gzip
import urllib.parse
import requests
from pathlib import Path
from utils import (print_success, print_error, print_info, get_os, is_admin,
                   get_arch, check_avx2_support, ensure_dirs, get_script_dir)
from constants import (CORE_BINARY, CORE_LOG, ZASHBOARD_DIR, ARCHIVES_DIR,
                       CONFIG_CLEAN, CONFIG_SMART, URL_FILE, MAX_ARCHIVES,
                       CORE_REPO, ZASHBOARD_REPO, YELLOW, RESET)
from config import generate_smart_config
from github import (get_latest_release_info, github_download_url,
                    download_with_fallback, build_core_asset_name,
                    find_asset_for_platform)
from i18n import t

core_process = None


# === СТАТУС ЯДРА ===
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

def get_latest_archived_version():
    """Возвращает тег версии последнего архива ядра для текущей платформы"""
    prefix = f"prizrak-core-{get_os()}-{get_arch()}-"
    archives = [a for a in ARCHIVES_DIR.glob("prizrak-core-*") if a.name.startswith(prefix)]
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
    version = get_latest_archived_version() or t("not_installed")
    return f"prizrak-core | {os_name}-{arch} | {variant} | {version}"


# === АРХИВЫ ===
def save_archive(archive_path, version_tag):
    """Сохраняет архив в папку архивов"""
    ensure_dirs()
    ext = archive_path.suffix
    archive_name = f"prizrak-core-{get_os()}-{get_arch()}-{version_tag}{ext}"
    dest_path = ARCHIVES_DIR / archive_name
    if not dest_path.exists():
        shutil.copy2(archive_path, dest_path)
    cleanup_old_archives()

def cleanup_old_archives():
    """Удаляет старые архивы, оставляя только MAX_ARCHIVES последних"""
    archives = sorted(
        ARCHIVES_DIR.glob("prizrak-core-*"),
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
        ARCHIVES_DIR.glob("prizrak-core-*"),
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )

def find_archived_archive(version_tag):
    """Ищет архив ядра с указанным тегом версии"""
    prefix = f"prizrak-core-{get_os()}-{get_arch()}-{version_tag}"
    for a in ARCHIVES_DIR.glob("prizrak-core-*"):
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
            print_error(t("rb_extract_fail", error=error))
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
            print_success(t("rb_done", name=archive_path.name))
            return True
        else:
            print_error(t("binary_not_in_archive"))
            return False
    except Exception as e:
        print_error(t("rb_error", error=e))
        return False


# === ОБНОВЛЕНИЕ ЯДРА ===
def update_core():
    """Обновляет ядро prizrak-core до последней версии (с фоллбэком через зеркала).
    Политика: если обновление не удалось, но локальный бинарник есть — продолжаем
    с предупреждением; если бинарника нет — ошибка и возврат False."""
    print_info(t("core_checking"))

    tag, assets, err = get_latest_release_info(CORE_REPO)
    if err:
        print_error(t("core_release_fail", error=err))
        if Path(CORE_BINARY).exists():
            print_info(t("core_local"))
            return True
        return False

    # Сравниваем с последней сохранённой версией в archives/
    local_tag = get_latest_archived_version()
    if local_tag == tag:
        if Path(CORE_BINARY).exists():
            print_info(t("core_uptodate", tag=tag))
            return True
        archived = find_archived_archive(tag)
        if archived:
            print_info(t("core_restore"))
            return rollback_to_version(archived)

    # Ищем ассет для нашей платформы
    asset = None
    if assets:
        asset = find_asset_for_platform(assets)

    # Если ассет не найден через API, собираем имя детерминированно
    if not asset:
        asset_name = build_core_asset_name(tag)
        asset = {"name": asset_name}
        print_info(t("core_build_name", name=asset_name))

    archive_path = Path(asset["name"])
    download_url = github_download_url(CORE_REPO, tag, asset["name"])
    print_info(t("downloading", name=asset["name"]))

    success, err = download_with_fallback(download_url, archive_path)
    if not success:
        print_error(t("core_download_fail", error=err))
        if Path(CORE_BINARY).exists():
            print_info(t("core_local"))
            return True
        return False

    save_archive(archive_path, tag)

    temp_dir = Path("temp_extract")
    temp_dir.mkdir(exist_ok=True)

    success, error = extract_archive(archive_path, temp_dir)
    if not success:
        print_error(t("extract_fail", error=error))
        archive_path.unlink(missing_ok=True)
        if Path(CORE_BINARY).exists():
            print_info(t("core_local"))
            return True
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
    archive_path.unlink(missing_ok=True)

    if binary_found:
        if get_os() != "windows":
            os.chmod(CORE_BINARY, 0o755)
        print_success(t("core_updated", tag=tag))
        return True
    else:
        print_error(t("binary_not_in_archive"))
        if Path(CORE_BINARY).exists():
            print_info(t("core_local"))
            return True
        return False


# === ZASHBOARD ===
def get_zashboard_version():
    """Получает текущую версию zashboard из локального файла"""
    version_file = ZASHBOARD_DIR / "version.txt"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return None

def is_zashboard_valid():
    """Проверяет, что панель корректно распакована (index.html в корне папки)"""
    return (ZASHBOARD_DIR / "index.html").exists()

def update_zashboard():
    """Обновляет zashboard до последней версии (с фоллбэком через зеркала).
    Политика: если обновление не удалось, но папка валидна — продолжаем
    с предупреждением; если папки нет — ошибка."""
    print_info(t("zb_checking"))

    tag, assets, err = get_latest_release_info(ZASHBOARD_REPO)
    if err:
        print_error(t("core_release_fail", error=err))
        if is_zashboard_valid():
            print_info(t("zb_local"))
            return True
        return False

    latest_version = tag or "unknown"
    current_version = get_zashboard_version()

    if current_version == latest_version and is_zashboard_valid():
        print_info(t("zb_uptodate", version=current_version))
        return True

    asset = None
    for a in assets:
        if "dist" in a["name"].lower() and a["name"].endswith(".zip"):
            asset = a
            break

    # Если API недоступен, имя ассета zashboard всегда предсказуемо
    if not asset:
        if tag:
            asset = {"name": "dist.zip"}
        else:
            print_error(t("zb_no_archive"))
            if is_zashboard_valid():
                print_info(t("zb_local"))
                return True
            return False

    archive_path = Path("zashboard_temp.zip")
    download_url = github_download_url(ZASHBOARD_REPO, latest_version, asset["name"])
    print_info(t("downloading", name=f"zashboard {latest_version}"))

    success, err = download_with_fallback(download_url, archive_path)
    if not success:
        print_error(t("zb_download_fail", error=err))
        if is_zashboard_valid():
            print_info(t("zb_local"))
            return True
        return False

    try:
        if ZASHBOARD_DIR.exists():
            shutil.rmtree(ZASHBOARD_DIR)
        ZASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            zip_ref.extractall(ZASHBOARD_DIR)

        # Файлы панели лежат внутри подпапки dist/, а ядро ожидает
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
        archive_path.unlink(missing_ok=True)
        print_success(t("zb_updated", version=latest_version))
        return True
    except Exception as e:
        print_error(t("zb_extract_fail", error=e))
        archive_path.unlink(missing_ok=True)
        if is_zashboard_valid():
            print_info(t("zb_local"))
            return True
        return False


# === ПРОФИЛЬ ПОДПИСКИ ===
def load_profile_url():
    """Загружает ссылку на профиль из URL.txt или запрашивает у пользователя"""
    if URL_FILE.exists():
        url = URL_FILE.read_text(encoding="utf-8").strip()
        if url:
            return url

    print_info(t("prof_not_found"))
    print_info(t("prof_paste"))
    print_info(t("prof_paste_hint"))
    url = input(f"{YELLOW}{t('prof_prompt')}{RESET}").strip()

    if url:
        URL_FILE.write_text(url, encoding="utf-8")
        print_success(t("prof_saved"))
        return url
    else:
        return ""

def validate_url(url):
    """Проверяет валидность URL. Возвращает (валидность, текст ошибки)"""
    if not url or not url.strip():
        return False, t("val_empty")
    parsed = urllib.parse.urlparse(url)
    if not all([parsed.scheme, parsed.netloc]):
        return False, t("val_bad")
    if parsed.scheme not in ['http', 'https']:
        return False, t("val_scheme")
    return True, None

def update_profile():
    """Скачивает и обновляет пользовательский профиль,
    затем перегенерирует smart-config.yaml"""
    profile_url = load_profile_url()
    if not profile_url:
        print_error(t("prof_url_missing"))
        return False

    valid, error = validate_url(profile_url)
    if not valid:
        print_error(error)
        return False

    print_info(t("prof_downloading"))
    try:
        response = requests.get(profile_url, timeout=15)
        if response.status_code == 401 or response.status_code == 403:
            print_error(t("prof_auth"))
            return False
        if response.status_code != 200:
            print_error(t("prof_unavailable"))
            return False

        CONFIG_CLEAN.write_text(response.text, encoding="utf-8")
        print_success(t("prof_ok"))
        generate_smart_config()
        return True
    except requests.exceptions.ConnectionError:
        print_error(t("prof_noconn"))
        return False
    except Exception as e:
        print_error(t("prof_error", error=e))
        return False


# === УПРАВЛЕНИЕ ЯДРОМ ===
def start_core():
    """Запускает ядро prizrak-core в фоне с конфигом smart-config.yaml.
    Если smart-config.yaml нет, но есть config.yaml — генерирует на лету."""
    global core_process

    # Если ядро уже работает - не запускаем второй экземпляр
    pid = get_core_pid()
    if pid:
        print_info(t("start_already", pid=pid))
        return True

    if not Path(CORE_BINARY).exists():
        print_error(t("start_no_binary"))
        return False

    # Если smart-config.yaml нет, но есть config.yaml — генерируем
    if not CONFIG_SMART.exists():
        if CONFIG_CLEAN.exists():
            print_info(t("start_gen_smart"))
            if not generate_smart_config():
                return False
        else:
            print_error(t("start_no_config"))
            return False

    try:
        script_dir = get_script_dir()
        binary_path = script_dir / CORE_BINARY
        config_path = script_dir / CONFIG_SMART
        ui_path = script_dir / "zashboard"
        log_path = script_dir / CORE_LOG

        base_cmd = [str(binary_path), "-f", str(config_path), "-ext-ui", str(ui_path)]

        # Если мы не root, нужно повысить права
        if not is_admin():
            if get_os() == "linux":
                if shutil.which("pkexec"):
                    print_info(t("start_pkexec"))
                    cmd = ["pkexec", "env", f"SAFE_PATHS={ui_path}"] + base_cmd
                    with open(log_path, "wb") as core_log:
                        core_process = subprocess.Popen(
                            cmd,
                            stdout=core_log,
                            stderr=core_log,
                            cwd=str(script_dir)
                        )
                elif shutil.which("sudo"):
                    print_error(t("start_sudo_noprompt"))
                    print_info(t("start_options"))
                    print_info(t("start_opt1"))
                    print_info(t("start_opt2"))
                    return False
                else:
                    print_error(t("start_no_root_mech"))
                    print_info(t("start_install_polkit"))
                    return False
            elif get_os() == "windows":
                print_error(t("start_win_admin"))
                print_info(t("start_win_hint"))
                return False
            else:  # macOS
                print_error(t("start_mac_admin"))
                print_info(t("start_mac_hint"))
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

        # Ждём появления ядра в процессах: при запуске через pkexec ко времени
        # старта добавляется ввод пароля в графическом окне, поэтому
        # фиксированная пауза давала ложное "ядро не запустилось"
        pid = None
        deadline = time.time() + 30
        while time.time() < deadline:
            pid = get_core_pid()
            if pid:
                break
            # Обёртка (pkexec) умерла до старта ядра — отмена авторизации
            # или ошибка: дальше ждать бессмысленно
            if core_process is not None and core_process.poll() is not None:
                break
            time.sleep(0.5)

        if pid is None:
            error_output = log_path.read_text(errors="replace").strip()
            tail = error_output.splitlines()[-5:]
            print_error(t("start_failed_log"))
            for line in tail:
                print_error(f"  {line}")
            return False

        print_success(t("started", pid=pid))
        return True
    except PermissionError:
        print_error(t("start_no_perm"))
        if get_os() != "windows":
            print_info(t("start_chmod", binary=CORE_BINARY))
        return False
    except Exception as e:
        print_error(t("start_error", error=e))
        return False

def stop_core():
    """Останавливает процесс ядра (с запросом прав, если ядро работает от root)"""
    global core_process

    if get_core_pid() is None and core_process is None:
        print_info(t("stop_not_running"))
        return

    if get_os() == "windows":
        # На Windows скрипт работает от администратора (UAC), taskkill напрямую
        subprocess.run(["taskkill", "/F", "/IM", CORE_BINARY], capture_output=True)
    else:
        pkill_path = shutil.which("pkill") or "/usr/bin/pkill"
        if is_admin():
            subprocess.run([pkill_path, "-x", CORE_BINARY], capture_output=True)
        else:
            # Ядро запущено от root - для остановки нужны права
            print_info(t("stop_pkexec"))
            if shutil.which("pkexec"):
                subprocess.run(["pkexec", pkill_path, "-x", CORE_BINARY], capture_output=True)
            elif shutil.which("sudo"):
                # sudo спросит пароль прямо в терминале
                subprocess.run(["sudo", pkill_path, "-x", CORE_BINARY])
            else:
                print_error(t("stop_no_mech"))
                return

    core_process = None

    # Проверяем реальный результат, а не верим себе на слово
    time.sleep(0.5)
    if get_core_pid() is None:
        print_info(t("stopped"))
    else:
        print_error(t("stop_failed"))
