"""
Работа с YAML конфигами
"""
from ruamel.yaml import YAML
from utils import CONFIG_CLEAN, CONFIG_SMART, get_os


def make_yaml():
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
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

        # Постобработка: пустая строка после strategy: sticky-sessions
        with open(CONFIG_SMART, "r", encoding="utf-8") as f:
            lines = f.readlines()

        cleaned = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Убираем пустую строку ПЕРЕД strategy:
            if line.strip() == "" and i + 1 < len(lines):
                if lines[i + 1].strip().startswith("strategy:"):
                    i += 1
                    continue
            cleaned.append(line)
            # Добавляем пустую строку ПОСЛЕ strategy: sticky-sessions
            if "strategy: sticky-sessions" in line:
                if i + 1 >= len(lines) or (
                    lines[i + 1].strip() != ""
                    and not lines[i + 1].strip().startswith("- name:")
                ):
                    cleaned.append("\n")
            i += 1

        with open(CONFIG_SMART, "w", encoding="utf-8") as f:
            f.writelines(cleaned)

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
