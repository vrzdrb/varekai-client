"""
Хранение и интеграция пользовательских правил маршрутизации.
Правила хранятся в user-rules.yaml и встраиваются в smart-config.yaml
при генерации: DIRECT — до провайдерских правил, PROXY — после них,
но до MATCH.
"""
from pathlib import Path

from ruamel.yaml import YAML

from utils import get_script_dir, t

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
    Возвращает: 'DOMAIN-SUFFIX,example.com,DIRECT' и т.п."""
    rtype = rule.get("type", "")
    target = rule.get("target", "")
    proxy = rule.get("proxy", "DIRECT")
    return f"{rtype},{target},{proxy}"


def format_ip_rule(target: str) -> str:
    """Приводит IP-адрес или подсеть к формату IP-CIDR mihomo.
    Одиночный адрес 192.168.1.1 -> 192.168.1.1/32.
    Подсеть 192.168.1.0/24 остаётся как есть."""
    target = target.strip()
    if "/" in target:
        return target
    return f"{target}/32"


def format_process_rule(target: str) -> str:
    """Приводит имя процесса к формату PROCESS-NAME-REGEX.
    Оборачивает в (?i:...) для нечувствительности к регистру."""
    target = target.strip()
    # Убираем расширение .exe если пользователь его добавил
    if target.lower().endswith(".exe"):
        target = target[:-4]
    # Экранируем точки в имени процесса
    escaped = target.replace(".", r"\.")
    return f"(?i:{escaped})"


def add_rule(rule_type: str, target: str, proxy: str) -> dict:
    """Создаёт и сохраняет новое правило. Возвращает rule- dict."""
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
    """Удаляет правило по индексу."""
    rules = load_user_rules()
    if 0 <= index < len(rules):
        rules.pop(index)
        return save_user_rules(rules)
    return False


def clear_rules() -> bool:
    """Удаляет все пользовательские правила."""
    return save_user_rules([])


def inject_into_config(config_lines: list, direct_rules: list, proxy_rules: list) -> list:
    """Вставляет пользовательские правила в массив rules конфига.
    direct_rules — строки 'TYPE,target,DIRECT' (в начало, до провайдерских).
    proxy_rules — строки 'TYPE,target,PROXY' (перед MATCH, после провайдерских).
    Возвращает новый список строк rules."""
    if not direct_rules and not proxy_rules:
        return config_lines

    # Разделяем: провайдерские правила (всё кроме MATCH) и финальный MATCH
    provider_lines = []
    match_lines = []
    for line in config_lines:
        stripped = line.strip()
        if stripped.startswith("MATCH,") or stripped == "MATCH":
            match_lines.append(line)
        else:
            provider_lines.append(line)

    result = []
    # 1. Правила DIRECT пользователя (до провайдерских)
    result.extend(direct_rules)
    # 2. Провайдерские правила
    result.extend(provider_lines)
    # 3. Правила PROXY пользователя (после провайдерских, до MATCH)
    result.extend(proxy_rules)
    # 4. MATCH
    result.extend(match_lines)
    return result
