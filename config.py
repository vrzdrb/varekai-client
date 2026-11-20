"""
Работа с YAML конфигами
"""

from ruamel.yaml import YAML

from utils import CONFIG_CLEAN, CONFIG_SMART, get_os

# Запасной URL проверки задержки, если в профиле его нет.
DEFAULT_DELAY_URL = "http://cp.cloudflare.com/generate_204"


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


def generate_smart_config(force_stack=None):
    """Генерирует smart-config.yaml из config.yaml.
    Смарт-стратегии ВСЕГДА включены.
    Для Windows: strict-route: false.
    force_stack — принудительно установить tun.stack (например, 'gvisor'
    при отсутствии wintun.dll)."""
    if not CONFIG_CLEAN.exists():
        return False
    try:
        config = load_config_rt(CONFIG_CLEAN)

        if get_os() == "windows":
            tun = config.get("tun")
            if isinstance(tun, dict):
                tun["strict-route"] = False
                if force_stack:
                    tun["stack"] = force_stack

        # Локальный дашборд из подписки не нужен: без external-ui-url
        # ядро не будет качать zashboard и подобные UI при каждом старте.
        for key in ("external-ui", "external-ui-name", "external-ui-url"):
            config.pop(key, None)

        # Лог-окно лаунчера показывает именно ядро — Info нужен всегда,
        # независимо от log-level в профиле подписки.
        config["log-level"] = "info"

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

        # Пользовательские правила маршрутизации: единый блок ПЕРЕД
        # провайдерскими, порядок = порядок в user-rules.yaml (= номера в UI).
        from user_routing import build_rule_line, inject_user_rules, load_user_rules

        user_rules = load_user_rules()
        if user_rules and "rules" in config and isinstance(config["rules"], list):
            lines = [build_rule_line(r) for r in user_rules if isinstance(r, dict)]
            config["rules"] = inject_user_rules(config["rules"], lines)

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


def get_delay_test_url() -> str:
    """URL проверки задержки. Приоритет — адрес штатного health-check
    из профиля (url-test/smart-группа, затем proxy-providers), чтобы
    ручной тест шёл тем же маршрутом, что и автоматический.

    Живое значение testUrl из /proxies точнее этого — его читает
    tui_app._run_delay_test; данная функция — fallback на случай,
    когда ядро ещё не отдало /proxies.
    """
    config_path = CONFIG_SMART if CONFIG_SMART.exists() else CONFIG_CLEAN
    if not config_path.exists():
        return DEFAULT_DELAY_URL
    try:
        cfg = load_config_rt(config_path)
        for group in cfg.get("proxy-groups") or []:
            if isinstance(group, dict) and group.get("url"):
                return str(group["url"])
        for prov in (cfg.get("proxy-providers") or {}).values():
            if isinstance(prov, dict):
                hc = prov.get("health-check") or {}
                if isinstance(hc, dict) and hc.get("url"):
                    return str(hc["url"])
    except Exception:
        pass
    return DEFAULT_DELAY_URL
