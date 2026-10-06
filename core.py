"""
Бизнес-логика: управление ядром, обновление, профиль
"""
import gzip
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

from config import generate_smart_config
from utils import (
    ARCHIVES_DIR,
    CONFIG_CLEAN,
    CONFIG_SMART,
    CORE_BINARY,
    CORE_LOG,
    CORE_REPO,
    CORE_VERSION_FILE,
    DEFAULT_MIRRORS,
    MAX_ARCHIVES,
    MIRRORS_FILE,
    URL_FILE,
    check_avx2_support,
    ensure_dirs,
    get_arch,
    get_os,
    get_script_dir,
    is_admin,
    t,
)

core_process = None
_core_op_lock = threading.Lock()

@dataclass
class CoreArchive:
    tag: str
    path: Path
    mtime: float


# === ВЕРСИИ И АРХИВЫ ===
def _archive_prefix():
    return f"prizrak-core-{get_os()}-{get_arch()}-"


def _archive_ext():
    return ".zip" if get_os() == "windows" else ".gz"


def archive_path_for_tag(tag):
    return ARCHIVES_DIR / f"{_archive_prefix()}{tag}{_archive_ext()}"

def tag_from_archive(path):
    """Извлекает тег версии из имени архива ядра."""
    name = Path(path).name
    if name.endswith(".part"):
        return None
    prefix = _archive_prefix()
    if not name.startswith(prefix):
        return None
    tag = name[len(prefix):]
    for ext in (".gz", ".zip"):
        if tag.endswith(ext):
            tag = tag[: -len(ext)]
    return tag or None

def get_latest_archived_version():
    """Возвращает тег версии последнего по mtime архива ядра."""
    archives = list_core_archives()
    return archives[0].tag if archives else None


def get_current_version():
    """Текущая версия ядра: core-version.txt, fallback — последний архив."""
    try:
        if CORE_VERSION_FILE.exists():
            version = CORE_VERSION_FILE.read_text(encoding="utf-8").strip()
            if version:
                return version
    except Exception:
        pass
    return get_latest_archived_version()


def _write_current_version(tag):
    CORE_VERSION_FILE.write_text(tag, encoding="utf-8")


def list_core_archives():
    """Список архивов ядра текущей платформы, свежие первыми."""
    prefix = _archive_prefix()
    if not ARCHIVES_DIR.exists():
        return []
    result = []
    for p in ARCHIVES_DIR.glob(f"{prefix}*"):
        tag = tag_from_archive(p)
        if tag:
            try:
                result.append(CoreArchive(tag=tag, path=p, mtime=p.stat().st_mtime))
            except OSError:
                continue
    result.sort(key=lambda a: a.mtime, reverse=True)
    return result


def cleanup_old_archives():
    """Удаляет старые архивы, оставляя только MAX_ARCHIVES последних."""
    archives = list_core_archives()
    for old in archives[MAX_ARCHIVES:]:
        try:
            old.path.unlink()
        except Exception:
            pass


def find_archived_archive(tag):
    """Ищет архив ядра с указанным тегом версии."""
    path = archive_path_for_tag(tag)
    return path if path.exists() else None


# === РАСПАКОВКА И АТОМАРНАЯ ЗАМЕНА ===
def _safe_extract_zip(zip_path, dest):
    """Распаковка zip с защитой от path traversal."""
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        for member in zip_ref.infolist():
            target = (Path(dest) / member.filename).resolve()
            if not str(target).startswith(str(Path(dest).resolve())):
                raise ValueError(f"Unsafe path in archive: {member.filename}")
        zip_ref.extractall(dest)

def _archive_kind(archive_path):
    """Возвращает 'zip' или 'gz' по имени файла, игнорируя суффикс .part."""
    name = str(archive_path)
    if name.endswith(".part"):
        name = name[: -len(".part")]
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".gz"):
        return "gz"
    return None

def _validate_archive(archive_path):
    """Проверяет, что архив целый и не пустой. Возвращает (ok, error)."""
    kind = _archive_kind(archive_path)
    try:
        if kind == "zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                if zf.testzip() is not None:
                    return False, t("arch_broken")
                if not any(not i.is_dir() for i in zf.infolist()):
                    return False, t("arch_broken")
        elif kind == "gz":
            with gzip.open(archive_path, "rb") as f:
                if not f.read(1):
                    return False, t("arch_broken")
        else:
            return False, t("arch_broken")
        return True, None
    except Exception:
        return False, t("arch_broken")

def _extract_archive(archive_path, dest):
    """Распаковывает архив в dest. Возвращает (ok, error)."""
    try:
        kind = _archive_kind(archive_path)
        if kind == "zip":
            _safe_extract_zip(archive_path, dest)
        elif kind == "gz":
            with gzip.open(archive_path, "rb") as f_in:
                binary_path = Path(dest) / Path(str(archive_path).removesuffix(".part")).stem
                with open(binary_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            return False, t("arch_broken")
        return True, None
    except Exception:
        return False, t("arch_broken")


def _find_binary_in(directory):
    """Находит бинарник в распакованном каталоге: непустой файл, не архив."""
    candidates = []
    for f in Path(directory).rglob("*"):
        if f.is_file() and not f.name.endswith((".zip", ".gz")):
            try:
                size = f.stat().st_size
            except OSError:
                continue
            if size > 0:
                candidates.append((size, f))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _stage_and_replace(binary_path):
    """Атомарно заменяет prizrak-core новым бинарником. Возвращает (ok, error)."""
    stage_path = Path(str(CORE_BINARY) + ".new")
    try:
        if stage_path.exists():
            stage_path.unlink()
        shutil.copy2(binary_path, stage_path)
        if get_os() != "windows":
            os.chmod(stage_path, 0o755)
        os.replace(stage_path, CORE_BINARY)
        return True, None
    except Exception as e:
        try:
            if stage_path.exists():
                stage_path.unlink()
        except Exception:
            pass
        return False, f"{t('core_update_fail')}: {e}"


def _install_from_archive(archive_path):
    """Ставит ядро из архива: валидация -> temp -> atomic replace.
    Возвращает (ok, error)."""
    ok, err = _validate_archive(archive_path)
    if not ok:
        return False, err
    try:
        with tempfile.TemporaryDirectory(prefix="varekai-core-", dir=get_script_dir()) as tmp:
            ok, err = _extract_archive(archive_path, tmp)
            if not ok:
                return False, err
            binary = _find_binary_in(tmp)
            if binary is None:
                return False, t("arch_broken")
            return _stage_and_replace(binary)
    except Exception as e:
        return False, f"{t('core_update_fail')}: {e}"


# === СТАТУС ЯДРА ===
def get_core_pid():
    """Возвращает PID запущенного ядра или None"""
    try:
        if get_os() == "windows":
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {CORE_BINARY}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            lines = [line for line in result.stdout.splitlines() if CORE_BINARY.lower() in line.lower()]
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


def get_current_core_info():
    """Возвращает информацию о текущем ядре (ОС, архитектура, версия)"""
    os_name = get_os()
    arch = get_arch()
    avx2 = check_avx2_support()
    variant = "v3" if (arch == "amd64" and avx2) else ("compatible" if arch == "amd64" else arch)
    version = get_current_version() or t("not_installed")
    return f"prizrak-core | {os_name}-{arch} | {variant} | {version}"


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
    """Скачивает файл в dest_path: сначала напрямую, затем через зеркала.
    Возвращает (ok, error)."""
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
    """Обновляет ядро prizrak-core до последней версии.
    Только при остановленном VPN.
    Возвращает: (status, message); 0=уже актуально, 1=обновлено, 2=ошибка"""
    if get_core_pid():
        return 2, t("core_running_update")
    if not _core_op_lock.acquire(blocking=False):
        return 2, t("core_update_in_progress")
    try:
        return _update_core_impl()
    finally:
        _core_op_lock.release()


def _update_core_impl():
    try:
        ensure_dirs()

        # Чистим недокачанные остатки прошлых запусков.
        for stale in ARCHIVES_DIR.glob("*.part"):
            try:
                stale.unlink()
            except Exception:
                pass

        tag, assets, err = get_latest_release_info(CORE_REPO)
        if err:
            return 2, err

        current = get_current_version()
        if current == tag and Path(CORE_BINARY).exists():
            return 0, t("core_already_latest")

        # Если архив уже есть локально — ставим из него.
        archived = find_archived_archive(tag)
        if archived:
            ok, err = _install_from_archive(archived)
            if ok:
                _write_current_version(tag)
                cleanup_old_archives()
                return 1, t("core_updated", version=tag)
            # Битый архив не держим — качаем заново.
            try:
                archived.unlink()
            except Exception:
                pass

        asset = find_asset_for_platform(assets) if assets else None
        if asset:
            asset_name = asset["name"]
        else:
            # Детерминированное имя как fallback; сервер вернет ошибку, если ассета нет.
            asset_name = build_core_asset_name(tag)

        dest = archive_path_for_tag(tag)
        part = dest.with_name(dest.name + ".part")
        try:
            ok, err = download_with_fallback(github_download_url(CORE_REPO, tag, asset_name), part)
            if not ok:
                return 2, err
            ok, err = _validate_archive(part)
            if not ok:
                return 2, err
            os.replace(part, dest)
            ok, err = _install_from_archive(dest)
            if not ok:
                return 2, err
            _write_current_version(tag)
            cleanup_old_archives()
            return 1, t("core_updated", version=tag)
        finally:
            try:
                if part.exists():
                    part.unlink()
            except Exception:
                pass
    except Exception as e:
        return 2, f"{t('core_update_fail')}: {e}"


def rollback_to_tag(tag):
    """Откатывает ядро на версию tag из archives. Возвращает (ok, message)."""
    if get_core_pid():
        return False, t("core_running_rollback")
    if not _core_op_lock.acquire(blocking=False):
        return False, t("core_update_in_progress")
    try:
        archive = find_archived_archive(tag)
        if archive is None:
            return False, t("core_rollback_fail")
        ok, err = _install_from_archive(archive)
        if not ok:
            return False, err or t("core_rollback_fail")
        _write_current_version(tag)
        return True, t("core_rollback_ok", version=tag)
    finally:
        _core_op_lock.release()

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
    """Скачивает и обновляет пользовательский профиль.
    Возвращает: (status, message); 1=обновлено, 2=ошибка"""
    profile_url = load_profile_url()
    if not profile_url:
        return 2, t("val_empty")
    valid, err = validate_url(profile_url)
    if not valid:
        return 2, err
    try:
        response = requests.get(profile_url, timeout=15)
        if response.status_code == 200:
            CONFIG_CLEAN.write_text(response.text, encoding="utf-8")
            if not generate_smart_config():
                return 2, t("profile_update_fail")
            return 1, t("profile_updated")
        return 2, f"{t('profile_update_fail')}: HTTP {response.status_code}"
    except Exception as e:
        return 2, f"{t('profile_update_fail')}: {e}"


# === УПРАВЛЕНИЕ ЯДРОМ ===
def _start_detached(cmd, log_path, script_dir):
    """Запускает ядро отсоединённым от лаунчера."""
    global core_process
    with open(log_path, "wb") as core_log:
        if get_os() == "windows":
            core_process = subprocess.Popen(
                cmd, stdout=core_log, stderr=core_log, cwd=str(script_dir),
                creationflags=subprocess.CREATE_NO_WINDOW
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            # umask 0: файлы, которые ядро создаст от root (провайдеры
            # правил), останутся доступны пользователю на чтение/запись.
            old_umask = os.umask(0o000)
            try:
                core_process = subprocess.Popen(
                    cmd, stdout=core_log, stderr=core_log, cwd=str(script_dir),
                    start_new_session=True
                )
            finally:
                os.umask(old_umask)


def _mount_options(path):
    """Опции монтирования ФС, на которой лежит файл (/proc/self/mounts).
    Возвращает список опций самого глубокого подходящего mount-point."""
    try:
        target = str(Path(path).resolve())
        best_opts = []
        best_len = -1
        with open("/proc/self/mounts", "r", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 4:
                    continue
                mount_point = parts[1].replace("\\040", " ")
                if target.startswith(mount_point) and len(mount_point) > best_len:
                    best_opts = parts[3].split(",")
                    best_len = len(mount_point)
        return best_opts
    except Exception:
        return []


def _tun_is_up():
    """Поднялся ли TUN-интерфейс ядра. При невозможности проверить
    считаем, что поднялся (не будем трогать рабочий экземпляр)."""
    try:
        r = subprocess.run(
            ["ip", "-o", "link"], capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.splitlines():
            name = line.split(":", 2)[1].strip().split("@")[0].lower() if ":" in line else ""
            # Интерфейсы mihomo называются tun*/utun* — startswith, чтобы
            # не поймать ложное "veth_tun_ext".
            if name.startswith("tun") or name.startswith("utun"):
                return True
    except Exception:
        return True
    return False


def _ensure_core_capabilities(binary_path):
    """Разовая выдача CAP_NET_ADMIN бинарнику ядра: ядро сможет работать
    с TUN без root и писать в любые папки пользователя (в т.ч. тома
    VeraCrypt, куда root через pkexec может не иметь доступа).
    Требует поддержки xattr файловой системой; результат кэшируется
    маркером рядом с бинарником (повторяем после обновления ядра).
    Возвращает True, если capability гарантированно применены."""
    # nosuid: ядро игнорирует file capabilities — setcap бессмысленен,
    # а ядро молча останется без TUN. Сразу идём по пути root.
    if "nosuid" in _mount_options(binary_path):
        return False
    try:
        r = subprocess.run(
            ["getcap", str(binary_path)], capture_output=True, text=True, timeout=5
        )
        if "cap_net_admin" in r.stdout:
            return True
    except Exception:
        return False

    marker = binary_path.parent / ".varekai-no-setcap"
    try:
        mtime = str(int(binary_path.stat().st_mtime))
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == mtime:
            return False  # уже известно: FS не поддерживает, бинарник не менялся
    except Exception:
        pass

    try:
        if shutil.which("pkexec"):
            elev = ["pkexec"]
        elif shutil.which("sudo"):
            elev = ["sudo", "-E"]
        else:
            return False
        r = subprocess.run(
            elev + ["setcap", "cap_net_admin,cap_net_bind_service=+ep", str(binary_path)],
            capture_output=True, timeout=60,
        )
        r2 = subprocess.run(
            ["getcap", str(binary_path)], capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and "cap_net_admin" in r2.stdout:
            marker.unlink(missing_ok=True)
            return True
        # FS не хранит xattr (FAT/exFAT, часть FUSE) — не дёргаем pkexec каждый раз
        marker.write_text(mtime, encoding="utf-8")
        return False
    except Exception:
        return False


def _linux_elevated_cmd(base_cmd, script_dir=None):
    """pkexec предпочтительнее, sudo — fallback.

    Для долгоживущих команд (ядро) добавляем явный cd: pkexec при старте
    от root сбрасывает рабочий каталог, и относительные пути rule-providers
    (./unified/...) оседали в /root/unified вместо папки приложения."""
    if shutil.which("pkexec"):
        elev = ["pkexec"]
    elif shutil.which("sudo"):
        elev = ["sudo", "-E"]
    else:
        return None
    if script_dir is None:
        return elev + list(base_cmd)
    inner = (
        "cd " + shlex.quote(str(script_dir))
        + " && exec " + " ".join(shlex.quote(str(part)) for part in base_cmd)
    )
    return elev + ["bash", "-c", inner]


def start_vpn():
    """Запускает ядро prizrak-core в фоне. Возвращает (ok, message)."""
    global core_process
    if get_core_pid():
        return True, t("vpn_start_ok")
    if not Path(CORE_BINARY).exists():
        return False, t("core_not_found")
    if not CONFIG_SMART.exists():
        if not CONFIG_CLEAN.exists() or not generate_smart_config():
            return False, t("prof_not_found")
    try:
        script_dir = get_script_dir()
        binary_path = script_dir / CORE_BINARY
        config_path = script_dir / CONFIG_SMART
        log_path = script_dir / CORE_LOG
        if log_path.exists():
            log_path.unlink()
        log_path.touch()

        # Предсоздаём то, что ядро положит рядом: оно может работать от
        # root, и без этого файлы остались бы недоступны пользователю.
        try:
            unified_dir = script_dir / "unified"
            unified_dir.mkdir(exist_ok=True)
            os.chmod(unified_dir, 0o777)
            cache_path = script_dir / "cache.db"
            if not cache_path.exists():
                cache_path.touch(mode=0o666)
        except Exception:
            pass

        # -d задаёт домашнюю директорию ядра: все относительные пути
        # (rule-providers ./unified, external-ui) разрешаются от папки
        # приложения, а не от ~/.config/mihomo или /root.
        base_cmd = [str(binary_path), "-d", str(script_dir), "-f", str(config_path)]

        def _wait_pid():
            deadline = time.time() + 30
            while time.time() < deadline:
                pid = get_core_pid()
                if pid:
                    return pid
                if core_process is not None and core_process.poll() is not None:
                    break
                time.sleep(0.5)
            return None

        used_caps = False
        if not is_admin():
            if get_os() == "linux":
                # Вариант 1: ядро от пользователя с CAP_NET_ADMIN — без root,
                # пишет куда угодно (включая тома VeraCrypt).
                if _ensure_core_capabilities(binary_path):
                    used_caps = True
                    _start_detached(base_cmd, log_path, script_dir)
                else:
                    cmd = _linux_elevated_cmd(base_cmd, script_dir)
                    if cmd is None:
                        return False, t("elev_no_mech")
                    _start_detached(cmd, log_path, script_dir)
            else:
                return False, t("admin_required")
        else:
            _start_detached(base_cmd, log_path, script_dir)

        pid = _wait_pid()
        if used_caps:
            if pid and not _tun_is_up():
                # Ядро живо, но TUN не поднялся (caps проигнорированы,
                # интерфейс занят и т.п.) — такой экземпляр бесполезен:
                # гасим и поднимаем классически, от root.
                try:
                    subprocess.run(["pkill", "-x", CORE_BINARY], capture_output=True)
                    time.sleep(1)
                except Exception:
                    pass
                pid = None
            if not pid:
                cmd = _linux_elevated_cmd(base_cmd, script_dir)
                if cmd is not None:
                    _start_detached(cmd, log_path, script_dir)
                    pid = _wait_pid()
        if pid:
            return True, t("vpn_start_ok")
        return False, f"{t('vpn_start_fail')}: {t('log_core')}"
    except Exception as e:
        return False, f"{t('vpn_start_fail')}: {e}"


def stop_vpn():
    """Останавливает процесс ядра. Возвращает (ok, message)."""
    global core_process
    if get_core_pid() is None and core_process is None:
        return True, t("vpn_stop_ok")
    try:
        if get_os() == "windows":
            subprocess.run(["taskkill", "/F", "/IM", CORE_BINARY], capture_output=True)
        else:
            pkill_path = shutil.which("pkill") or "/usr/bin/pkill"
            if is_admin():
                subprocess.run([pkill_path, "-x", CORE_BINARY], capture_output=True)
            else:
                elevated = _linux_elevated_cmd([pkill_path, "-x", CORE_BINARY])
                if elevated is None:
                    return False, t("elev_no_mech")
                subprocess.run(elevated, capture_output=True)
        core_process = None
        time.sleep(0.5)
        if get_core_pid() is None:
            return True, t("vpn_stop_ok")
        return False, t("vpn_stop_fail")
    except Exception as e:
        return False, f"{t('vpn_stop_fail')}: {e}"

