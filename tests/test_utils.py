import re
from pathlib import Path

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


def test_group_button_colors_fallback_untouched():
    """Темы без ключей group_btn_* обязаны получить прежнюю пару:
    это гарантия, что nanita/geek_green/blue_fir/monokai не изменились."""
    for name in ("nanita", "geek_green", "blue_fir", "monokai"):
        th = utils.THEMES[name]
        assert utils.get_group_button_colors(name) == (
            th["group_bg"], th["group_text"], th["button_hover"]
        )


def test_group_button_colors_varekai_ikigai():
    """Текст = фон кнопки «Логи»; фон = заданная доля яркости текста."""
    ratios = {"varekai": 0.25, "ikigai": 0.30}
    for name, ratio in ratios.items():
        th = utils.THEMES[name]
        bg, text, hover = utils.get_group_button_colors(name)
        assert text == th["button_bg"]
        assert hover != bg
        base, dark = th["button_bg"].lstrip("#"), bg.lstrip("#")
        for i in (0, 2, 4):
            assert abs(int(dark[i:i + 2], 16) - round(int(base[i:i + 2], 16) * ratio)) <= 1


def test_group_button_bg_separable_from_tech_bg():
    """Фон кнопки группы не должен сливаться с фоном окна групп.

    Меряем разницу по каналам, а не по яркости: у ikigai различие
    хроматическое (фиолетовая кнопка на серо-синем окне) при почти
    одинаковой luminance — тест по яркости этот дефект не ловит.
    Прежняя пара #2F253E / #30323E давала Δ=13 и завалилась бы здесь.
    """
    for name in ("varekai", "ikigai"):
        th = utils.THEMES[name]
        btn, win = th["group_btn_bg"].lstrip("#"), th["tech_bg"].lstrip("#")
        delta = max(abs(int(btn[i:i + 2], 16) - int(win[i:i + 2], 16)) for i in (0, 2, 4))
        assert delta >= 15, f"{name}: кнопка сливается с окном групп (Δ={delta})"


def test_scrollbar_palette_not_affected_by_group_buttons():
    """Ползунки читают group_bg/group_text — они не должны потемнеть
    вместе с кнопками групп."""
    for name in ("varekai", "ikigai"):
        th = utils.THEMES[name]
        assert th["group_bg"] == th["button_bg"]
        assert th["group_bg"] != th["group_btn_bg"]


def test_project_version_is_pep440():
    """setuptools отвергает не-PEP440 версию на `pip install -e .`.
    Ни ruff, ни остальные тесты этого не проверяют — дефект уезжает
    в CI. Значение '0.9.9f' ломало сборку именно так."""
    ver = pytest.importorskip("packaging.version")
    root = Path(__file__).resolve().parent.parent
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m, "в pyproject.toml не найден project.version"
    ver.Version(m.group(1))   # InvalidVersion — если версия не по PEP 440
