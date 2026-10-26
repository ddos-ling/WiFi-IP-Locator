"""Mismatch dialog: prompt user to apply a NIC profile"""
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox,
                               QGroupBox, QLabel, QMessageBox, QProgressBar,
                               QRadioButton, QVBoxLayout)

from ..core import ip_manager
from ..core.ip_utils import effective_dns
from ..storage import format_mac
from .async_worker import AsyncDialogMixin, AsyncWorker


def _summarize_adapter(ad):
    mode = "DHCP" if ad.get("dhcp", "").lower() == "enabled" else "静态"
    ip = ad.get("ip") or "无 IP"
    gw = ad.get("gateway") or "无网关"
    return f"{mode} · {ip} · {gw}"


def _summarize_profile(prof, settings=None):
    if prof.get("dhcp"):
        parts = ["DHCP 自动获取"]
    else:
        parts = [f"{prof.get('ip')}/{prof.get('mask')}"]
        if prof.get("gateway"):
            parts.append(f"网关 {prof['gateway']}")
    dns1, dns2 = effective_dns(prof, settings)
    if dns1:
        parts.append(f"DNS {dns1}" + (f", {dns2}" if dns2 else ""))
    else:
        parts.append("DNS 跟随 DHCP")
    return " · ".join(parts)


class MismatchDialog(AsyncDialogMixin, QDialog):
    """Shown when located at a point but no configured NIC matches.

    Multiple configured NICs may be present; the user picks exactly ONE to
    apply (applying the same static config to several NICs can break routing).
    """

    def __init__(self, parent, point, entries, settings=None):
        super().__init__(parent)
        self.setWindowTitle("网络配置不符")
        self.setMinimumWidth(520)
        self._point = point
        self._entries = entries
        self._settings = settings
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

        box = QGroupBox("候选网卡（选择一张应用其所在组的配置）")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(12)
        for i, e in enumerate(self._entries):
            grp = e["group"]
            ad = e["adapter"]
            state = "已连接" if e["connected"] else "未连接"
            if e["matched"]:
                match_state = "✔ 配置一致" if e["connected"] else "配置一致（但未连接）"
            else:
                match_state = "配置不符"
            text = (f"{grp.get('label', '?')} · 成员 [{format_mac(ad['mac'])}] ({state})\n"
                    f"    当前：{_summarize_adapter(ad)}\n"
                    f"    目标：{_summarize_profile(grp, self._settings)}（{match_state}）")
            rb = QRadioButton(text)
            self._group.addButton(rb, i)
            box_layout.addWidget(rb)
        root.addWidget(box)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate "loading" animation
        self.progress.setTextVisible(False)
        self.progress.hide()
        root.addWidget(self.progress)

        self.lb_status = QLabel("")
        self.lb_status.hide()
        root.addWidget(self.lb_status)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                         QDialogButtonBox.StandardButton.Cancel)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("应用所选配置")
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("忽略")
        self._buttons.accepted.connect(self._on_apply)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

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
        if self._worker is not None:
            return  # already applying
        idx = self._group.checkedId()
        if idx < 0:
            return
        entry = self._entries[idx]
        name = entry["adapter"]["name"]
        prof = entry["group"]

        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.progress.show()
        self.lb_status.setText("正在应用配置，如弹出 UAC 授权窗口请点击「是」…")
        self.lb_status.show()
        self._applied_summary = _summarize_profile(prof, self._settings)

        self._worker = AsyncWorker(lambda: ip_manager.apply_profile(name, prof, self._settings),
                                   parent=self)
        self._worker.done.connect(self._on_apply_done)
        self._worker.failed.connect(self._on_apply_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_apply_done(self, pair):
        ok, text = pair
        self._worker = None
        self.progress.hide()
        self.lb_status.hide()
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        if ok:
            QMessageBox.information(self, "完成", f"配置已应用：{self._applied_summary}")
            self.accept()
        else:
            QMessageBox.warning(self, "应用失败", f"netsh 返回错误：\n{text[-600:]}")

    def _on_apply_failed(self, message):
        self._worker = None
        self.progress.hide()
        self.lb_status.hide()
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        QMessageBox.warning(self, "应用失败", message)
