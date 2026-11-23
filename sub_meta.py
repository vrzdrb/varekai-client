"""
Метаданные подписки: разбор заголовков ответа сервера подписок
(hwid-sub / prizrak-box), хранение и подготовка строк для TUI.

Модуль НЕ зависит от Textual — только от utils, поэтому тестируется
без установленного интерфейса.

Разбираются: Subscription-Userinfo, Profile-Title,
Profile-Update-Interval, Announce, Announce-Url, Support-Url,
Subscription-Renew-Url, new-url, fallback-url, Notify-Expire-Days,
X-Hwid-Active, X-Hwid-Not-Supported, X-Hwid-Max-Devices-Reached.

pxa-latency-dots / pxa-global-mode-mp / global-mode НЕ разбираются:
это переключатели интерфейса prizrak-box, в varekai-client их нет.

Profile-Title и Announce приходят как 'base64:<b64>', если не ASCII.
"""

import base64
import json
import time

from utils import PROFILE_META_FILE, get_language, t

_SM_L10N = {
    "ru": {
        "sub_traffic": "↓ {down} · ↑ {up}",
        "sub_expire": "Действует до {date} ({days} дн.)",
        "sub_expired": "Срок действия истёк {date}",
        "sub_hwid_limit": "Достигнут лимит устройств подписки",
        "sub_hwid_unsupported": "Подписка требует HWID — клиент его не передал",
    },
    "en": {
        "sub_traffic": "↓ {down} · ↑ {up}",
        "sub_expire": "Valid until {date} ({days} d)",
        "sub_expired": "Expired {date}",
        "sub_hwid_limit": "Subscription device limit reached",
        "sub_hwid_unsupported": "Subscription requires HWID — client did not send it",
    },
}


def _sm_t(key: str, **kwargs) -> str:
    try:
        val = t(key, **kwargs)
        if val and val != key:
            return val
    except Exception:
        pass
    table = _SM_L10N.get(get_language(), _SM_L10N["en"])
    return table.get(key, key).format(**kwargs)


def _fmt_bytes(n) -> str:
    """Свой форматтер, а не tui_widgets.fmt_bytes: тот тянет Textual,
    а этот модуль должен остаться пригодным для тестов без интерфейса."""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _text(value):
    """Значение заголовка; 'base64:<b64>' раскодируется как UTF-8."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    if v.startswith("base64:"):
        try:
            v = base64.b64decode(v[7:]).decode("utf-8", "replace").strip()
        except Exception:
            return None
    v = "".join(ch for ch in v if ch >= " " or ch == "\t").strip()
    return v or None


def _int(value):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _flag(value):
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    if s in ("true", "1", "on"):
        return True
    if s in ("false", "0", "off"):
        return False
    return None


def parse_userinfo(value) -> dict:
    """'upload=1; download=2; expire=1700000000' -> dict с int-значениями."""
    out = {}
    if not isinstance(value, str):
        return out
    for part in value.split(";"):
        k, _, v = part.strip().partition("=")
        k = k.strip().lower()
        if k in ("upload", "download", "expire"):
            n = _int(v)
            if n is not None:
                out[k] = n
    return out


def parse_headers(headers) -> dict:
    """Заголовки ответа -> нормализованный словарь метаданных.
    Ключи регистра-независимы; неизвестные заголовки игнорируются."""
    h = {}
    try:
        for k, v in headers.items():
            h[str(k).lower()] = v
    except AttributeError:
        return {}

    ui = parse_userinfo(h.get("subscription-userinfo"))
    notify = []
    raw_notify = h.get("notify-expire-days")
    if isinstance(raw_notify, str):
        for p in raw_notify.replace(",", " ").split():
            n = _int(p)
            if n is not None and 1 <= n <= 365:
                notify.append(n)

    return {
        "title": _text(h.get("profile-title")),
        "upload": ui.get("upload"),
        "download": ui.get("download"),
        "expire": ui.get("expire"),
        "update_interval": _int(h.get("profile-update-interval")),
        "support_url": _text(h.get("support-url")),
        "renew_url": _text(h.get("subscription-renew-url")),
        "new_url": _text(h.get("new-url")),
        "fallback_url": _text(h.get("fallback-url")),
        "announce": _text(h.get("announce")),
        "announce_url": _text(h.get("announce-url")),
        "notify_expire_days": notify,
        "hwid_active": _flag(h.get("x-hwid-active")),
        "hwid_unsupported": _flag(h.get("x-hwid-not-supported")) is True,
        "hwid_limit_reached": _flag(h.get("x-hwid-max-devices-reached")) is True,
        "fetched": int(time.time()),
    }


def has_content(meta: dict) -> bool:
    """Есть ли что показывать в панели. Пустые метаданные не должны
    добавлять пустые строки в интерфейс у обычных подписок."""
    if not isinstance(meta, dict):
        return False
    for k in ("title", "upload", "download", "expire", "announce"):
        if meta.get(k) is not None:
            return True
    return bool(meta.get("hwid_limit_reached") or meta.get("hwid_unsupported"))


def save_meta(meta: dict) -> bool:
    try:
        PROFILE_META_FILE.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception:
        return False


def load_meta() -> dict:
    try:
        if PROFILE_META_FILE.exists():
            data = json.loads(PROFILE_META_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def summary(meta: dict, now=None) -> list:
    """[(kind, text)] для панели над кнопками. kind: info | warn | err.
    Порядок: титул+трафик, срок, объявление, отказы HWID."""
    if not has_content(meta):
        return []
    out = []

    bits = []
    title = meta.get("title")
    if title:
        bits.append(str(title))
    down, up = meta.get("download"), meta.get("upload")
    if down is not None or up is not None:
        bits.append(_sm_t("sub_traffic", down=_fmt_bytes(down or 0), up=_fmt_bytes(up or 0)))
    if bits:
        out.append(("info", " · ".join(bits)))

    exp = meta.get("expire")
    if isinstance(exp, int) and exp > 0:
        now = int(time.time()) if now is None else int(now)
        date = time.strftime("%d.%m.%Y", time.localtime(exp))
        if exp <= now:
            out.append(("err", _sm_t("sub_expired", date=date)))
        else:
            days = int((exp - now) // 86400)
            notify = meta.get("notify_expire_days") or []
            kind = "warn" if any(days <= d for d in notify if isinstance(d, int)) else "info"
            out.append((kind, _sm_t("sub_expire", date=date, days=days)))

    announce = meta.get("announce")
    if announce:
        out.append(("info", str(announce)))

    if meta.get("hwid_limit_reached"):
        out.append(("err", _sm_t("sub_hwid_limit")))
    if meta.get("hwid_unsupported"):
        out.append(("err", _sm_t("sub_hwid_unsupported")))
    return out
