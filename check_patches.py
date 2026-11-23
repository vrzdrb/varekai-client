#!/usr/bin/env python3
"""Одноразовая проверка полноты правок: python3 check_patches.py"""
from pathlib import Path

# (файл, маркер, должен присутствовать)
CHECKS = [
    ("clash_api.py", "DEFAULT_DELAY_URL", True),
    ("clash_api.py", "max_connections=64", True),
    ("clash_api.py", "async def aclose", True),
    ("clash_api.py", "timeout_ms / 1000.0 + 3.0", True),
    ("clash_api.py", "max(30.0, timeout_ms / 1000.0 + 10.0)", True),
    ("clash_api.py", "async def reload_config", True),

    ("config.py", "def get_delay_test_url", True),
    ("config.py", "inject_user_rules", True),
    ("config.py", "cp.cloudflare.com/generate_204", True),

    ("user_routing.py", "def inject_user_rules", True),
    ("user_routing.py", "import ipaddress", True),

    ("tui_widgets.py", "get_group_button_colors", True),
    ("tui_widgets.py", "def _apply_button_bg", True),
    ("tui_widgets.py", "get_group_button_colors(th=th)", True),

    ("tui_app.py", "PING_CONCURRENCY", True),
    ("tui_app.py", "def _testable_nodes", True),
    ("tui_app.py", "def _probe_nodes", True),
    ("tui_app.py", "def _log_node_delay", True),
    ("tui_app.py", "_ping_busy", True),
    ("tui_app.py", "gr108", True),
    ("tui_app.py", "#3F3411", True),
    ("tui_app.py", "#392C4B", True),
    ("tui_app.py", "row._apply_button_bg()", True),
    ("tui_app.py", "get_delay_test_url", True),
    ("tui_app.py", "testUrl", True),
    ("tui_app.py", "SUB_UPDATE_CHECK", True),
    ("tui_app.py", "def _render_sub_meta", True),
    ("tui_app.py", "def _maybe_auto_update_profile", True),
    ("tui_app.py", 'id="sub_meta"', True),
    ("tui_app.py", "#sub_meta", True),

    ("tui_routing.py", "rt_menu_remove", True),
    ("tui_routing.py", "rt_remove_field", True),
    ("tui_routing.py", "def _do_remove", True),
    ("tui_routing.py", "def _apply_rules_worker", True),
    ("tui_routing.py", "reload_config", True),
    ("tui_routing.py", "border: none", True),

    ("tui_connections.py", "api.group_delay", False),   # фоновые тесты убраны
    ("tui_connections.py", "ИЗВЕСТНЫМ задержкам", True),

    ("main.py", "def request_age_key", True),
    ("main.py", "--age-key", True),

    ("utils.py", "AGE_KEY_FILE", True),
    ("utils.py", "PROFILE_META_FILE", True),
    ("utils.py", "#392C4B", True),
    ("utils.py", "#262832", True),

    ("core.py", "from sub_client import update_profile", True),
    ("pyproject.toml", "cryptography", True),
    ("pyproject.toml", "sub_client", True),

    ("tests/test_utils.py", "test_group_button_colors_fallback_untouched", True),
    ("tests/test_utils.py", '"ikigai": 0.30', True),
    ("tests/test_utils.py", "test_group_button_bg_separable_from_tech_bg", True),
    ("tests/test_user_routing.py", "def test_remove_rule_by_index", True),
    ("tests/test_sub_meta.py", "def test_pxa_and_global_mode_are_ignored", True),
    ("tests/test_sub_client.py", "def test_migration_is_bounded", True),
    ("tests/test_sub_client.py", "def test_migration_pingpong_stops", True),
    ("tests/test_age_crypto.py", "def test_roundtrip_via_age", True),
]

WORKFLOW = [".github/workflows/build-release.yml", "build-release.yml"]
WF_CHECKS = [
    ("exec sudo -E ./Varekai", True),
    ("codesign --remove-signature", True),
    ("codesign --verify", True),
    ("--deep --sign -", False),          # старая бесполезная подпись
]

fails = 0


def check(name, marker, want, text):
    global fails
    ok = (marker in text) == want
    if not ok:
        fails += 1
    tag = "OK  " if ok else "FAIL"
    verb = "есть" if want else "нет "
    print(f"{tag}  {name:34s} {verb}  {marker}")


for name, marker, want in CHECKS:
    p = Path(name)
    if not p.exists():
        print(f"FAIL  {name:34s} ---   ФАЙЛ НЕ НАЙДЕН")
        fails += 1
        continue
    check(name, marker, want, p.read_text(encoding="utf-8", errors="replace"))

wf = next((Path(p) for p in WORKFLOW if Path(p).exists()), None)
if wf is None:
    print("FAIL  build-release.yml                  ---   ФАЙЛ НЕ НАЙДЕН")
    fails += 1
else:
    print(f"\n# workflow: {wf}")
    text = wf.read_text(encoding="utf-8", errors="replace")
    for marker, want in WF_CHECKS:
        check(str(wf), marker, want, text)

print(f"\nИтого проблем: {fails}")
