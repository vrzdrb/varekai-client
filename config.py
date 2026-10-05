"""
Работа с YAML конфигами
"""
from ruamel.yaml import YAML

import re

from utils import CONFIG_CLEAN, CONFIG_SMART, get_os, get_script_dir


def make_yaml():
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    # Элементы списков с отступом под ключом (стандартный стиль clash-конфигов):
    #   fake-ip-filter:
    #     - '+.kimi.ai'
    # По умолчанию ruamel ставит '-' на уровне ключа — не валится парсер,
    # но ломает читаемость и сбивает с толку diff'ы.
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load_config_rt(path):
    y = make_yaml()
    with open(path, "r", encoding="utf-8") as f:
        return y.load(f)


def dump_config_rt(data, path):
    y = make_yaml()
    with open(path, "w", encoding="utf-8") as f:
        y.dump(data, f)


def generate_smart_config():
    """Генерирует smart-config.yaml из config.yaml.
    Смарт-стратегии ВСЕГДА включены.
    Для Windows: strict-route: false."""
    if not CONFIG_CLEAN.exists():
        return False
    try:
        config = load_config_rt(CONFIG_CLEAN)

        if get_os() == "windows":
            tun = config.get("tun")
            if isinstance(tun, dict):
                tun["strict-route"] = False

        # Абсолютные пути rule-providers: ядро под Linux стартует через
        # pkexec от root, и его рабочий каталог становится /root — относительные
        # "./unified/..." оседали в /root/unified вместо папки приложения.
        providers = config.get("rule-providers")
        if isinstance(providers, dict):
            app_dir = get_script_dir()
            for pdata in providers.values():
                if not isinstance(pdata, dict):
                    continue
                raw = str(pdata.get("path") or "")
                # Абсолютные пути пропускаем: ведущий '/' (Linux/macOS)
                # или буква диска 'C:\' / 'C:/' (Windows)
                is_absolute = raw.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", raw)
                if raw and not is_absolute:
                    rel = raw[2:] if raw.startswith("./") else raw
                    pdata["path"] = str(app_dir / rel)

        # Смарт-стратегии ВСЕГДА включены
        if "proxy-groups" in config and isinstance(config["proxy-groups"], list):
            for group in config["proxy-groups"]:
                if not isinstance(group, dict):
                    continue
                group_type = str(group.get("type", "")).lower()
                if group_type in ("url-test", "load-balance"):
                    group["type"] = "smart"
                    group["strategy"] = "sticky-sessions"
                    if "tolerance" in group:
                        del group["tolerance"]

        dump_config_rt(config, CONFIG_SMART)
        return True
    except Exception:
        return False


def get_proxy_groups_order():
    """Возвращает имена proxy-groups в порядке следования из конфига."""
    config_path = CONFIG_SMART if CONFIG_SMART.exists() else CONFIG_CLEAN
    if not config_path.exists():
        return []
    try:
        config = load_config_rt(config_path)
        groups = config.get("proxy-groups")
        if not isinstance(groups, list):
            return []
        return [
            g["name"] for g in groups
            if isinstance(g, dict) and g.get("name")
        ]
    except Exception:
        return []


def get_api_secret():
    """Читает секрет для REST API. Приоритет: smart-config.yaml -> config.yaml"""
    config_path = CONFIG_SMART if CONFIG_SMART.exists() else CONFIG_CLEAN
    if not config_path.exists():
        return "varekai"
    try:
        config = load_config_rt(config_path)
        return config.get("secret", "varekai")
    except Exception:
        return "varekai"

