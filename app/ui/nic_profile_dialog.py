"""NIC profile editor (per geo point)"""
from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLabel, QLineEdit, QVBoxLayout)

from ..core.nic_info import get_adapters
from ..core.ip_utils import valid_ipv4, mask_to_prefix
from ..storage import format_mac, normalize_mac

_IPV4_RX = QRegularExpressionValidator(QRegularExpression(r"^(?:\d{1,3}\.){3}\d{1,3}$"))


class NicProfileDialog(QDialog):
    """Create or edit a NIC profile entry"""

    def __init__(self, parent, profile=None, adapters=None):
        super().__init__(parent)
        self.setWindowTitle("编辑网卡配置" if profile else "添加网卡配置")
        self.setMinimumWidth(460)
        self._adapters = adapters or []
        self._profile = dict(profile or {"mac": "", "label": "", "dhcp": True,
                                         "ip": "", "mask": "", "gateway": "",
                                         "dns1": "", "dns2": ""})
        self._build_ui()
        self._fill()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(16)
        form.setHorizontalSpacing(16)

        self.cb_adapter = QComboBox()
        self.cb_adapter.addItem("(手动输入)", None)
        for ad in self._adapters:
            text = f"{ad['name']}  [{format_mac(ad['mac'])}]  {'已连接' if ad.get('_conn') else ''}"
            self.cb_adapter.addItem(text.strip(), ad)
        self.cb_adapter.currentIndexChanged.connect(self._on_pick_adapter)
        form.addRow("选择在位网卡", self.cb_adapter)

        self.ed_label = QLineEdit()
        self.ed_label.setPlaceholderText("备注名，例如：USB 网卡 A")
        form.addRow("备注名", self.ed_label)

        self.ed_mac = QLineEdit()
        self.ed_mac.setPlaceholderText("AA-BB-CC-DD-EE-FF")
        self.ed_mac.textChanged.connect(lambda: self.ed_mac.setText(
            self.ed_mac.text().upper().replace(":", "-").replace(".", "-")))
        form.addRow("网卡 MAC", self.ed_mac)

        self.chk_dhcp = QCheckBox("使用 DHCP 自动获取")
        self.chk_dhcp.toggled.connect(self._toggle_static)
        form.addRow("", self.chk_dhcp)

        self.ed_ip = self._ip_field("192.168.1.100")
        self.ed_mask = self._ip_field("255.255.255.0")
        self.ed_gw = self._ip_field("192.168.1.1")
        self.ed_dns1 = self._ip_field("223.5.5.5")
        self.ed_dns2 = self._ip_field("114.114.114.114")
        form.addRow("IP 地址", self.ed_ip)
        form.addRow("子网掩码", self.ed_mask)
        form.addRow("网关", self.ed_gw)
        form.addRow("DNS1", self.ed_dns1)
        form.addRow("DNS2", self.ed_dns2)
        root.addLayout(form)

        self.lb_warn = QLabel("")
        self.lb_warn.setWordWrap(True)
        root.addWidget(self.lb_warn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addSpacing(8)
        root.addWidget(buttons)

    def _ip_field(self, placeholder):
        ed = QLineEdit()
        ed.setValidator(_IPV4_RX)
        ed.setPlaceholderText(placeholder)
        return ed

    def _fill(self):
        p = self._profile
        self.ed_label.setText(p.get("label", ""))
        self.ed_mac.setText(format_mac(p.get("mac", "")))
        self.chk_dhcp.setChecked(bool(p.get("dhcp")))
        self.ed_ip.setText(p.get("ip", ""))
        self.ed_mask.setText(p.get("mask", ""))
        self.ed_gw.setText(p.get("gateway", ""))
        self.ed_dns1.setText(p.get("dns1", ""))
        self.ed_dns2.setText(p.get("dns2", ""))
        self._toggle_static(self.chk_dhcp.isChecked())

    def _on_pick_adapter(self):
        ad = self.cb_adapter.currentData()
        if not ad:
            return
        self.ed_mac.setText(format_mac(ad["mac"]))
        if not self.ed_label.text().strip():
            self.ed_label.setText(ad["name"])

    def _toggle_static(self, dhcp):
        for w in (self.ed_ip, self.ed_mask, self.ed_gw, self.ed_dns1, self.ed_dns2):
            w.setEnabled(not dhcp)

    def _on_accept(self):
        mac = normalize_mac(self.ed_mac.text())
        label = self.ed_label.text().strip()
        if len(mac) != 12:
            self.lb_warn.setText("MAC 地址无效（需要 12 位十六进制）")
            return
        p = self._profile
        p["mac"] = mac
        p["label"] = label or format_mac(mac)
        p["dhcp"] = self.chk_dhcp.isChecked()
        p["ip"] = self.ed_ip.text().strip()
        p["mask"] = self.ed_mask.text().strip()
        p["gateway"] = self.ed_gw.text().strip()
        p["dns1"] = self.ed_dns1.text().strip()
        p["dns2"] = self.ed_dns2.text().strip()
        if not p["dhcp"]:
            if not valid_ipv4(p["ip"]):
                self.lb_warn.setText("IP 地址无效")
                return
            if mask_to_prefix(p["mask"]) == 0:
                self.lb_warn.setText("子网掩码无效")
                return
            if p["gateway"] and not valid_ipv4(p["gateway"]):
                self.lb_warn.setText("网关无效")
                return
            if p["dns1"] and not valid_ipv4(p["dns1"]):
                self.lb_warn.setText("DNS1 无效")
                return
            if p["dns2"]:
                if not valid_ipv4(p["dns2"]):
                    self.lb_warn.setText("DNS2 无效")
                    return
                if not p["dns1"]:
                    self.lb_warn.setText("填写 DNS2 前必须先填写 DNS1")
                    return
        elif p["ip"] or p["mask"]:
            p["ip"] = p["mask"] = p["gateway"] = p["dns1"] = p["dns2"] = ""
        self.accept()

    def result_profile(self):
        return self._profile
