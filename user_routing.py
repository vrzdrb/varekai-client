"""
Хранение и интеграция пользовательских правил маршрутизации.

Правила хранятся в user-rules.yaml и встраиваются в smart-config.yaml
при генерации ЕДИНЫМ блоком перед провайдерскими правилами, до MATCH.
Порядок внутри блока = порядок в user-rules.yaml = номера в окне
маршрутизации: пользовательские правила перекрывают провайдерские.
"""

import ipaddress
from pathlib import Path

from ruamel.yaml import YAML

from utils import get_script_dir

USER_RULES_FILE = "user-rules.yaml"


def _rules_path() -> Path:
    return get_script_dir() / USER_RULES_FILE


def load_user_rules() -> list:
    """Загружает пользовательские правила из user-rules.yaml."""
    path = _rules_path()
    if not path.exists():
        return []
    try:
        y = YAML()
        with open(path, "r", encoding="utf-8") as f:
            data = y.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("rules", [])
    except Exception:
        pass
    return []


def save_user_rules(rules: list) -> bool:
    """Сохраняет пользовательские правила в user-rules.yaml."""
    path = _rules_path()
    try:
        y = YAML()
        y.indent(mapping=2, sequence=4, offset=2)
        with open(path, "w", encoding="utf-8") as f:
            y.dump({"rules": rules}, f)
        return True
    except Exception:
        return False


def build_rule_line(rule: dict) -> str:
    """Преобразует правило в строку формата mihomo.

    rule: {type, target, proxy}
    Возвращает: 'DOMAIN-SUFFIX,example.com,DIRECT' и т.п.
    """
    rtype = str(rule.get("type", "")).strip()
    target = str(rule.get("target", "")).strip()
    proxy = str(rule.get("proxy", "DIRECT")).strip()
    return f"{rtype},{target},{proxy}"


def format_ip_rule(target: str) -> str:
    """Приводит IP-адрес или подсеть к формату IP-CIDR mihomo.

    Одиночный IPv4 192.168.1.1 -> 192.168.1.1/32.
    Подсеть 192.168.1.0/24 остаётся как есть.

    IPv6 и не-IP возвращаются без изменений: раньше к ним приписывалось
    /32, что давало заведомо битое правило (2a00::1/32) и молчаливый
    отказ ядра применять конфиг.
    """
    target = target.strip()
    if "/" in target:
        return target
    try:
        if ipaddress.ip_address(target).version == 4:
            return f"{target}/32"
    except ValueError:
        pass
    return target


def format_process_rule(target: str) -> str:
    """Приводит имя процесса к формату PROCESS-NAME-REGEX.

    Оборачивает в (?i:...) для нечувствительности к регистру и
    экранирует точки, иначе '.' в regex означает «любой символ».
    """
    target = target.strip()
    # Убираем расширение .exe, если пользователь его добавил
    if target.lower().endswith(".exe"):
        target = target[:-4]
    escaped = target.replace(".", r"\.")
    return f"(?i:{escaped})"


def add_rule(rule_type: str, target: str, proxy: str) -> dict:
    """Создаёт и сохраняет новое правило. Возвращает rule-dict."""
    if rule_type == "IP-CIDR":
        target = format_ip_rule(target)
    elif rule_type == "PROCESS-NAME-REGEX":
        target = format_process_rule(target)
    rule = {"type": rule_type, "target": target, "proxy": proxy}
    rules = load_user_rules()
    rules.append(rule)
    save_user_rules(rules)
    return rule


def remove_rule(index: int) -> bool:
    """Удаляет правило по индексу (0-based). Номер в UI = index + 1."""
    rules = load_user_rules()
    if 0 <= index < len(rules):
        rules.pop(index)
        return save_user_rules(rules)
    return False


def clear_rules() -> bool:
    """Удаляет все пользовательские правила."""
    return save_user_rules([])


def inject_user_rules(config_lines: list, rule_lines: list) -> list:
    """Вставляет пользовательские правила ЕДИНЫМ блоком перед
    провайдерскими. Порядок внутри блока = порядок в user-rules.yaml
    = номера в списке окна маршрутизации. MATCH остаётся последним."""
    if not rule_lines:
        return list(config_lines)
    provider_lines, match_lines = [], []
    for line in config_lines:
        stripped = str(line).strip()
        if stripped.startswith("MATCH,") or stripped == "MATCH":
            match_lines.append(line)
        else:
            provider_lines.append(line)
    return list(rule_lines) + provider_lines + match_lines


def inject_into_config(config_lines: list, direct_rules: list, proxy_rules: list) -> list:
    """Совместимая обёртка: сигнатура сохранена для существующих вызовов
    и тестов. Оба блока теперь идут ДО провайдерских правил —
    пользовательские перекрывают провайдерские, а не наоборот."""
    return inject_user_rules(config_lines, list(direct_rules) + list(proxy_rules))
