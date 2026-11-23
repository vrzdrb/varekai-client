"""
Клиент подписки: запрос с заголовками устройства, age-расшифровка,
метаданные ответа, миграция ссылки по new-url / fallback-url.

Миграция выполняется молча, по указанию сервера. Технические границы
(не спрашивают пользователя): только http/https, не более
MAX_MIGRATIONS переходов за цикл, уже посещённые ссылки не повторяются —
защита от петли A -> B -> A.
"""

import hashlib
import os
import platform
import re
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

import requests

import age_crypto
from config import generate_smart_config
from sub_meta import parse_headers, save_meta
from utils import (
    AGE_KEY_FILE,
    APP_VERSION,
    CONFIG_CLEAN,
    URL_FILE,
    get_arch,
    get_os,
    t,
)

MAX_MIGRATIONS = 3
FETCH_TIMEOUT = 20
_HWID_CACHE = ""


# ---------------------------------------------------------------- устройство
def get_hwid() -> str:
    """Стабильный идентификатор машины под формат сервера:
    HWID_RE = [a-zA-Z0-9=-]{10,64}. sha256-hex — ровно 64 символа.

    Основа — машинные ID ОС, а не случайное число в файле: переустановка
    клиента не должна занимать ещё один слот устройства в подписке."""
    global _HWID_CACHE
    if _HWID_CACHE:
        return _HWID_CACHE
    raw = ""
    try:
        os_name = get_os()
        if os_name == "windows":
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as key:
                raw = str(winreg.QueryValueEx(key, "MachineGuid")[0])
        elif os_name == "darwin":
            r = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5,
            )
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', r.stdout or "")
            raw = m.group(1) if m else ""
        else:
            for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                try:
                    raw = Path(p).read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                if raw:
                    break
    except Exception:
        raw = ""
    if not raw:
        raw = f"{platform.node()}|{platform.machine()}|{platform.processor()}"
    _HWID_CACHE = hashlib.sha256(("varekai-hwid|" + raw).encode("utf-8")).hexdigest()
    return _HWID_CACHE


def device_headers() -> dict:
    """Заголовки, которые hwid-sub читает при выдаче подписки."""
    try:
        arch = get_arch()
    except RuntimeError:
        arch = platform.machine() or "unknown"
    os_name = get_os()
    pretty = {"windows": "Windows", "darwin": "macOS"}.get(os_name, "Linux")
    return {
        "User-Agent": f"Varekai-Client/{APP_VERSION} ({pretty}; {arch})",
        "X-Hwid": get_hwid(),
        "X-Device-OS": pretty,
        "X-Ver-OS": (platform.release() or "")[:64],
        "X-Device-Model": (platform.machine() or "")[:64],
    }


# ---------------------------------------------------------------- ключ age
def load_age_key() -> str:
    """Строка AGE-SECRET-KEY-… из age-key.txt. Комментарии (# public key)
    пропускаются — можно положить файл целиком от age-keygen."""
    try:
        if AGE_KEY_FILE.exists():
            for line in AGE_KEY_FILE.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.upper().startswith("AGE-SECRET-KEY-"):
                    return s
    except Exception:
        pass
    return ""


def save_age_key(line: str) -> bool:
    try:
        AGE_KEY_FILE.write_text(line.strip() + "\n", encoding="utf-8")
        try:
            os.chmod(AGE_KEY_FILE, 0o600)
        except OSError:
            pass  # Windows: каталог и так пользовательский
        return True
    except Exception:
        return False


def validate_age_key(line: str):
    """-> текст ошибки или None. PQ-ключи принимаются: их расшифрует
    внешняя утилита age, поэтому длину payload не ограничиваем."""
    try:
        hrp, raw = age_crypto.bech32_decode(line)
    except age_crypto.AgeError as e:
        return str(e)
    if not hrp.startswith("age-secret-key-"):
        return "ожидается строка AGE-SECRET-KEY-…"
    if hrp == "age-secret-key-" and len(raw) != 32:
        return "ключ X25519 должен содержать 32 байта"
    return None


# ---------------------------------------------------------------- ссылка
def _load_url() -> str:
    try:
        if URL_FILE.exists():
            return URL_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def _valid_url(url) -> bool:
    try:
        p = urllib.parse.urlparse(url or "")
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.netloc)


def _write_url(url: str) -> None:
    try:
        URL_FILE.write_text(url.strip() + "\n", encoding="utf-8")
    except Exception:
        pass


def _fetch(url: str):
    """-> (http_status, body_bytes, meta, error). status 0 = сетевой сбой."""
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT, headers=device_headers())
    except requests.exceptions.RequestException as e:
        return 0, b"", {}, f"{t('profile_update_fail')}: {e}"
    # .content, а не .text: requests угадывает кодировку по заголовкам,
    # а сервер отдаёт text/plain без charset для armor.
    return r.status_code, r.content or b"", parse_headers(r.headers), None


def _write_config(plain: bytes) -> bool:
    """Атомарная запись config.yaml: обрыв на середине не должен
    оставить обрезанный конфиг, с которым ядро потом не стартует."""
    try:
        fd, tmp = tempfile.mkstemp(dir=str(CONFIG_CLEAN.parent), prefix=".config-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(plain)
            os.replace(tmp, str(CONFIG_CLEAN))
            return True
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception:
        pass
    return False


def _looks_like_config(plain: bytes) -> bool:
    head = plain[:200].decode("utf-8", "replace").strip().lower()
    if not head or head.startswith(("<html", "<!doctype")):
        return False
    return True


# ---------------------------------------------------------------- обновление
def update_profile():
    """Скачивает профиль, расшифровывает age, применяет new-url /
    fallback-url, сохраняет метаданные. Возвращает (status, message):
    1 = обновлено, 2 = ошибка. Сигнатура прежняя — вызовы не ломаются."""
    url = _load_url()
    if not url:
        return 2, t("val_empty")
    if not _valid_url(url):
        return 2, t("val_scheme")

    identity = load_age_key()
    visited = []
    notes = []

    for hop in range(MAX_MIGRATIONS + 1):
        visited.append(url)
        status, body, meta, error = _fetch(url)
        if meta:
            save_meta(meta)   # в т.ч. причины отказа 403/404 — их покажет панель

        if status != 200:
            fallback = meta.get("fallback_url")
            if _valid_url(fallback) and fallback not in visited:
                url = fallback
                _write_url(url)
                notes.append(t("sub_url_fallback"))
                continue
            return 2, error or f"{t('profile_update_fail')}: HTTP {status}"

        was_armor = age_crypto.is_armor(body)
        try:
            plain = age_crypto.decrypt(body, identity)
        except age_crypto.AgeError as e:
            if was_armor and not identity.strip():
                return 2, t("age_needed")
            return 2, t("age_decrypt_fail", error=str(e))

        new_url = meta.get("new_url")
        if (hop < MAX_MIGRATIONS and _valid_url(new_url)
                and new_url != url and new_url not in visited):
            url = new_url
            _write_url(url)
            notes.append(t("sub_url_migrated"))
            continue

        if not _looks_like_config(plain):
            return 2, f"{t('profile_update_fail')}: {t('val_bad')}"
        if not _write_config(plain):
            return 2, t("profile_update_fail")
        if not generate_smart_config():
            return 2, t("profile_update_fail")

        msg = t("profile_updated") + (" (age)" if was_armor else "")
        if notes:
            msg += " · " + "; ".join(dict.fromkeys(notes))
        return 1, msg

    return 2, f"{t('profile_update_fail')}: {t('sub_url_migrated')}"


def auto_update_due(meta: dict, now=None) -> bool:
    """Пора ли обновить профиль по Profile-Update-Interval (часы).
    Точка отсчёта — время последнего успешного запроса из метаданных,
    а не старт приложения: расписание переживает перезапуск и сон."""
    hours = (meta or {}).get("update_interval")
    if not isinstance(hours, int) or not 1 <= hours <= 720:
        return False
    fetched = (meta or {}).get("fetched")
    if not isinstance(fetched, int) or fetched <= 0:
        return False
    now = time.time() if now is None else now
    return (now - fetched) >= hours * 3600
