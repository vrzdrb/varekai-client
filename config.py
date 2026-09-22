from ruamel.yaml import YAML
from utils import print_success, print_error, get_os
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
    Всегда (для ПК): strict-route: false на Windows (firewall rules
    блокируют DoH-трафик ядра, ломая DIRECT).
    При включённых смарт-стратегиях: группы url-test/load-balance → type: smart
    + strategy: sticky-sessions, tolerance удаляется.
    При выключенных — копия конфига с тем же TUN-оверрайдом."""
    if not CONFIG_CLEAN.exists():
        print_error("Чистый конфиг (config.yaml) не найден")
        return False

    try:
        settings = load_settings()
        config = load_config_rt(CONFIG_CLEAN)

        # Windows-specific: strict-route добавляет firewall rules,
        # режущие исходящий DNS-трафик самого ядра (DoH к nameserver'ам).
        # На Linux strict-route работает через fwmark и своего трафика не трогает.
        if get_os() == "windows":
            tun = config.get("tun")
            if isinstance(tun, dict):
                tun["strict-route"] = False

        if settings.get("smart_enabled", True):
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

        # Постобработка пустых строк вокруг strategy: sticky-sessions
        with open(CONFIG_SMART, "r", encoding="utf-8") as f:
            lines = f.readlines()

        cleaned = []
        i = 0
        while i < len(lines):
            line = lines[i]
            # Убираем пустую строку перед strategy:
            if line.strip() == "" and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith("strategy:"):
                    i += 1
                    continue
            cleaned.append(line)
            # Добавляем пустую строку после strategy: sticky-sessions
            if "strategy: sticky-sessions" in line:
                if i + 1 >= len(lines) or (
                    lines[i + 1].strip() != ""
                    and not lines[i + 1].strip().startswith("- name:")
                ):
                    cleaned.append("\n")
            i += 1

        with open(CONFIG_SMART, "w", encoding="utf-8") as f:
            f.writelines(cleaned)

        print_success(f"Сгенерирован {CONFIG_SMART}")
        return True
    except Exception as e:
        print_error(f"Ошибка генерации smart-config: {e}")
        return False
