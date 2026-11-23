import base64

import sub_meta


def _headers(**extra):
    h = {
        "Subscription-Userinfo": "upload=1073741824; download=10737418240; expire=1900000000",
        "Profile-Update-Interval": "24",
        "Notify-Expire-Days": "7,3,1",
        "X-Hwid-Active": "true",
        "Support-Url": "https://t.me/example",
    }
    h.update(extra)
    return h


def test_parse_headers_basic():
    m = sub_meta.parse_headers(_headers())
    assert m["upload"] == 1073741824
    assert m["download"] == 10737418240
    assert m["expire"] == 1900000000
    assert m["update_interval"] == 24
    assert m["notify_expire_days"] == [7, 3, 1]
    assert m["hwid_active"] is True
    assert m["support_url"] == "https://t.me/example"


def test_case_insensitive_and_base64_title():
    title = "Привет, варекай"
    enc = "base64:" + base64.b64encode(title.encode()).decode()
    m = sub_meta.parse_headers({"PROFILE-TITLE": enc, "announce": enc})
    assert m["title"] == title
    assert m["announce"] == title


def test_unknown_headers_ignored():
    m = sub_meta.parse_headers({"X-Whatever": "1", "Server": "nginx"})
    assert sub_meta.has_content(m) is False
    assert sub_meta.summary(m) == []


def test_pxa_and_global_mode_are_ignored():
    """Переключатели интерфейса prizrak-box в varekai-client не нужны."""
    m = sub_meta.parse_headers({
        "pxa-latency-dots": "1",
        "pxa-global-mode-mp": "1",
        "global-mode": "1",
    })
    assert "pxa_latency_dots" not in m
    assert "pxa_global_mode_mp" not in m
    assert "global_mode" not in m
    assert sub_meta.has_content(m) is False


def test_hwid_refusal_flags():
    m = sub_meta.parse_headers({"X-Hwid-Max-Devices-Reached": "true"})
    assert m["hwid_limit_reached"] is True
    assert "err" in [k for k, _ in sub_meta.summary(m)]


def test_summary_traffic_and_expiry():
    m = sub_meta.parse_headers(_headers(**{"Profile-Title": "varekai"}))
    lines = sub_meta.summary(m, now=1900000000 - 10 * 86400)
    # строка 0 — титул + трафик, строка 1 — срок
    assert lines[0][0] == "info"
    assert "varekai" in lines[0][1]
    assert "10.0 GB" in lines[0][1]      # download
    assert lines[1][0] == "info"         # 10 дней > всех notify-порогов
    assert "10" in lines[1][1]


def test_expiry_warning_uses_notify_days():
    m = sub_meta.parse_headers(_headers())
    kinds = [k for k, _ in sub_meta.summary(m, now=1900000000 - 2 * 86400)]
    assert "warn" in kinds               # 2 дня <= порога 3
    assert "err" not in kinds


def test_expired_is_error():
    m = sub_meta.parse_headers(_headers())
    kinds = [k for k, _ in sub_meta.summary(m, now=1900000001)]
    assert "err" in kinds


def test_empty_meta_produces_nothing():
    assert sub_meta.summary({}) == []
    assert sub_meta.summary(None) == []
