"""NIC group editor: multiple member MACs sharing one IP configuration"""
from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from ..core.ip_utils import valid_ipv4, mask_to_prefix
from ..core.nic_info import get_adapters
from ..storage import format_mac, normalize_mac
from .async_worker import AsyncDialogMixin, AsyncWorker

_IPV4_RX = QRegularExpressionValidator(QRegularExpression(r"^(?:\d{1,3}\.){3}\d{1,3}$"))


class NicGroupDialog(AsyncDialogMixin, QDialog):
    """Create or edit a NIC group (one config shared by several member NICs)"""

    def __init__(self, parent, group=None):
        super().__init__(parent)
        self.setWindowTitle("编辑网卡组" if group else "添加网卡组")
        self.setMinimumWidth(520)
        self._worker = None
        self._adapters = []
        self._group = dict(group or {"label": "", "macs": [], "dhcp": True,
                                     "ip": "", "mask": "", "gateway": "",
                                     "dns1": "", "dns2": ""})
        self._build_ui()
        self._fill()
        self._load_adapters_async()

    # ---------- UI ----------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(16)
        form.setHorizontalSpacing(16)

        self.ed_label = QLineEdit()
        self.ed_label.setPlaceholderText("组名，例如：有线网卡组 / 办公室网口")
        form.addRow("组名", self.ed_label)
        root.addLayout(form)

        # members group box
        box = QGroupBox("组成员网卡（组内任一张已连接且配置一致即视为匹配）")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(12)

        self.list_macs = QListWidget()
        self.list_macs.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        box_layout.addWidget(self.list_macs)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.cb_adapter = QComboBox()
        self.cb_adapter.setEnabled(False)
        add_row.addWidget(self.cb_adapter, 1)
        btn_add_live = QPushButton("添加")
        btn_add_live.clicked.connect(self._add_from_combo)
        add_row.addWidget(btn_add_live)
        box_layout.addLayout(add_row)

        manual_row = QHBoxLayout()
        manual_row.setSpacing(8)
        self.ed_mac = QLineEdit()
        self.ed_mac.setPlaceholderText("手动输入 MAC：AA-BB-CC-DD-EE-FF")
        self.ed_mac.textChanged.connect(lambda: self.ed_mac.setText(
            self.ed_mac.text().upper().replace(":", "-").replace(".", "-")))
        manual_row.addWidget(self.ed_mac, 1)
        btn_add_manual = QPushButton("添加")
        btn_add_manual.clicked.connect(self._add_manual)
        manual_row.addWidget(btn_add_manual)
        box_layout.addLayout(manual_row)

        btn_del = QPushButton("移除所选成员")
        btn_del.clicked.connect(self._remove_selected)
        box_layout.addWidget(btn_del)
        root.addWidget(box, 1)

        # ip config
        form2 = QFormLayout()
        form2.setSpacing(16)
        form2.setHorizontalSpacing(16)
        self.chk_dhcp = QCheckBox("使用 DHCP 自动获取")
        self.chk_dhcp.toggled.connect(self._toggle_static)
        form2.addRow("", self.chk_dhcp)
        self.ed_ip = self._ip_field("192.168.1.100")
        self.ed_mask = self._ip_field("255.255.255.0")
        self.ed_gw = self._ip_field("192.168.1.1")
        self.ed_dns1 = self._ip_field("223.5.5.5")
        self.ed_dns2 = self._ip_field("114.114.114.114")
        form2.addRow("IP 地址", self.ed_ip)
        form2.addRow("子网掩码", self.ed_mask)
        form2.addRow("网关", self.ed_gw)
        form2.addRow("DNS1", self.ed_dns1)
        form2.addRow("DNS2", self.ed_dns2)
        root.addLayout(form2)

        self.lb_warn = QLabel("")
        self.lb_warn.setWordWrap(True)
        root.addWidget(self.lb_warn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _ip_field(self, placeholder):
        ed = QLineEdit()
        ed.setValidator(_IPV4_RX)
        ed.setPlaceholderText(placeholder)
        return ed

    # ---------- members ----------

    def _fill(self):
        g = self._group
        self.ed_label.setText(g.get("label", ""))
        self.chk_dhcp.setChecked(bool(g.get("dhcp")))
        self.ed_ip.setText(g.get("ip", ""))
        self.ed_mask.setText(g.get("mask", ""))
        self.ed_gw.setText(g.get("gateway", ""))
        self.ed_dns1.setText(g.get("dns1", ""))
        self.ed_dns2.setText(g.get("dns2", ""))
        self._toggle_static(self.chk_dhcp.isChecked())
        for mac in g.get("macs", []):
            self._append_mac(mac)

    def _append_mac(self, mac):
        m = normalize_mac(mac)
        if not m or len(m) != 12:
            return False
        if any(self.list_macs.item(i).data(Qt.ItemDataRole.UserRole) == m
               for i in range(self.list_macs.count())):
            return True  # already in the group
        item = QListWidgetItem(format_mac(m))
        item.setData(Qt.ItemDataRole.UserRole, m)
        self.list_macs.addItem(item)
        return True

    def _add_from_combo(self):
        ad = self.cb_adapter.currentData()
        if ad:
            self._append_mac(ad["mac"])

    def _add_manual(self):
        if not self._append_mac(self.ed_mac.text()):
            self.lb_warn.setText("MAC 地址无效（需要 12 位十六进制）")
            return
        self.ed_mac.clear()
        self.lb_warn.setText("")

    def _remove_selected(self):
        for item in self.list_macs.selectedItems():
            self.list_macs.takeItem(self.list_macs.row(item))

    def _load_adapters_async(self):
        self.cb_adapter.addItem("正在读取网卡列表…", None)
        self._worker = AsyncWorker(get_adapters, parent=self)
        self._worker.done.connect(self._on_adapters_loaded)
        self._worker.failed.connect(self._on_adapters_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_adapters_loaded(self, adapters):
        self._worker = None
        self._adapters = adapters or []
        self.cb_adapter.clear()
        self.cb_adapter.setEnabled(True)
        for ad in self._adapters:
            conn = "已连接" if ad.get("status", "").lower() == "up" else ""
            text = f"{ad['name']}  [{format_mac(ad['mac'])}]  {conn}".strip()
            self.cb_adapter.addItem(text, ad)

    def _on_adapters_failed(self, message):
        self._worker = None
        self.cb_adapter.clear()
        self.cb_adapter.addItem(f"(读取失败：{message}，请手动输入 MAC)", None)

    # ---------- ip config ----------

    def _toggle_static(self, dhcp):
        for w in (self.ed_ip, self.ed_mask, self.ed_gw, self.ed_dns1, self.ed_dns2):
            w.setEnabled(not dhcp)

    def _on_accept(self):
        g = self._group
        label = self.ed_label.text().strip()
        macs = [self.list_macs.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.list_macs.count())]
        if not macs:
            self.lb_warn.setText("网卡组至少需要一张成员网卡")
            return
        g["label"] = label or format_mac(macs[0])
        g["macs"] = macs
        g["dhcp"] = self.chk_dhcp.isChecked()
        g["ip"] = self.ed_ip.text().strip()
        g["mask"] = self.ed_mask.text().strip()
        g["gateway"] = self.ed_gw.text().strip()
        g["dns1"] = self.ed_dns1.text().strip()
        g["dns2"] = self.ed_dns2.text().strip()
        if not g["dhcp"]:
            if not valid_ipv4(g["ip"]):
                self.lb_warn.setText("IP 地址无效")
                return
            if mask_to_prefix(g["mask"]) == 0:
                self.lb_warn.setText("子网掩码无效")
                return
            if g["gateway"] and not valid_ipv4(g["gateway"]):
                self.lb_warn.setText("网关无效")
                return
            if g["dns1"] and not valid_ipv4(g["dns1"]):
                self.lb_warn.setText("DNS1 无效")
                return
            if g["dns2"]:
                if not valid_ipv4(g["dns2"]):
                    self.lb_warn.setText("DNS2 无效")
                    return
                if not g["dns1"]:
                    self.lb_warn.setText("填写 DNS2 前必须先填写 DNS1")
                    return
        elif g["ip"] or g["mask"]:
            g["ip"] = g["mask"] = g["gateway"] = g["dns1"] = g["dns2"] = ""
        self.accept()

    def result_group(self):
        return self._group
