"""Mismatch dialog: prompt user to apply a NIC profile"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox,
                               QLabel, QRadioButton, QVBoxLayout)

from ..core import ip_manager
from ..storage import format_mac


def _summarize_adapter(ad):
    mode = "DHCP" if ad.get("dhcp", "").lower() == "enabled" else "静态"
    ip = ad.get("ip") or "无 IP"
    gw = ad.get("gateway") or "无网关"
    return f"{mode} · {ip} · {gw}"


def _summarize_profile(prof):
    if prof.get("dhcp"):
        return "DHCP 自动获取"
    parts = [f"{prof.get('ip')}/{prof.get('mask')}"]
    if prof.get("gateway"):
        parts.append(f"网关 {prof['gateway']}")
    if prof.get("dns1"):
        dns = prof["dns1"] + (f", {prof['dns2']}" if prof.get("dns2") else "")
        parts.append(f"DNS {dns}")
    return " · ".join(parts)


class MismatchDialog(QDialog):
    """Shown when located at a point but no configured NIC matches.

    Multiple configured NICs may be present; the user picks exactly ONE to
    apply (applying the same static config to several NICs can break routing).
    """

    def __init__(self, parent, point, entries):
        super().__init__(parent)
        self.setWindowTitle("网络配置不符")
        self.setMinimumWidth(520)
        self._point = point
        self._entries = entries
        self._group = QButtonGroup(self)
        self._build_ui()
        self._select_default()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(16)

        title = QLabel(f"已定位到「{self._point.get('name', '?')}」，"
                       f"但没有已连接网卡符合该点的配置：")
        title.setWordWrap(True)
        root.addWidget(title)

        from PySide6.QtWidgets import QGroupBox
        box = QGroupBox("候选网卡（选择一张应用配置）")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(12)
        for i, e in enumerate(self._entries):
            prof = e["profile"]
            ad = e["adapter"]
            state = "已连接" if e["connected"] else "未连接"
            match_state = "✔ 配置一致" if e["matched"] else "配置不符"
            text = (f"{prof.get('label') or format_mac(prof.get('mac', ''))} "
                    f"[{format_mac(ad['mac'])}] ({state})\n"
                    f"    当前：{_summarize_adapter(ad)}\n"
                    f"    目标：{_summarize_profile(prof)}（{match_state}）")
            rb = QRadioButton(text)
            self._group.addButton(rb, i)
            box_layout.addWidget(rb)
        root.addWidget(box)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用所选配置")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("忽略")
        buttons.accepted.connect(self._on_apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _select_default(self):
        for i, e in enumerate(self._entries):
            if e["connected"] and not e["matched"]:
                self._group.button(i).setChecked(True)
                return
        for i, e in enumerate(self._entries):
            if e["connected"]:
                self._group.button(i).setChecked(True)
                return
        if self._entries:
            self._group.button(0).setChecked(True)

    def _on_apply(self):
        idx = self._group.checkedId()
        if idx < 0:
            return
        entry = self._entries[idx]
        name = entry["adapter"]["name"]
        prof = entry["profile"]
        from PySide6.QtWidgets import QMessageBox
        try:
            ok, text = ip_manager.apply_profile(name, prof)
        except ip_manager.ApplyError as exc:
            QMessageBox.warning(self, "应用失败", str(exc))
            return
        if ok:
            QMessageBox.information(self, "完成",
                                    f"已将「{name}」应用为：{_summarize_profile(prof)}")
            self.accept()
        else:
            QMessageBox.warning(self, "应用失败", f"netsh 返回错误：\n{text[-600:]}")
