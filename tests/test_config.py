import pytest

pytest.importorskip("ruamel.yaml")

import config

SAMPLE_CONFIG = """\
tun:
  enable: true
  strict-route: true
secret: testsecret
proxy-groups:
  - name: PROXY
    type: url-test
    tolerance: 50
    proxies:
      - NodeA
  - name: CHOICE
    type: selector
    proxies:
      - NodeA
proxies:
  - name: NodeA
    type: ss
"""


def _prepare_paths(tmp_path, monkeypatch):
    clean = tmp_path / "config.yaml"
    smart = tmp_path / "smart-config.yaml"
    clean.write_text(SAMPLE_CONFIG, encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_CLEAN", clean)
    monkeypatch.setattr(config, "CONFIG_SMART", smart)
    return clean, smart


def test_generate_smart_config_linux(tmp_path, monkeypatch):
    clean, smart = _prepare_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "get_os", lambda: "linux")

    assert config.generate_smart_config() is True

    data = config.load_config_rt(smart)
    groups = {g["name"]: g for g in data["proxy-groups"]}
    assert groups["PROXY"]["type"] == "smart"
    assert groups["PROXY"]["strategy"] == "sticky-sessions"
    assert "tolerance" not in groups["PROXY"]
    assert groups["CHOICE"]["type"] == "selector"
    assert data["tun"]["strict-route"] is True


def test_generate_smart_config_windows_strict_route(tmp_path, monkeypatch):
    clean, smart = _prepare_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "get_os", lambda: "windows")

    assert config.generate_smart_config() is True
    data = config.load_config_rt(smart)
    assert data["tun"]["strict-route"] is False


def test_group_order_and_secret(tmp_path, monkeypatch):
    clean, smart = _prepare_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "get_os", lambda: "linux")
    assert config.generate_smart_config() is True

    assert config.get_proxy_groups_order() == ["PROXY", "CHOICE"]
    assert config.get_api_secret() == "testsecret"


def test_get_api_secret_default(tmp_path, monkeypatch):
    clean = tmp_path / "config.yaml"
    smart = tmp_path / "smart-config.yaml"
    clean.write_text("proxy-groups: []\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_CLEAN", clean)
    monkeypatch.setattr(config, "CONFIG_SMART", smart)
    assert config.get_api_secret() == "varekai"
