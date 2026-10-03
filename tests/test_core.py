import gzip
import os
from pathlib import Path

import pytest

pytest.importorskip("requests")
pytest.importorskip("ruamel.yaml")

import core
import utils


@pytest.fixture
def core_env(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "get_os", lambda: "linux")
    monkeypatch.setattr(core, "get_arch", lambda: "amd64")
    monkeypatch.setattr(core, "check_avx2_support", lambda: False)
    monkeypatch.setattr(core, "get_script_dir", lambda: tmp_path)
    monkeypatch.setattr(core, "ARCHIVES_DIR", tmp_path / "archives")
    monkeypatch.setattr(core, "CORE_VERSION_FILE", tmp_path / "core-version.txt")
    monkeypatch.setattr(core, "CORE_BINARY", str(tmp_path / "prizrak-core"))
    (tmp_path / "archives").mkdir()
    return tmp_path


def _make_gz_archive(path: Path, payload: bytes = b"binary-data"):
    with gzip.open(path, "wb") as f:
        f.write(payload)


def test_build_core_asset_name(core_env, monkeypatch):
    assert core.build_core_asset_name("v1.2.3") == "prizrak-core-linux-amd64-v1-v1.2.3.gz"
    monkeypatch.setattr(core, "check_avx2_support", lambda: True)
    assert core.build_core_asset_name("v1.2.3") == "prizrak-core-linux-amd64-v3-v1.2.3.gz"


def test_tag_from_archive_and_find(core_env):
    archives = core_env / "archives"
    arch = archives / "prizrak-core-linux-amd64-v1.2.3.gz"
    _make_gz_archive(arch)

    assert core.tag_from_archive(arch) == "v1.2.3"
    assert core.find_archived_archive("v1.2.3") == arch
    assert core.find_archived_archive("v9.9.9") is None


def test_list_core_archives_sorted(core_env):
    archives = core_env / "archives"
    a1 = archives / "prizrak-core-linux-amd64-v1.0.0.gz"
    a2 = archives / "prizrak-core-linux-amd64-v1.1.0.gz"
    _make_gz_archive(a1)
    _make_gz_archive(a2)
    os.utime(a1, (1000000000, 1000000000))
    os.utime(a2, (1000000100, 1000000100))

    listed = core.list_core_archives()
    assert [a.tag for a in listed] == ["v1.1.0", "v1.0.0"]


def test_install_from_archive_atomic_and_version(core_env):
    archives = core_env / "archives"
    arch = archives / "prizrak-core-linux-amd64-v2.0.0.gz"
    _make_gz_archive(arch, b"new-core-binary")

    ok, err = core._install_from_archive(arch)
    assert ok, err

    binary = core_env / "prizrak-core"
    assert binary.read_bytes() == b"new-core-binary"
    assert os.access(binary, os.X_OK)
    assert not (core_env / "prizrak-core.new").exists()


def test_rollback_to_tag(core_env):
    archives = core_env / "archives"
    arch = archives / "prizrak-core-linux-amd64-v1.5.0.gz"
    _make_gz_archive(arch, b"old-core")

    ok, msg = core.rollback_to_tag("v1.5.0")
    assert ok, msg
    assert (core_env / "prizrak-core").read_bytes() == b"old-core"
    assert core.get_current_version() == "v1.5.0"


def test_update_core_refuses_while_running(core_env, monkeypatch):
    monkeypatch.setattr(core, "get_core_pid", lambda: "1234")
    status, msg = core.update_core()
    assert status == 2
    assert msg == utils.t("core_running_update")


def test_validate_url():
    assert core.validate_url("https://example.com/sub")[0] is True
    assert core.validate_url("http://example.com")[0] is True
    assert core.validate_url("")[0] is False
    assert core.validate_url("ftp://example.com")[0] is False
    assert core.validate_url("not-a-url")[0] is False


def test_find_asset_for_platform(core_env, monkeypatch):
    assets = [
        {"name": "prizrak-core-linux-amd64-v1-v1.0.0.gz"},
        {"name": "prizrak-core-linux-amd64-v3-v1.0.0.gz"},
        {"name": "prizrak-core-linux-amd64-compatible-v1.0.0.gz"},
        {"name": "prizrak-core-windows-amd64-v1-v1.0.0.zip"},
        {"name": "prizrak-core-linux-amd64-v1-v1.0.0.deb"},
    ]
    monkeypatch.setattr(core, "check_avx2_support", lambda: True)
    picked = core.find_asset_for_platform(assets)
    assert picked["name"] == "prizrak-core-linux-amd64-v3-v1.0.0.gz"

    monkeypatch.setattr(core, "check_avx2_support", lambda: False)
    picked = core.find_asset_for_platform(assets)
    assert picked["name"] == "prizrak-core-linux-amd64-v1-v1.0.0.gz"
