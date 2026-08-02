from typing import Dict, Any

SETTINGS_FILE = "settings.json"
MENU_BUILDER_FILE = "menu_builder.json"

def get_settings(load_json_fn) -> Dict[str, Any]:
    settings = load_json_fn(SETTINGS_FILE)
    if not isinstance(settings, dict):
        return {}
    return settings

def update_settings(save_json_fn, load_json_fn, updates: Dict[str, Any]):
    settings = get_settings(load_json_fn)
    settings.update(updates)
    save_json_fn(SETTINGS_FILE, settings)

def get_menu_config(load_json_fn) -> Dict[str, Dict[str, Any]]:
    menu = load_json_fn(MENU_BUILDER_FILE)
    if not isinstance(menu, dict):
        return {}
    return menu

def update_menu_item(save_json_fn, load_json_fn, key: str, updates: Dict[str, Any]):
    menu = get_menu_config(load_json_fn)
    if key in menu:
        menu[key].update(updates)
        save_json_fn(MENU_BUILDER_FILE, menu)
