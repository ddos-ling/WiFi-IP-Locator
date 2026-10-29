"""HKCU registry autostart toggle"""
import os
import sys

import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "WiFi-IP-Locator"


def _command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    script = os.path.abspath(sys.argv[0])
    return f'"{pythonw}" "{script}" --minimized'


def is_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except OSError:
        return False


def set_enabled(enable):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enable:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except OSError:
                pass
