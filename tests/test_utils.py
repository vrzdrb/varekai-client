import pytest

import utils


def test_get_arch_known_mappings(monkeypatch):
    monkeypatch.setattr(utils.platform, "machine", lambda: "x86_64")
    assert utils.get_arch() == "amd64"
    monkeypatch.setattr(utils.platform, "machine", lambda: "AMD64")
    assert utils.get_arch() == "amd64"
    monkeypatch.setattr(utils.platform, "machine", lambda: "arm64")
    assert utils.get_arch() == "arm64"
    monkeypatch.setattr(utils.platform, "machine", lambda: "aarch64")
    assert utils.get_arch() == "arm64"


def test_get_arch_unsupported(monkeypatch):
    monkeypatch.setattr(utils.platform, "machine", lambda: "riscv64")
    with pytest.raises(RuntimeError):
        utils.get_arch()


def test_replace_flag_emojis_windows(monkeypatch):
    monkeypatch.setattr(utils, "get_os", lambda: "windows")
    assert utils.replace_flag_emojis("🇺🇸 USA") == "[US] USA"
    assert utils.replace_flag_emojis("🇩🇪 DE") == "[DE]"
    assert utils.replace_flag_emojis("🇷🇺 RU >> 🇨🇭 CH") == "[RU] >> [CH]"
    # код, являющийся частью слова, не обрезается
    assert utils.replace_flag_emojis("🇨🇿 CZNET Special") == "[CZ] CZNET Special"


def test_replace_flag_emojis_non_windows(monkeypatch):
    monkeypatch.setattr(utils, "get_os", lambda: "linux")
    assert utils.replace_flag_emojis("🇺🇸 USA") == "🇺🇸 USA"
