"""Config persistence for WiFi-IP-Locator"""
import copy
import json
import os
import uuid

APP_NAME = "WiFi-IP-Locator"


def _config_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


CONFIG_PATH = os.path.join(_config_dir(), "config.json")

DEFAULTS = {
    "settings": {
        "scan_interval": 30,   # seconds between wifi scans
        "debounce": 2,         # consecutive confirmations before a location switch
    },
    "points": [],
}


def normalize_mac(mac):
    """Normalize a MAC to 12 uppercase hex chars (no separators)"""
    return (mac or "").replace("-", "").replace(":", "").replace(".", "").strip().upper()


def format_mac(mac):
    """Format 12 hex chars as XX-XX-XX-XX-XX-XX for display"""
    m = normalize_mac(mac)
    return "-".join(m[i:i + 2] for i in range(0, len(m), 2)) if len(m) == 12 else (mac or "")


def new_point(name, threshold=75.0):
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "threshold": float(threshold),
        "fingerprint": [],   # [{bssid, ssid, rssi}]
        "profiles": [],      # [{mac, label, dhcp, ip, mask, gateway, dns1, dns2}]
    }


class Config:
    _instance = None

    def __init__(self):
        self._data = copy.deepcopy(DEFAULTS)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.load()
        return cls._instance

    def load(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        self._data = copy.deepcopy(DEFAULTS)
        self._data["settings"].update(data.get("settings") or {})
        self._data["points"] = data.get("points") or []

    def save(self):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    @property
    def settings(self):
        return self._data["settings"]

    @property
    def points(self):
        return self._data["points"]

    def add_point(self, point):
        self._data["points"].append(point)
        self.save()

    def remove_point(self, point_id):
        self._data["points"] = [p for p in self._data["points"] if p["id"] != point_id]
        self.save()

    def get_point(self, point_id):
        for p in self._data["points"]:
            if p["id"] == point_id:
                return p
        return None
