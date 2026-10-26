"""App settings: scan interval, debounce, autostart"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QSlider, QSpinBox, QVBoxLayout)

from .. import autostart


class SettingsDialog(QDialog):
    def __init__(self, parent, config):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(420)
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(16)
        form.setHorizontalSpacing(16)

        row = QHBoxLayout()
        row.setSpacing(16)
        self.sl_interval = QSlider(Qt.Orientation.Horizontal)
        self.sl_interval.setRange(10, 300)
        self.sl_interval.setSingleStep(5)
        self.lb_interval = QLabel("")
        self.sl_interval.valueChanged.connect(
            lambda v: self.lb_interval.setText(f"{v} 秒"))
        row.addWidget(self.sl_interval, 1)
        row.addWidget(self.lb_interval)
        form.addRow("定位扫描间隔", row)

        self.sp_debounce = QSpinBox()
        self.sp_debounce.setRange(1, 5)
        self.sp_debounce.setToolTip("连续多少次扫描结果一致才确认位置切换，可避免在边界区域来回抖动")
        form.addRow("位置确认次数", self.sp_debounce)

        self.chk_autostart = QCheckBox("开机自动启动（写入当前用户注册表 Run 项）")
        form.addRow("", self.chk_autostart)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load(self):
        s = self._config.settings
        self.sl_interval.setValue(int(s.get("scan_interval", 30)))
        self.sp_debounce.setValue(int(s.get("debounce", 2)))
        self.chk_autostart.setChecked(autostart.is_enabled())

    def _on_accept(self):
        s = self._config.settings
        s["scan_interval"] = int(self.sl_interval.value())
        s["debounce"] = int(self.sp_debounce.value())
        try:
            autostart.set_enabled(self.chk_autostart.isChecked())
        except OSError as exc:
            self.chk_autostart.setToolTip(str(exc))
        self._config.save()
        self.accept()
