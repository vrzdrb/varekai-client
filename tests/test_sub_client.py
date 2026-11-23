import re

import pytest

import age_crypto
import sub_client

HWID_RE = re.compile(r"[a-zA-Z0-9=-]{10,64}")  # формат из сервера hwid-sub


@pytest.fixture
def paths(tmp_path, monkeypatch):
    url = tmp_path / "URL.txt"
    cfg = tmp_path / "config.yaml"
    key = tmp_path / "age-key.txt"
    monkeypatch.setattr(sub_client, "URL_FILE", url)
    monkeypatch.setattr(sub_client, "CONFIG_CLEAN", cfg)
    monkeypatch.setattr(sub_client, "AGE_KEY_FILE", key)
    monkeypatch.setattr(sub_client, "generate_smart_config", lambda *a, **k: True)
    monkeypatch.setattr(sub_client, "save_meta", lambda m: True)
    return url, cfg, key


def test_hwid_matches_server_format():
    hwid = sub_client.get_hwid()
    assert HWID_RE.fullmatch(hwid)
    assert hwid == sub_client.get_hwid()   # стабильно в рамках процесса


def test_device_headers_present():
    h = sub_client.device_headers()
    for k in ("X-Hwid", "X-Device-OS", "X-Ver-OS", "X-Device-Model", "User-Agent"):
        assert h.get(k)


def test_plain_profile_written(paths, monkeypatch):
    url, cfg, _ = paths
    url.write_text("https://sub.example.com/abc", encoding="utf-8")
    monkeypatch.setattr(sub_client, "_fetch",
                        lambda u: (200, b"proxies: []\n", {}, None))
    assert sub_client.update_profile()[0] == 1
    assert cfg.read_bytes() == b"proxies: []\n"


def test_new_url_migrates_silently(paths, monkeypatch):
    url, cfg, _ = paths
    url.write_text("https://old.example.com/a", encoding="utf-8")
    calls = []

    def fake(u):
        calls.append(u)
        if u.startswith("https://old"):
            return 200, b"old", {"new_url": "https://new.example.com/b"}, None
        return 200, b"proxies: []\n", {}, None

    monkeypatch.setattr(sub_client, "_fetch", fake)
    assert sub_client.update_profile()[0] == 1
    assert calls == ["https://old.example.com/a", "https://new.example.com/b"]
    assert url.read_text(encoding="utf-8").strip() == "https://new.example.com/b"
    assert cfg.read_bytes() == b"proxies: []\n"


def test_migration_is_bounded(paths, monkeypatch):
    """Сервер каждый раз присылает новый URL — переходы обрываются
    на MAX_MIGRATIONS, тело последнего ответа применяется."""
    url, _, _ = paths
    url.write_text("https://h0.example.com/s", encoding="utf-8")
    seen = []

    def fake(u):
        seen.append(u)
        return 200, b"proxies: []\n", {"new_url": f"https://h{len(seen)}.example.com/s"}, None

    monkeypatch.setattr(sub_client, "_fetch", fake)
    sub_client.update_profile()
    assert len(seen) == sub_client.MAX_MIGRATIONS + 1
    assert len(set(seen)) == len(seen)   # повторов нет


def test_migration_pingpong_stops(paths, monkeypatch):
    """A -> B -> A: возврат к уже посещённой ссылке не выполняется."""
    url, cfg, _ = paths
    url.write_text("https://a.example.com/1", encoding="utf-8")
    seen = []

    def fake(u):
        seen.append(u)
        nxt = "https://b.example.com/2" if "//a." in u else "https://a.example.com/1"
        return 200, b"proxies: []\n", {"new_url": nxt}, None

    monkeypatch.setattr(sub_client, "_fetch", fake)
    assert sub_client.update_profile()[0] == 1
    assert seen == ["https://a.example.com/1", "https://b.example.com/2"]
    assert cfg.read_bytes() == b"proxies: []\n"


def test_fallback_used_on_failure(paths, monkeypatch):
    url, _, _ = paths
    url.write_text("https://main.example.com/a", encoding="utf-8")

    def fake(u):
        if "//main." in u:
            return 0, b"", {"fallback_url": "https://backup.example.com/b"}, "net down"
        return 200, b"proxies: []\n", {}, None

    monkeypatch.setattr(sub_client, "_fetch", fake)
    assert sub_client.update_profile()[0] == 1
    assert url.read_text(encoding="utf-8").strip() == "https://backup.example.com/b"


def test_encrypted_without_key_reports_hint(paths, monkeypatch):
    url, _, _ = paths
    url.write_text("https://sub.example.com/a", encoding="utf-8")
    armor = (b"-----BEGIN AGE ENCRYPTED FILE-----\nAAAA\n"
             b"-----END AGE ENCRYPTED FILE-----\n")
    monkeypatch.setattr(sub_client, "_fetch", lambda u: (200, armor, {}, None))
    status, msg = sub_client.update_profile()
    assert status == 2
    assert "--age-key" in msg


def test_html_error_page_not_saved_as_config(paths, monkeypatch):
    url, cfg, _ = paths
    url.write_text("https://sub.example.com/a", encoding="utf-8")
    monkeypatch.setattr(sub_client, "_fetch",
                        lambda u: (200, b"<!DOCTYPE html><html>oops", {}, None))
    assert sub_client.update_profile()[0] == 2
    assert not cfg.exists()


def test_auto_update_due():
    now = 1_900_000_000
    assert sub_client.auto_update_due({"update_interval": 24, "fetched": now}, now) is False
    assert sub_client.auto_update_due(
        {"update_interval": 24, "fetched": now - 25 * 3600}, now) is True
    assert sub_client.auto_update_due({"update_interval": 0, "fetched": 0}, now) is False
    assert sub_client.auto_update_due({}, now) is False


def test_age_key_roundtrip(paths):
    _, _, key = paths
    secret = age_crypto.bech32_encode("age-secret-key-", bytes(range(32))).upper()
    assert sub_client.validate_age_key(secret) is None
    assert sub_client.save_age_key(secret) is True
    assert sub_client.load_age_key() == secret
    assert key.exists()


def test_age_key_rejects_typo():
    good = age_crypto.bech32_encode("age-secret-key-", bytes(range(32)))
    bad = good[:-2] + ("q" if good[-2] != "q" else "p") + good[-1]
    assert sub_client.validate_age_key(bad)
