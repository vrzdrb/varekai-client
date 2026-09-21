from ruamel.yaml import YAML
from utils import print_success, print_error
from settings import load_settings
from constants import CONFIG_CLEAN, CONFIG_SMART
from i18n import t


def make_yaml():
    """Round-trip YAML: сохраняет комментарии, якоря и форматирование"""
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # не переносить длинные строки
    return y

def load_config_rt(path):
    """Читает конфиг с сохранением структуры (якоря, комментарии)"""
    y = make_yaml()
    with open(path, "r", encoding="utf-8") as f:
        return y.load(f)

def dump_config_rt(data, path):
    """Пишет конфиг, сохраняя якоря и комментарии"""
    y = make_yaml()
    with open(path, "w", encoding="utf-8") as f:
        y.dump(data, f)

def generate_smart_config():
    """Генерирует smart-config.yaml из config.yaml.
    При включённых смарт-стратегиях: группы url-test/load-balance становятся
    type: smart (uselightgbm: false, collectdata: true, strategy: sticky-sessions),
    tolerance удаляется, глобально smart-collector-size: 100.
    При выключенных — чистая копия конфига."""
    if not CONFIG_CLEAN.exists():
        print_error(t("cfg_no_clean"))
        return False

    try:
        settings = load_settings()
        config = load_config_rt(CONFIG_CLEAN)

        if settings.get("smart_enabled", True):
            # Глобально: лимит коллектора (МБ)
            if "profile" not in config or config["profile"] is None:
                config["profile"] = {}
            config["profile"]["smart-collector-size"] = 100

            # Модифицируем существующие группы, новых не создаём
            if "proxy-groups" in config and isinstance(config["proxy-groups"], list):
                for group in config["proxy-groups"]:
                    if not isinstance(group, dict):
                        continue
                    group_type = str(group.get("type", "")).lower()
                    if group_type in ("url-test", "load-balance"):
                        group["type"] = "smart"
                        group["uselightgbm"] = False
                        group["collectdata"] = True
                        group["strategy"] = "sticky-sessions"
                        # tolerance — понятие из url-test, в smart не нужен
                        if "tolerance" in group:
                            del group["tolerance"]

        dump_config_rt(config, CONFIG_SMART)
        print_success(t("cfg_generated", path=CONFIG_SMART))
        return True
    except Exception as e:
        print_error(t("cfg_error", error=e))
        return False
