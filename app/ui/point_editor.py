"""Geo point editor: SSID tree, multi-sample fingerprinting, threshold hint"""
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                               QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from ..core.locator import similarity
from ..core.wlan_api import scan_wifi
from ..storage import format_mac
from .async_worker import AsyncDialogMixin, AsyncWorker


def _gray_brush():
    return QBrush(QColor(128, 128, 128))


def _aggregate(scans):
    """Merge N scans: per-BSSID average rssi/link and sample count"""
    agg = {}
    for scan in scans:
        for ap in scan:
            e = agg.setdefault(ap["bssid"], {"ssid": ap["ssid"], "rssi_sum": 0,
                                             "link_sum": 0, "ch": ap["channel"],
                                             "count": 0, "best": -999})
            e["rssi_sum"] += ap["rssi"]
            e["link_sum"] += ap["link"]
            e["count"] += 1
            e["best"] = max(e["best"], ap["rssi"])
    out = {}
    for b, e in agg.items():
        out[b] = {"ssid": e["ssid"], "rssi": round(e["rssi_sum"] / e["count"]),
                  "link": round(e["link_sum"] / e["count"]), "ch": e["ch"],
                  "count": e["count"], "best": e["best"]}
    return out


class PointEditor(AsyncDialogMixin, QDialog):
    """Create or edit a geo point (works on a copy; caller applies on accept)"""

    COL_NAME, COL_CH, COL_RSSI, COL_SAMPLE, COL_LINK = range(5)

    def __init__(self, parent, point):
        super().__init__(parent)
        self._point = point
        self._worker = None
        self._checked = {f["bssid"] for f in point.get("fingerprint", [])}
        self._agg = {}          # bssid -> aggregated sample info
        self._total_samples = 0
        self._latest_scan = None
        self._building = False  # guards itemChanged during tree rebuild
        self.setWindowTitle("编辑地理点" if point.get("name") else "添加地理点")
        self.setMinimumSize(680, 580)
        self._build_ui()
        self._start_sampling()

    # ---------- UI ----------

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
        self.sp_threshold.setToolTip("当前环境与指纹的相似度达到该值才算匹配；可参考下方匹配度预估设置")
        form.addWidget(self.sp_threshold)
        root.addLayout(form)

        # sampling controls
        sample_row = QHBoxLayout()
        sample_row.setSpacing(8)
        self.btn_scan = QPushButton("开始采样")
        self.btn_scan.clicked.connect(self._start_sampling)
        sample_row.addWidget(self.btn_scan)
        sample_row.addWidget(QLabel("采样次数"))
        self.sp_samples = QSpinBox()
        self.sp_samples.setRange(1, 10)
        self.sp_samples.setValue(3)
        self.sp_samples.setToolTip("多次采样取平均，可过滤瞬时信号波动，提高指纹质量")
        sample_row.addWidget(self.sp_samples)
        self.btn_retest = QPushButton("重测匹配度")
        self.btn_retest.clicked.connect(self._retest)
        self.btn_retest.setToolTip("单独扫一次并按当前勾选重新计算匹配度预估")
        sample_row.addWidget(self.btn_retest)
        self.lb_scan_time = QLabel("")
        sample_row.addWidget(self.lb_scan_time, 1)
        root.addLayout(sample_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate "loading" animation
        self.progress.setTextVisible(False)
        self.progress.hide()
        root.addWidget(self.progress)

        # SSID quick select
        ssid_row = QHBoxLayout()
        ssid_row.setSpacing(8)
        ssid_row.addWidget(QLabel("按 SSID 选择"))
        self.cb_ssid = QComboBox()
        self.cb_ssid.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        ssid_row.addWidget(self.cb_ssid, 1)
        btn_pick_ssid = QPushButton("勾选该 SSID 全部 AP")
        btn_pick_ssid.clicked.connect(self._on_pick_ssid)
        ssid_row.addWidget(btn_pick_ssid)
        btn_all = QPushButton("全选")
        btn_all.clicked.connect(lambda: self._set_all_checked(Qt.CheckState.Checked))
        ssid_row.addWidget(btn_all)
        btn_none = QPushButton("清空")
        btn_none.clicked.connect(lambda: self._set_all_checked(Qt.CheckState.Unchecked))
        ssid_row.addWidget(btn_none)
        root.addLayout(ssid_row)

        # threshold preview
        self.lb_preview = QLabel("")
        self.lb_preview.setWordWrap(True)
        self.lb_preview.setStyleSheet("font-weight: bold;")
        root.addWidget(self.lb_preview)

        hint = QLabel("同名 SSID 已合并为一个节点（按信号强度排序）；建议勾选信号强、"
                      "区别度高的 AP，弱信号 AP 缺席时算法会自动容忍")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["SSID / BSSID", "信道", "信号 (dBm)", "采样", "链路质量"])
        self.tree.setAlternatingRowColors(True)
        self.tree.header().resizeSection(0, 320)
        self.tree.header().resizeSection(1, 60)
        self.tree.header().resizeSection(2, 100)
        self.tree.header().resizeSection(3, 90)
        self.tree.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.tree, 1)

        self.lb_status = QLabel("")
        root.addWidget(self.lb_status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---------- sampling ----------

    def _start_sampling(self):
        if self._worker is not None:
            return  # sampling already running
        n = self.sp_samples.value()
        self.btn_scan.setEnabled(False)
        self.btn_retest.setEnabled(False)
        self.progress.show()
        self.lb_scan_time.setText("准备采样…")

        def _run(emit):
            scans = []
            for i in range(n):
                if i:
                    time.sleep(0.8)  # settle between samples
                scans.append(scan_wifi(scan_wait_ms=1800))
                emit((i + 1, n))
            return scans

        self._worker = AsyncWorker(_run, parent=self, with_progress=True)
        self._worker.progress.connect(self._on_sample_progress)
        self._worker.done.connect(self._on_sampling_done)
        self._worker.failed.connect(self._on_sampling_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _retest(self):
        """Single quick scan, only refreshes the match preview"""
        if self._worker is not None:
            return
        self.btn_retest.setEnabled(False)
        self.progress.show()
        self._worker = AsyncWorker(lambda: scan_wifi(scan_wait_ms=1800), parent=self)
        self._worker.done.connect(self._on_retest_done)
        self._worker.failed.connect(self._on_retest_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_sample_progress(self, payload):
        cur, total = payload
        self.lb_scan_time.setText(f"采样中 {cur}/{total}…")

    def _on_sampling_done(self, scans):
        self._worker = None
        self._total_samples = len(scans)
        self._agg = _aggregate(scans)
        self._latest_scan = scans[-1] if scans else None
        self.lb_scan_time.setText(f"采样完成：{self._total_samples} 次，"
                                  f"{len(self._agg)} 个 AP（取平均信号）")
        self._finish_scan()
        self._rebuild_tree()

    def _on_sampling_failed(self, message):
        self._worker = None
        self.lb_scan_time.setText(f"采样失败：{message}")
        self._finish_scan()

    def _on_retest_done(self, scan):
        self._worker = None
        self._latest_scan = scan
        self.lb_scan_time.setText(f"重测完成：{len(scan)} 个 AP")
        self._finish_scan()
        self._update_preview()

    def _on_retest_failed(self, message):
        self._worker = None
        self.lb_scan_time.setText(f"重测失败：{message}")
        self._finish_scan()

    def _finish_scan(self):
        self.progress.hide()
        self.btn_scan.setEnabled(True)
        self.btn_retest.setEnabled(True)

    # ---------- tree ----------

    def _rebuild_tree(self):
        self._building = True
        self.tree.clear()
        configured = {f["bssid"]: f for f in self._point.get("fingerprint", [])}
        groups = {}
        for b, e in self._agg.items():
            groups.setdefault(e["ssid"], []).append(b)
        # SSIDs sorted by their strongest AP, children sorted by avg rssi
        ssid_order = sorted(groups,
                            key=lambda s: -max(self._agg[b]["best"] for b in groups[s]))
        n = max(1, self._total_samples)
        for ssid in ssid_order:
            bs = sorted(groups[ssid], key=lambda b: -self._agg[b]["rssi"])
            best = self._agg[bs[0]]["best"]
            parent = QTreeWidgetItem([f"{ssid}　({len(bs)} AP · 最佳 {best} dBm)",
                                      "-", str(best), "-", "-"])
            parent.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            parent.setData(0, Qt.ItemDataRole.UserRole, None)
            parent.setData(0, Qt.ItemDataRole.UserRole + 1, ssid)
            parent.setCheckState(0, self._group_state(bs))
            self.tree.addTopLevelItem(parent)
            for b in bs:
                e = self._agg[b]
                tag = "　[已配置]" if b in configured else ""
                child = QTreeWidgetItem([format_mac(b) + tag, str(e["ch"] or "-"),
                                         str(e["rssi"]), f"{e['count']}/{n}",
                                         str(e["link"])])
                child.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                child.setData(0, Qt.ItemDataRole.UserRole, b)
                child.setCheckState(0, Qt.CheckState.Checked if b in self._checked
                                    else Qt.CheckState.Unchecked)
                if b in configured:
                    child.setForeground(0, _gray_brush())
                parent.addChild(child)
        # configured but not sampled this round
        for b, f in configured.items():
            if b in self._agg:
                continue
            child = QTreeWidgetItem([f"{f.get('ssid', '?')} · {format_mac(b)}　[已配置·未采样]",
                                     "-", "未采样", f"0/{n}", "-"])
            child.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            child.setData(0, Qt.ItemDataRole.UserRole, b)
            child.setCheckState(0, Qt.CheckState.Checked if b in self._checked
                                else Qt.CheckState.Unchecked)
            for col in range(5):
                child.setForeground(col, _gray_brush())
            self.tree.addTopLevelItem(child)
        self._building = False
        self._refresh_ssid_combo()
        self._update_preview()

    def _group_state(self, bssids):
        all_on = all(b in self._checked for b in bssids)
        any_on = any(b in self._checked for b in bssids)
        if all_on:
            return Qt.CheckState.Checked
        return Qt.CheckState.PartiallyChecked if any_on else Qt.CheckState.Unchecked

    def _on_item_changed(self, item, col):
        if self._building or col != 0:
            return
        b = item.data(0, Qt.ItemDataRole.UserRole)
        if b is None:
            # parent toggled: propagate to children
            on = item.checkState(0) != Qt.CheckState.Unchecked
            self._building = True
            for i in range(item.childCount()):
                child = item.child(i)
                cb = child.data(0, Qt.ItemDataRole.UserRole)
                if cb is None:
                    continue
                child.setCheckState(0, Qt.CheckState.Checked if on
                                    else Qt.CheckState.Unchecked)
                if on:
                    self._checked.add(cb)
                else:
                    self._checked.discard(cb)
            self._building = False
        else:
            if item.checkState(0) == Qt.CheckState.Checked:
                self._checked.add(b)
            else:
                self._checked.discard(b)
            parent = item.parent()
            if parent is not None:
                self._building = True
                bs = [parent.child(i).data(0, Qt.ItemDataRole.UserRole)
                      for i in range(parent.childCount())]
                parent.setCheckState(0, self._group_state(bs))
                self._building = False
        self._update_preview()

    # ---------- helpers ----------

    def _refresh_ssid_combo(self):
        keep = self.cb_ssid.currentText()
        self.cb_ssid.blockSignals(True)
        self.cb_ssid.clear()
        for ssid in sorted({e["ssid"] for e in self._agg.values()}):
            self.cb_ssid.addItem(ssid)
        self.cb_ssid.blockSignals(False)
        idx = self.cb_ssid.findText(keep)
        if idx >= 0:
            self.cb_ssid.setCurrentIndex(idx)

    def _on_pick_ssid(self):
        ssid = self.cb_ssid.currentText()
        if not ssid:
            return
        count = 0
        self._building = True
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole + 1) != ssid:
                continue
            for j in range(item.childCount()):
                child = item.child(j)
                cb = child.data(0, Qt.ItemDataRole.UserRole)
                if cb is None:
                    continue
                child.setCheckState(0, Qt.CheckState.Checked)
                self._checked.add(cb)
                count += 1
        self._building = False
        self.lb_status.setText(f"已勾选 SSID「{ssid}」下的 {count} 个 AP")
        self._update_preview()

    def _set_all_checked(self, state):
        self._building = True
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            for j in range(item.childCount()):
                child = item.child(j)
                cb = child.data(0, Qt.ItemDataRole.UserRole)
                if cb is None:
                    continue
                child.setCheckState(0, state)
                if state == Qt.CheckState.Checked:
                    self._checked.add(cb)
                else:
                    self._checked.discard(cb)
            item.setCheckState(0, state)
        self._building = False
        self._update_preview()

    def _fingerprint_from_checked(self):
        """Build fingerprint from current selection (averaged or last known rssi)"""
        fp = {}
        old_fp = {f["bssid"]: f for f in self._point.get("fingerprint", [])}
        for b in self._checked:
            if b in self._agg:
                fp[b] = self._agg[b]["rssi"]
            elif b in old_fp:
                fp[b] = old_fp[b]["rssi"]
        return fp

    def _update_preview(self):
        if self._latest_scan is None:
            self.lb_preview.setText("")
            return
        fp = self._fingerprint_from_checked()
        if not fp:
            self.lb_preview.setText("勾选 AP 后将自动预估当前环境的匹配度")
            return
        scan_map = {r["bssid"]: r["rssi"] for r in self._latest_scan}
        score = similarity(fp, scan_map)
        suggest = max(50, min(95, round(score - 5)))
        self.lb_preview.setText(
            f"按当前勾选（{len(fp)} 个 AP）与最近一次扫描：匹配度 {score:.1f}%　→　"
            f"建议阈值 ≈ {suggest}%（留 5% 余量，可在上方调整）")

    # ---------- accept ----------

    def _on_accept(self):
        name = self.ed_name.text().strip()
        if not name:
            self.lb_status.setText("请填写地理点名称")
            return
        old_fp = {f["bssid"]: f for f in self._point.get("fingerprint", [])}
        selected = []
        for bssid in self._checked:
            if bssid in self._agg:
                e = self._agg[bssid]
                selected.append({"bssid": bssid, "ssid": e["ssid"], "rssi": e["rssi"]})
            elif bssid in old_fp:
                # not sampled this round: keep the last known record
                selected.append(dict(old_fp[bssid]))
        if not selected:
            self.lb_status.setText("请至少勾选一个参与定位的 AP")
            return
        self._point["name"] = name
        self._point["threshold"] = float(self.sp_threshold.value())
        self._point["fingerprint"] = selected
        self.accept()

    def result_point(self):
        return self._point
