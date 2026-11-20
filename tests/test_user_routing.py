import pytest

pytest.importorskip("ruamel.yaml")

import user_routing

PROVIDER_RULES = [
    "RULE-SET,ads,REJECT",
    "RULE-SET,cn,DIRECT",
    "MATCH,PROXY",
]


def test_user_rules_go_before_provider_rules():
    user = ["DOMAIN-SUFFIX,example.com,PROXY", "DOMAIN,foo.bar,DIRECT"]
    assert user_routing.inject_user_rules(PROVIDER_RULES, user) == user + [
        "RULE-SET,ads,REJECT", "RULE-SET,cn,DIRECT", "MATCH,PROXY",
    ]


def test_user_order_is_preserved():
    user = ["DOMAIN,a.com,PROXY", "DOMAIN,b.com,DIRECT", "DOMAIN,c.com,PROXY"]
    assert user_routing.inject_user_rules(PROVIDER_RULES, user)[:3] == user


def test_match_stays_last():
    result = user_routing.inject_user_rules(PROVIDER_RULES, ["DOMAIN,a.com,PROXY"])
    assert result[-1] == "MATCH,PROXY"


def test_empty_user_rules_is_noop():
    assert user_routing.inject_user_rules(PROVIDER_RULES, []) == PROVIDER_RULES


def test_legacy_wrapper_puts_proxy_before_providers():
    result = user_routing.inject_into_config(
        PROVIDER_RULES, ["DOMAIN,a.com,DIRECT"], ["DOMAIN,b.com,PROXY"]
    )
    assert result.index("DOMAIN,b.com,PROXY") < result.index("RULE-SET,ads,REJECT")


@pytest.fixture
def tmp_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(user_routing, "_rules_path", lambda: tmp_path / "user-rules.yaml")


def test_remove_rule_by_index(tmp_rules):
    for host in ("a.com", "b.com", "c.com"):
        user_routing.add_rule("DOMAIN", host, "PROXY")
    assert user_routing.remove_rule(1) is True
    assert [r["target"] for r in user_routing.load_user_rules()] == ["a.com", "c.com"]


def test_remove_rule_out_of_range(tmp_rules):
    user_routing.add_rule("DOMAIN", "a.com", "PROXY")
    assert user_routing.remove_rule(5) is False
    assert len(user_routing.load_user_rules()) == 1


def test_ip_rule_gets_mask(tmp_rules):
    rule = user_routing.add_rule("IP-CIDR", "192.168.1.1", "DIRECT")
    assert rule["target"] == "192.168.1.1/32"
    assert user_routing.build_rule_line(rule) == "IP-CIDR,192.168.1.1/32,DIRECT"


def test_ipv6_rule_not_given_ipv4_mask():
    assert user_routing.format_ip_rule("2a00::1") == "2a00::1"
    assert user_routing.format_ip_rule("10.0.0.0/8") == "10.0.0.0/8"


def test_process_rule_escapes_dots():
    assert user_routing.format_process_rule("Telegram.exe") == "(?i:Telegram)"
    assert user_routing.format_process_rule("my.app.exe") == r"(?i:my\.app)"
