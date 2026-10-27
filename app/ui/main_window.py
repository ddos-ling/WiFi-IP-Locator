"""Main window + tray"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QApplication, QDialog, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSystemTrayIcon, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..storage import Config, format_mac, new_point
from ..core.monitor import MonitorWorker
from .point_editor import PointEditor
from .nic_group_dialog import NicGroupDialog
from .settings_dialog import SettingsDialog
from .apply_dialog import MismatchDialog
from .locate_detail import LocateDetailDialog


class MainWindow(QMainWindow):
    def __init__(self, config: Config, icon: QIcon):
        super().__init__()
        self._config = config
        self._icon = icon
        self._monitor = None
        self._mismatch_dialog = None
        self._suppressed_point_id = None
        self._last_net_ok = None
        self._last_scan_ts = 0.0
        self._force_quit = False
        self.setWindowTitle("WiFi IP 定位助手")
        self.setWindowIcon(icon)
        self.resize(860, 560)
        self._build_ui()
        self._build_tray()
        self._start_monitor()

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

    # ---------- UI construction ----------

    def _build_ui(self):
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)
        self.setCentralWidget(central)

        # left: points
        left = QVBoxLayout()
        left.setSpacing(8)
        self.lb_points = QLabel("地理点")
        left.addWidget(self.lb_points)
        self.list_points = QListWidget()
        self.list_points.currentRowChanged.connect(self._on_point_selected)
        left.addWidget(self.list_points, 1)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_add = QPushButton("添加地理点")
        btn_add.clicked.connect(self._add_point)
        btn_edit = QPushButton("编辑")
        btn_edit.clicked.connect(self._edit_point)
        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self._delete_point)
        for b in (btn_add, btn_edit, btn_del):
            btn_row.addWidget(b)
        left.addLayout(btn_row)
        layout.addLayout(left, 5)

        # right: NIC groups
        right = QVBoxLayout()
        right.setSpacing(8)
        self.lb_profiles = QLabel("网卡组（未选择地理点）")
        right.addWidget(self.lb_profiles)
        self.table_profiles = QTableWidget(0, 7)
        self.table_profiles.setHorizontalHeaderLabels(
            ["组名", "成员网卡", "模式", "IP", "子网掩码", "网关", "DNS"])
        self.table_profiles.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_profiles.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        header = self.table_profiles.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setCascadingSectionResizes(True)
        self.table_profiles.setColumnWidth(0, 140)
        self.table_profiles.setColumnWidth(1, 200)
        self.table_profiles.setColumnWidth(2, 70)
        self.table_profiles.setColumnWidth(3, 130)
        self.table_profiles.setColumnWidth(4, 130)
        self.table_profiles.setColumnWidth(5, 120)
        self.table_profiles.setWordWrap(False)
        right.addWidget(self.table_profiles, 1)
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(8)
        btn_p_add = QPushButton("添加网卡组")
        btn_p_add.clicked.connect(self._add_profile)
        btn_p_edit = QPushButton("编辑")
        btn_p_edit.clicked.connect(self._edit_profile)
        btn_p_del = QPushButton("删除")
        btn_p_del.clicked.connect(self._delete_profile)
        btn_check = QPushButton("立即检查")
        btn_check.clicked.connect(self._force_check)
        for b in (btn_p_add, btn_p_edit, btn_p_del, btn_check):
            btn_row2.addWidget(b)
        right.addLayout(btn_row2)
        layout.addLayout(right, 7)

        # menu
        menu = self.menuBar().addMenu("工具(&T)")
        act_detail = QAction("定位详情…", self)
        act_detail.triggered.connect(self._show_detail)
        act_settings = QAction("设置…", self)
        act_settings.triggered.connect(self._show_settings)
        menu.addAction(act_detail)
        menu.addAction(act_settings)

        # status bar
        self.lb_loc = QLabel("定位：等待扫描…")
        self.lb_net = QLabel("网络：—")
        self.lb_scan = QLabel("")
        sb = self.statusBar()
        sb.addWidget(self.lb_loc)
        sb.addWidget(QLabel("    |    "))
        sb.addWidget(self.lb_net)
        sb.addPermanentWidget(self.lb_scan)
        self._refresh_point_list()

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self._icon, self)
        menu = QMenu()
        act_show = QAction("显示主窗口", self)
        act_show.triggered.connect(self._show_window)
        act_check = QAction("立即检查", self)
        act_check.triggered.connect(self._force_check)
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self._quit)
        menu.addAction(act_show)
        menu.addAction(act_check)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("WiFi IP 定位助手")
        self.tray.activated.connect(
            lambda reason: self._show_window()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    # ---------- monitor ----------

    def _start_monitor(self):
        self._monitor = MonitorWorker(self._config)
        self._monitor.location_changed.connect(self._on_location)
        self._monitor.network_state.connect(self._on_network_state)
        self._monitor.scan_error.connect(self._on_scan_error)
        self._monitor.start()

    def _tick(self):
        import time
        if self._last_scan_ts:
            self.lb_scan.setText(f"上次扫描 {int(time.time() - self._last_scan_ts)} 秒前")

    # ---------- point list ----------

    def _selected_point(self):
        item = self.list_points.currentItem()
        if not item:
            return None
        return self._config.get_point(item.data(Qt.ItemDataRole.UserRole))

    def _refresh_point_list(self, keep_id=None):
        self.list_points.blockSignals(True)
        self.list_points.clear()
        for p in self._config.points:
            item = QListWidgetItem(f"{p['name']}  (阈值 {p['threshold']:.0f}%)")
            item.setData(Qt.ItemDataRole.UserRole, p["id"])
            self.list_points.addItem(item)
            if p["id"] == keep_id:
                self.list_points.setCurrentItem(item)
        self.list_points.blockSignals(False)
        if self.list_points.currentRow() < 0 and self.list_points.count():
            self.list_points.setCurrentRow(0)
        else:
            self._refresh_profiles()

    def _on_point_selected(self, row):
        self._refresh_profiles()

    def _refresh_profiles(self):
        point = self._selected_point()
        if not point:
            self.lb_profiles.setText("网卡组（未选择地理点）")
            self.table_profiles.setRowCount(0)
            return
        n_fp = len(point.get("fingerprint", []))
        n_groups = len(point.get("nic_groups", []))
        n_macs = sum(len(g.get("macs", [])) for g in point.get("nic_groups", []))
        self.lb_profiles.setText(
            f"「{point['name']}」网卡组（{n_groups} 组 · {n_macs} 张网卡 · 指纹 {n_fp} AP · 阈值 {point['threshold']:.0f}%）")
        self.table_profiles.setRowCount(0)
        for grp in point.get("nic_groups", []):
            row = self.table_profiles.rowCount()
            self.table_profiles.insertRow(row)
            mode = "DHCP" if grp.get("dhcp") else "静态"
            macs = "\n".join(format_mac(m) for m in grp.get("macs", []))
            dns_mode = grp.get("dns_mode", "global")
            if dns_mode == "custom":
                dns = grp.get("dns1", "") + (f" / {grp['dns2']}" if grp.get("dns2") else "")
            elif dns_mode == "dhcp":
                dns = "跟随 DHCP"
            else:
                s = self._config.settings
                if s.get("global_dns_enabled"):
                    dns = f"全局 {s.get('global_dns1', '')}" + \
                          (f" / {s.get('global_dns2', '')}" if s.get("global_dns2") else "")
                else:
                    dns = "跟随 DHCP（全局未启用）"
            values = [grp.get("label", ""), macs, mode,
                      grp.get("ip", ""), grp.get("mask", ""),
                      grp.get("gateway", ""), dns]
            for col, v in enumerate(values):
                self.table_profiles.setItem(row, col, QTableWidgetItem(v))

    # ---------- point actions ----------

    def _add_point(self):
        point = new_point("")
        dlg = PointEditor(self, point)
        if dlg.exec() and dlg.result_point()["name"]:
            self._config.add_point(dlg.result_point())
            self._refresh_point_list(keep_id=point["id"])

    def _edit_point(self):
        point = self._selected_point()
        if not point:
            return
        import copy
        dlg = PointEditor(self, copy.deepcopy(point))
        if dlg.exec():
            updated = dlg.result_point()
            point.update(updated)
            self._config.save()
            self._refresh_point_list(keep_id=point["id"])

    def _delete_point(self):
        point = self._selected_point()
        if not point:
            return
        n_groups = len(point.get("nic_groups", []))
        msg = f"确定删除地理点「{point['name']}」？"
        if n_groups:
            msg += f"\n其下 {n_groups} 个网卡组将一并删除。"
        if QMessageBox.question(self, "删除地理点", msg) == QMessageBox.StandardButton.Yes:
            self._config.remove_point(point["id"])
            self._refresh_point_list()

    # ---------- profile actions ----------

    def _current_profile(self, point):
        row = self.table_profiles.currentRow()
        if row < 0 or row >= len(point.get("nic_groups", [])):
            return None
        return point["nic_groups"][row]

    def _add_profile(self):
        point = self._selected_point()
        if not point:
            QMessageBox.information(self, "提示", "请先选择一个地理点")
            return
        dlg = NicGroupDialog(self, None)
        if dlg.exec():
            point.setdefault("nic_groups", []).append(dlg.result_group())
            self._config.save()
            self._refresh_profiles()
            self._monitor.force_network_check()

    def _edit_profile(self):
        point = self._selected_point()
        if not point:
            return
        grp = self._current_profile(point)
        if not grp:
            QMessageBox.information(self, "提示", "请先选择一个网卡组")
            return
        import copy
        dlg = NicGroupDialog(self, copy.deepcopy(grp))
        if dlg.exec():
            grp.update(dlg.result_group())
            self._config.save()
            self._refresh_profiles()
            self._monitor.force_network_check()

    def _delete_profile(self):
        point = self._selected_point()
        if not point:
            return
        grp = self._current_profile(point)
        if not grp:
            QMessageBox.information(self, "提示", "请先选择一个网卡组")
            return
        if QMessageBox.question(
                self, "删除网卡组",
                f"确定删除网卡组「{grp.get('label')}」？") == QMessageBox.StandardButton.Yes:
            point["nic_groups"].remove(grp)
            self._config.save()
            self._refresh_profiles()

    # ---------- monitor slots ----------

    def _on_location(self, payload):
        import time
        self._last_scan_ts = time.time()
        point = payload.get("point")
        results = payload.get("results") or []
        top = results[0] if results else None
        if point:
            self.lb_loc.setText(f"定位：{point['name']}（相似度 {top['score']:.1f}%）")
            self.tray.setToolTip(f"WiFi IP 定位助手 - {point['name']}")
        else:
            hint = f"最高 {top['score']:.1f}%（{top['name']}）" if top else ""
            self.lb_loc.setText(f"定位：无法进行空间定位{('　' + hint) if hint else ''}")
            self.tray.setToolTip("WiFi IP 定位助手 - 无法进行空间定位")

    def _on_network_state(self, payload):
        point = payload.get("point")
        if point is None:
            self.lb_net.setText("网络：—")
            self._last_net_ok = None
            return
        if payload.get("error"):
            self.lb_net.setText(f"网络：检查失败（{payload['error']}）")
            return
        ok = payload["ok"]
        prev_ok = self._last_net_ok
        self._last_net_ok = ok
        # a fresh prompt is warranted on location switch, manual check,
        # or when the state flips from OK to not-OK (config drift);
        # while it stays not-OK the user is not nagged repeatedly
        prompt_warranted = bool(payload.get("transition")) or prev_ok is True
        if ok:
            self.lb_net.setText("网络：配置正常 ✔")
            self._suppressed_point_id = None
            return
        self.lb_net.setText("网络：配置不符 ✘")
        entries = payload.get("entries") or []
        if not entries:
            if prompt_warranted:
                self.tray.showMessage("无法检查网络",
                                      f"已定位到「{point['name']}」，但配置的网卡均不在位。",
                                      QSystemTrayIcon.MessageIcon.Warning, 5000)
            return
        # unconnected NICs are not fixable targets: skip prompting entirely
        if not payload.get("has_connected", any(e["connected"] for e in entries)):
            self.lb_net.setText("网络：配置网卡未连接")
            if prompt_warranted:
                self.tray.showMessage("网卡未连接",
                                      f"已定位到「{point['name']}」，但该点配置的网卡均未连接，"
                                      f"跳过网络配置检查。",
                                      QSystemTrayIcon.MessageIcon.Information, 5000)
            return
        entries = [e for e in entries if e["connected"]]
        if self._mismatch_dialog is not None:
            return
        if self._suppressed_point_id == point["id"]:
            return
        if not prompt_warranted:
            return
        self._suppressed_point_id = None
        self.raise_()
        self._show_window()
        self._mismatch_dialog = MismatchDialog(self, point, entries, self._config.settings)
        result = self._mismatch_dialog.exec()
        self._mismatch_dialog = None
        if result != int(QDialog.DialogCode.Accepted):
            # user ignored: do not re-prompt until the state flips back to OK
            # or the location changes
            self._suppressed_point_id = point["id"]
        self._monitor.force_network_check()

    def _on_scan_error(self, message):
        self.lb_loc.setText(f"定位：扫描失败 - {message}")

    # ---------- misc actions ----------

    def _force_check(self):
        if self._monitor:
            self._monitor.force_rescan()
            self._monitor.force_network_check()

    def _show_detail(self):
        LocateDetailDialog(self, self._config).exec()

    def _show_settings(self):
        SettingsDialog(self, self._config).exec()

    # ---------- window lifecycle ----------

    def _show_window(self):
        self.showNormal()
        self.activateWindow()

    def _quit(self):
        self._force_quit = True
        self.close()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if not self._force_quit:
            event.ignore()
            self.hide()
            self.tray.showMessage("仍在运行",
                                  "程序已最小化到托盘，将继续自动定位并检查网络。",
                                  QSystemTrayIcon.MessageIcon.Information, 3000)
            return
        if self._monitor:
            self._monitor.stop()
            self._monitor.requestInterruption()
            if not self._monitor.wait(5000):
                # thread stuck in a scan/system call; force it down
                self._monitor.terminate()
                self._monitor.wait(2000)
        self.tray.hide()
        event.accept()
