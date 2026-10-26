"""Locate detail: live debugging panel with continuous high-frequency scans"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from ..core.locator import evaluate_points
from ..core.wlan_api import scan_wifi
from .async_worker import AsyncDialogMixin, AsyncWorker


class LocateDetailDialog(AsyncDialogMixin, QDialog):
    """Continuous monitoring of point-match scores for tuning thresholds"""

    def __init__(self, parent, config):
        super().__init__(parent)
        self._config = config
        self._worker = None
        self._last_scan = None
        self.setWindowTitle("定位详情（调试）")
        self.setMinimumSize(560, 480)
        self._build_ui()
        self._refresh()

    # ---------- UI ----------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(16)

        # controls
        ctrl = QHBoxLayout()
        ctrl.setSpacing(16)
        self.btn_toggle = QPushButton("暂停")
        self.btn_toggle.clicked.connect(self._toggle)
        ctrl.addWidget(self.btn_toggle)
        ctrl.addWidget(QLabel("刷新间隔"))
        self.sp_interval = QSpinBox()
        self.sp_interval.setRange(2, 30)
        self.sp_interval.setValue(3)
        self.sp_interval.setSuffix(" 秒")
        self.sp_interval.setToolTip("连续扫描的间隔；扫描本身约需 2-3 秒")
        ctrl.addWidget(self.sp_interval)
        ctrl.addStretch(1)
        root.addLayout(ctrl)

        # stats
        stats = QFormLayout()
        stats.setSpacing(8)
        stats.setHorizontalSpacing(16)
        self.lb_matched = QLabel("—")
        self.lb_matched.setStyleSheet("font-weight: bold;")
        self.lb_max = QLabel("—")
        self.lb_min = QLabel("—")
        self.lb_avg = QLabel("—")
        self.lb_aps = QLabel("—")
        stats.addRow("当前匹配", self.lb_matched)
        stats.addRow("最高 / 最低 / 平均相似度", self._hbox(self.lb_max, self.lb_min, self.lb_avg))
        stats.addRow("当前环境可见 AP 数", self.lb_aps)
        root.addLayout(stats)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate "loading" animation
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        root.addWidget(self.progress)

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

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(self.sp_interval.value() * 1000)
        self.sp_interval.valueChanged.connect(
            lambda v: self._timer.setInterval(v * 1000))

    def _hbox(self, *labels):
        w = QHBoxLayout()
        w.setSpacing(16)
        for lb in labels:
            w.addWidget(lb)
        w.addStretch(1)
        return w

    # ---------- logic ----------

    def _toggle(self):
        if self._timer.isActive():
            self._timer.stop()
            self.btn_toggle.setText("开始")
        else:
            self._refresh()
            self._timer.start(self.sp_interval.value() * 1000)
            self.btn_toggle.setText("暂停")

    def _refresh(self):
        if self._worker is not None:
            return  # previous scan still running
        points = self._config.points
        if not points:
            self.lb_matched.setText("尚未添加任何地理点")
            return
        self.progress.show()

        def _run():
            scan = scan_wifi()
            return scan, evaluate_points(points, scan)

        self._worker = AsyncWorker(_run, parent=self)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_done(self, pair):
        self._worker = None
        self.progress.hide()
        scan, results = pair
        self._last_scan = scan
        self._fill_table(results)
        self._fill_stats(results, scan)

    def _on_failed(self, message):
        self._worker = None
        self.progress.hide()
        self.lb_matched.setText(f"扫描失败：{message}")

    def _fill_table(self, results):
        self.table.setRowCount(0)
        for r in results:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(r["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(f"{r['score']:.1f}%"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{r['threshold']:.0f}%"))
            verdict = "✔ 匹配" if r["matched"] else "低于阈值"
            self.table.setItem(row, 3, QTableWidgetItem(verdict))

    def _fill_stats(self, results, scan):
        self.lb_aps.setText(str(len(scan)))
        if not results:
            self.lb_max.setText("—")
            self.lb_min.setText("—")
            self.lb_avg.setText("—")
            return
        scores = [r["score"] for r in results]
        self.lb_max.setText(f"{max(scores):.1f}%（{results[0]['name']}）")
        self.lb_min.setText(f"{min(scores):.1f}%（{results[scores.index(min(scores))]['name']}）")
        self.lb_avg.setText(f"{sum(scores) / len(scores):.1f}%")
        matched = [r for r in results if r["matched"]]
        if matched:
            self.lb_matched.setText(f"✔ {matched[0]['name']}（{matched[0]['score']:.1f}%）")
        else:
            self.lb_matched.setText("✘ 无法进行空间定位")
