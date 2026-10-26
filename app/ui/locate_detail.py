"""Locate detail: show similarity scores of all points right now"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core.locator import evaluate_points
from ..core.wlan_api import scan_wifi, WlanError


class LocateDetailDialog(QDialog):
    def __init__(self, parent, config):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("定位详情")
        self.setMinimumSize(520, 380)
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(16)
        self.lb_summary = QLabel("")
        self.lb_summary.setWordWrap(True)
        root.addWidget(self.lb_summary)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["地理点", "当前相似度", "阈值", "结果"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 110)
        self.table.setColumnWidth(2, 80)
        root.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.close)
        root.addWidget(buttons)

    def refresh(self):
        points = self._config.points
        if not points:
            self.lb_summary.setText("尚未添加任何地理点")
            return
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        self.lb_summary.setText("正在扫描…")
        QApplication.processEvents()
        try:
            scan = scan_wifi()
            results = evaluate_points(points, scan)
        except WlanError as exc:
            self.lb_summary.setText(f"扫描失败：{exc}")
            self.table.setRowCount(0)
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.table.setRowCount(0)
        for r in results:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(r["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(f"{r['score']:.1f}%"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{r['threshold']:.0f}%"))
            verdict = "✔ 匹配" if r["matched"] else "低于阈值"
            self.table.setItem(row, 3, QTableWidgetItem(verdict))
        top = results[0] if results else None
        if top and top["matched"]:
            self.lb_summary.setText(f"当前最佳匹配：「{top['name']}」（{top['score']:.1f}%）")
        else:
            self.lb_summary.setText("无法进行空间定位：所有地理点均低于阈值")
