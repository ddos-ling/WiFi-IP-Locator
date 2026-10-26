"""Geo point editor: name, threshold, SSID fingerprint selection"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core.wlan_api import scan_wifi, WlanError


class PointEditor(QDialog):
    """Create or edit a geo point (works on a copy; caller applies on accept)"""

    COL_CHECK, COL_SSID, COL_BSSID, COL_CH, COL_RSSI, COL_LINK = range(6)

    def __init__(self, parent, point):
        super().__init__(parent)
        self._point = point
        self._scan = []
        self.setWindowTitle("编辑地理点" if point.get("name") else "添加地理点")
        self.setMinimumSize(620, 480)
        self._build_ui()
        self._precheck()
        self._do_scan()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(16)

        form = QHBoxLayout()
        form.setSpacing(16)
        form.addWidget(QLabel("名称"))
        self.ed_name = QLineEdit(self._point.get("name", ""))
        self.ed_name.setPlaceholderText("例如：办公室工位 / 会议室")
        form.addWidget(self.ed_name, 1)
        form.addWidget(QLabel("匹配阈值 %"))
        self.sp_threshold = QDoubleSpinBox()
        self.sp_threshold.setRange(50.0, 99.0)
        self.sp_threshold.setSingleStep(1.0)
        self.sp_threshold.setValue(float(self._point.get("threshold", 75.0)))
        self.sp_threshold.setToolTip("当前环境与指纹的相似度达到该值才算匹配；调高更严格")
        form.addWidget(self.sp_threshold)
        root.addLayout(form)

        hint = QLabel("扫描周围 WiFi 后勾选参与定位的 AP（建议勾选信号稳定、区别度高的 SSID）")
        hint.setWordWrap(True)
        root.addWidget(hint)

        btn_row = QHBoxLayout()
        self.btn_scan = QPushButton("重新扫描周围 WiFi")
        self.btn_scan.clicked.connect(self._do_scan)
        btn_row.addWidget(self.btn_scan)
        self.lb_scan_time = QLabel("")
        btn_row.addWidget(self.lb_scan_time, 1)
        root.addLayout(btn_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["选择", "SSID", "BSSID (MAC)", "信道", "信号 (dBm)", "链路质量"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(self.COL_CHECK, 50)
        self.table.setColumnWidth(self.COL_SSID, 170)
        self.table.setColumnWidth(self.COL_BSSID, 150)
        self.table.setColumnWidth(self.COL_CH, 60)
        self.table.setColumnWidth(self.COL_RSSI, 90)
        root.addWidget(self.table, 1)

        self.lb_status = QLabel("")
        root.addWidget(self.lb_status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _precheck(self):
        self._selected = {f["bssid"] for f in self._point.get("fingerprint", [])}

    def _do_scan(self):
        self.btn_scan.setEnabled(False)
        self.lb_status.setText("正在扫描…")
        try:
            self._scan = scan_wifi(scan_wait_ms=2200)
        except WlanError as exc:
            self._scan = []
            self.lb_status.setText(f"扫描失败：{exc}")
        else:
            self.lb_status.setText(f"扫描到 {len(self._scan)} 个 AP")
        finally:
            self.btn_scan.setEnabled(True)
        self._fill_table()

    def _fill_table(self):
        self.table.setRowCount(0)
        for row, ap in enumerate(self._scan):
            self.table.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked if ap["bssid"] in self._selected
                              else Qt.CheckState.Unchecked)
            self.table.setItem(row, self.COL_CHECK, chk)
            self.table.setItem(row, self.COL_SSID, QTableWidgetItem(ap["ssid"]))
            self.table.setItem(row, self.COL_BSSID, QTableWidgetItem(ap["bssid"]))
            self.table.setItem(row, self.COL_CH, QTableWidgetItem(str(ap["channel"] or "-")))
            self.table.setItem(row, self.COL_RSSI, QTableWidgetItem(str(ap["rssi"])))
            self.table.setItem(row, self.COL_LINK, QTableWidgetItem(str(ap["link"])))

    def _on_accept(self):
        name = self.ed_name.text().strip()
        if not name:
            self.lb_status.setText("请填写地理点名称")
            return
        selected = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_CHECK)
            if item and item.checkState() == Qt.CheckState.Checked:
                bssid = self.table.item(row, self.COL_BSSID).text()
                ap = next((a for a in self._scan if a["bssid"] == bssid), None)
                if ap:
                    selected.append({"bssid": ap["bssid"], "ssid": ap["ssid"], "rssi": ap["rssi"]})
        if not selected:
            self.lb_status.setText("请至少勾选一个参与定位的 AP")
            return
        self._point["name"] = name
        self._point["threshold"] = float(self.sp_threshold.value())
        self._point["fingerprint"] = selected
        self.accept()

    def result_point(self):
        return self._point
