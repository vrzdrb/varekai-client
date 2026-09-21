import json
from constants import SETTINGS_FILE, DEFAULT_SETTINGS

def load_settings():
    """Читает настройки ПК-оверрайдов, недостающие ключи берёт из дефолтов"""
    settings = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings.update(json.load(f))
    except Exception:
        pass
    return settings

def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
