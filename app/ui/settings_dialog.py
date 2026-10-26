"""App settings: scan interval, debounce, autostart, global DNS"""
from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QSlider,
                               QSpinBox, QVBoxLayout)

from .. import autostart
from ..core.ip_utils import valid_ipv4

_IPV4_RX = QRegularExpressionValidator(QRegularExpression(r"^(?:\d{1,3}\.){3}\d{1,3}$"))


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

        # global DNS
        box = QGroupBox("全局 DNS（地址可 DHCP、DNS 可静态：未自定义 DNS 的网卡组默认使用）")
        gform = QFormLayout(box)
        gform.setSpacing(16)
        gform.setHorizontalSpacing(16)
        self.chk_global_dns = QCheckBox("启用全局 DNS")
        self.chk_global_dns.toggled.connect(self._toggle_global_dns)
        gform.addRow("", self.chk_global_dns)
        self.ed_gdns1 = QLineEdit()
        self.ed_gdns1.setValidator(_IPV4_RX)
        self.ed_gdns1.setPlaceholderText("223.5.5.5")
        self.ed_gdns2 = QLineEdit()
        self.ed_gdns2.setValidator(_IPV4_RX)
        self.ed_gdns2.setPlaceholderText("114.114.114.114（可选）")
        gform.addRow("全局 DNS1", self.ed_gdns1)
        gform.addRow("全局 DNS2", self.ed_gdns2)
        root.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _toggle_global_dns(self, on):
        self.ed_gdns1.setEnabled(on)
        self.ed_gdns2.setEnabled(on)

    def _load(self):
        s = self._config.settings
        self.sl_interval.setValue(int(s.get("scan_interval", 30)))
        self.sp_debounce.setValue(int(s.get("debounce", 2)))
        self.chk_autostart.setChecked(autostart.is_enabled())
        self.chk_global_dns.setChecked(bool(s.get("global_dns_enabled")))
        self.ed_gdns1.setText(s.get("global_dns1", ""))
        self.ed_gdns2.setText(s.get("global_dns2", ""))
        self._toggle_global_dns(self.chk_global_dns.isChecked())

    def _on_accept(self):
        s = self._config.settings
        s["scan_interval"] = int(self.sl_interval.value())
        s["debounce"] = int(self.sp_debounce.value())
        s["global_dns_enabled"] = self.chk_global_dns.isChecked()
        s["global_dns1"] = self.ed_gdns1.text().strip()
        s["global_dns2"] = self.ed_gdns2.text().strip()
        if s["global_dns_enabled"] and not valid_ipv4(s["global_dns1"]):
            self.ed_gdns1.setFocus()
            return  # keep dialog open; DNS1 required when enabled
        try:
            autostart.set_enabled(self.chk_autostart.isChecked())
        except OSError as exc:
            self.chk_autostart.setToolTip(str(exc))
        self._config.save()
        self.accept()
