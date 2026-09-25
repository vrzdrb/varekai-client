"""
Бизнес-логика: управление ядром, обновление, профиль
"""
import os
import sys
import shutil
import subprocess
import time
import zipfile
import gzip
import urllib.parse
import re
import requests
from pathlib import Path

from utils import (
    get_os, get_arch, check_avx2_support, ensure_dirs, get_script_dir,
    is_admin, t, URL_FILE, CORE_BINARY, CORE_LOG, ARCHIVES_DIR,
    CONFIG_CLEAN, CONFIG_SMART, MAX_ARCHIVES, CORE_REPO,
    DEFAULT_MIRRORS, MIRRORS_FILE
)
from config import generate_smart_config

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
    except Exception:
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
    variant = "v3" if (arch == "amd64" and avx2) else ("compatible" if arch == "amd64" else arch)
    version = get_latest_archived_version() or t("not_installed")
    return f"prizrak-core | {os_name}-{arch} | {variant} | {version}"


# === АРХИВЫ ===
def save_archive(archive_path, version_tag):
    """Сохраняет архив в папку архивов"""
    ensure_dirs()
    dest_path = ARCHIVES_DIR / f"prizrak-core-{get_os()}-{get_arch()}-{version_tag}{archive_path.suffix}"
    if not dest_path.exists():
        shutil.copy2(archive_path, dest_path)
    cleanup_old_archives()


def cleanup_old_archives():
    """Удаляет старые архивы, оставляя только MAX_ARCHIVES последних"""
    archives = sorted(ARCHIVES_DIR.glob("prizrak-core-*"), key=lambda x: x.stat().st_mtime, reverse=True)
    for old_archive in archives[MAX_ARCHIVES:]:
        try:
            old_archive.unlink()
        except Exception:
            pass


def get_available_archives():
    """Возвращает список доступных архивов для отката"""
    if not ARCHIVES_DIR.exists():
        return []
    return sorted(ARCHIVES_DIR.glob("prizrak-core-*"), key=lambda x: x.stat().st_mtime, reverse=True)


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
                binary_path = Path(extract_to) / Path(archive_path).stem
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
        success, _ = extract_archive(archive_path, temp_dir)
        if not success:
            return False
        binary_found = False
        for f in temp_dir.rglob("*"):
            if f.is_file() and not f.name.endswith(('.zip', '.gz')):
                shutil.copy2(f, CORE_BINARY)
                binary_found = True
                break
        shutil.rmtree(temp_dir, ignore_errors=True)
        if binary_found and get_os() != "windows":
            os.chmod(CORE_BINARY, 0o755)
        return binary_found
    except Exception:
        return False


# === GITHUB И ЗЕРКАЛА ===
def ensure_mirrors_file():
    """Создаёт mirrors.txt с дефолтами, если файла нет"""
    if not MIRRORS_FILE.exists():
        MIRRORS_FILE.write_text("\n".join(DEFAULT_MIRRORS) + "\n", encoding="utf-8")


def load_mirrors():
    """Читает список зеркал"""
    ensure_mirrors_file()
    mirrors = []
    for line in MIRRORS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            mirrors.append(line if line.endswith("/") else line + "/")
    return mirrors


def download_with_fallback(url, dest_path):
    """Скачивает файл: сначала напрямую, затем через зеркала"""
    for prefix in [""] + load_mirrors():
        try:
            response = requests.get(prefix + url, stream=True, timeout=5 if prefix == "" else 30)
            if response.status_code == 200:
                with open(dest_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True, None
        except requests.exceptions.RequestException:
            continue
    return False, t("gh_all_fail")


def get_latest_tag_via_redirect(repo):
    """Получает тег последнего релиза через редирект"""
    url = f"https://github.com/{repo}/releases/latest"
    for prefix in [""] + load_mirrors():
        try:
            r = requests.head(prefix + url, allow_redirects=True, timeout=5 if prefix == "" else 10)
            if r.status_code == 200 and "/tag/" in r.url:
                return r.url.rstrip("/").split("/tag/")[-1], None
        except requests.exceptions.RequestException:
            continue
    return None, t("gh_tag_fail")


def get_latest_release_info(repo):
    """Возвращает (tag, assets, error)"""
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/releases/latest",
            timeout=5,
            headers={"User-Agent": "Varekai-Client"}
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("tag_name"), data.get("assets", []), None
    except requests.exceptions.RequestException:
        pass
    return get_latest_tag_via_redirect(repo)


def github_download_url(repo, tag, asset_name):
    """Прямая ссылка на ассет релиза"""
    return f"https://github.com/{repo}/releases/download/{tag}/{asset_name}"


def build_core_asset_name(tag):
    """Детерминированно собирает имя ассета prizrak-core"""
    os_name, arch = get_os(), get_arch()
    micro = "-v3" if (arch == "amd64" and check_avx2_support()) else ("-v1" if arch == "amd64" else "")
    return f"prizrak-core-{os_name}-{arch}{micro}-{tag}{'.zip' if os_name == 'windows' else '.gz'}"


def find_asset_for_platform(assets):
    """Ищет подходящий бинарник для текущей платформы"""
    os_name, arch = get_os(), get_arch()
    avx2_supported = check_avx2_support()
    target_microarch = "v3" if (arch == "amd64" and avx2_supported) else ("v1" if arch == "amd64" else None)
    candidates = []
    for asset in assets:
        name = asset["name"].lower()
        if os_name not in name or arch not in name:
            continue
        if any(name.endswith(ext) for ext in ('.deb', '.rpm', '.pkg.tar.zst')):
            continue
        if (os_name == "windows" and not name.endswith(".zip")) or (os_name != "windows" and not name.endswith(".gz")):
            continue
        if "compatible" in name:
            continue
        if arch == "amd64" and target_microarch:
            if target_microarch == "v3" and "-v3-" not in name:
                continue
            if target_microarch == "v1" and ("-v2-" in name or "-v3-" in name):
                continue
        if re.search(r'-go\d+-', name):
            continue
        candidates.append(asset)
    return candidates[0] if candidates else None


# === ОБНОВЛЕНИЕ ЯДРА ===
def update_core():
    """Обновляет ядро prizrak-core до последней версии"""
    tag, assets, err = get_latest_release_info(CORE_REPO)
    if err:
        return Path(CORE_BINARY).exists()
    local_tag = get_latest_archived_version()
    if local_tag == tag and Path(CORE_BINARY).exists():
        return True
    archived = find_archived_archive(tag) if local_tag == tag else None
    if archived:
        return rollback_to_version(archived)
    asset = find_asset_for_platform(assets) if assets else None
    if not asset:
        asset = {"name": build_core_asset_name(tag)}
    archive_path = Path(asset["name"])
    success, _ = download_with_fallback(github_download_url(CORE_REPO, tag, asset["name"]), archive_path)
    if not success:
        return Path(CORE_BINARY).exists()
    save_archive(archive_path, tag)
    temp_dir = Path("temp_extract")
    temp_dir.mkdir(exist_ok=True)
    success, _ = extract_archive(archive_path, temp_dir)
    if not success:
        archive_path.unlink(missing_ok=True)
        return Path(CORE_BINARY).exists()
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
    if binary_found and get_os() != "windows":
        os.chmod(CORE_BINARY, 0o755)
    return binary_found or Path(CORE_BINARY).exists()


# === ПРОФИЛЬ ПОДПИСКИ ===
def load_profile_url():
    """Загружает ссылку на профиль из URL.txt"""
    if URL_FILE.exists():
        url = URL_FILE.read_text(encoding="utf-8").strip()
        if url:
            return url
    return ""


def validate_url(url):
    """Проверяет валидность URL"""
    if not url or not url.strip():
        return False, t("val_empty")
    parsed = urllib.parse.urlparse(url)
    if not all([parsed.scheme, parsed.netloc]):
        return False, t("val_bad")
    if parsed.scheme not in ['http', 'https']:
        return False, t("val_scheme")
    return True, None


def update_profile():
    """Скачивает и обновляет пользовательский профиль"""
    profile_url = load_profile_url()
    if not profile_url:
        return False
    valid, _ = validate_url(profile_url)
    if not valid:
        return False
    try:
        response = requests.get(profile_url, timeout=15)
        if response.status_code == 200:
            CONFIG_CLEAN.write_text(response.text, encoding="utf-8")
            generate_smart_config()
            return True
    except Exception:
        pass
    return False


# === УПРАВЛЕНИЕ ЯДРОМ ===
def start_vpn():
    """Запускает ядро prizrak-core в фоне"""
    global core_process
    if get_core_pid():
        return True
    if not Path(CORE_BINARY).exists():
        return False
    if not CONFIG_SMART.exists():
        if not CONFIG_CLEAN.exists() or not generate_smart_config():
            return False
    try:
        script_dir = get_script_dir()
        binary_path = script_dir / CORE_BINARY
        config_path = script_dir / CONFIG_SMART
        log_path = script_dir / CORE_LOG
        # Очищаем VPN.log при каждом запуске
        if log_path.exists():
            log_path.unlink()
        log_path.touch()
        base_cmd = [str(binary_path), "-f", str(config_path)]
        if not is_admin():
            if get_os() == "linux" and shutil.which("pkexec"):
                cmd = ["pkexec"] + base_cmd
                with open(log_path, "wb") as core_log:
                    core_process = subprocess.Popen(cmd, stdout=core_log, stderr=core_log, cwd=str(script_dir))
            else:
                return False
        else:
            cmd = base_cmd
            with open(log_path, "wb") as core_log:
                if get_os() == "windows":
                    core_process = subprocess.Popen(
                        cmd, stdout=core_log, stderr=core_log, cwd=str(script_dir),
                        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                    )
                else:
                    core_process = subprocess.Popen(
                        cmd, stdout=core_log, stderr=core_log, cwd=str(script_dir), start_new_session=True
                    )
        pid = None
        deadline = time.time() + 30
        while time.time() < deadline:
            pid = get_core_pid()
            if pid:
                break
            if core_process is not None and core_process.poll() is not None:
                break
            time.sleep(0.5)
        return pid is not None
    except Exception:
        return False


def stop_vpn():
    """Останавливает процесс ядра"""
    global core_process
    if get_core_pid() is None and core_process is None:
        return
    if get_os() == "windows":
        subprocess.run(["taskkill", "/F", "/IM", CORE_BINARY], capture_output=True)
    else:
        pkill_path = shutil.which("pkill") or "/usr/bin/pkill"
        if is_admin():
            subprocess.run([pkill_path, "-x", CORE_BINARY], capture_output=True)
        else:
            if shutil.which("pkexec"):
                subprocess.run(["pkexec", pkill_path, "-x", CORE_BINARY], capture_output=True)
            elif shutil.which("sudo"):
                subprocess.run(["sudo", pkill_path, "-x", CORE_BINARY])
    core_process = None
    time.sleep(0.5)
