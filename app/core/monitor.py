"""Background monitor thread: scan -> locate -> network check"""
import time

from PySide6.QtCore import QThread, Signal

from .locator import evaluate_points, best_match
from .nic_info import get_adapters, find_by_mac, is_connected
from .wlan_api import scan_wifi, WlanError


def profile_matches(prof, adapter, settings=None):
    """Whether an adapter's current config matches a profile (+ global DNS)"""
    if not prof or not adapter:
        return False
    dhcp_on = adapter.get("dhcp", "").lower() == "enabled"
    if prof.get("dhcp"):
        addr_ok = dhcp_on
    else:
        if dhcp_on:
            return False
        from .ip_utils import mask_to_prefix
        addr_ok = ((adapter.get("ip") or "") == (prof.get("ip") or "")
                   and mask_to_prefix(prof.get("mask") or "") in (0, adapter.get("prefix", 0))
                   and (not prof.get("gateway") or adapter.get("gateway") == prof["gateway"]))
    if not addr_ok:
        return False
    # DNS only verifiable when a static DNS is in effect; DHCP-provided
    # DNS cannot be compared, so it is skipped
    from .ip_utils import effective_dns
    dns1, dns2 = effective_dns(prof, settings)
    if dns1:
        dns = adapter.get("dns") or []
        if not dns or dns[0] != dns1:
            return False
        if dns2 and (len(dns) < 2 or dns[1] != dns2):
            return False
    return True


class MonitorWorker(QThread):
    location_changed = Signal(dict)   # {matched, point, score, results}
    network_state = Signal(dict)      # {point, ok, entries, transition, silent}
    scan_error = Signal(str)

    def __init__(self, config):
        super().__init__()
        self._config = config
        self._stop = False
        self._force_scan = False
        self._force_check = False
        self._current_point_id = None
        self._candidate_id = None
        self._candidate_count = 0

    # --- control API (thread-safe flags) ---

    def stop(self):
        self._stop = True

    def force_rescan(self):
        self._force_scan = True

    def force_network_check(self):
        self._force_check = True

    @property
    def current_point_id(self):
        return self._current_point_id

    # --- main loop ---

    def run(self):
        first = True
        while not self._stop:
            interval = max(10, int(self._config.settings.get("scan_interval", 30)))
            try:
                scan = scan_wifi()
            except WlanError as exc:
                self.scan_error.emit(str(exc))
                if self._sleep(interval):
                    return
                continue

            matched, results = self._evaluate(scan)
            self.location_changed.emit({
                "matched": matched is not None,
                "point": matched,
                "results": results,
            })

            need_check = False
            if matched is not None:
                pid = matched["id"]
                if pid != self._candidate_id:
                    self._candidate_id = pid
                    self._candidate_count = 1
                else:
                    self._candidate_count += 1
                debounce = max(1, int(self._config.settings.get("debounce", 2)))
                confirmed = (self._candidate_count >= debounce) or first
                if confirmed and pid != self._current_point_id:
                    self._current_point_id = pid
                    need_check = True  # transition into a new point
            else:
                self._candidate_id = None
                self._candidate_count = 0
                if self._current_point_id is not None:
                    self._current_point_id = None
                    self.network_state.emit({"point": None, "ok": True, "entries": [],
                                             "transition": True, "silent": True})

            if self._force_check:
                need_check = True

            first = False
            force = self._force_check
            self._force_check = False
            point = self._config.get_point(self._current_point_id) if self._current_point_id else None
            if point:
                # re-check every cycle so manual config drift is detected;
                # transition/force flag lets the UI open the prompt dialog
                self._check_network(point, transition=need_check)
            elif need_check:
                self.network_state.emit({"point": None, "ok": True, "entries": [],
                                         "transition": True, "silent": True})

            if self._sleep(interval):
                return

    def _evaluate(self, scan):
        points = self._config.points
        _, results = best_match(points, scan)
        top = results[0] if results else None
        if top and top["matched"]:
            return self._config.get_point(top["id"]), results
        return None, results

    def _check_network(self, point, transition=True):
        try:
            adapters = get_adapters()
        except Exception as exc:  # AdapterError or unexpected
            self.network_state.emit({"point": point, "ok": False, "entries": [],
                                     "transition": transition, "silent": True,
                                     "error": str(exc)})
            return
        entries = []
        ok = False
        for grp in point.get("nic_groups", []):
            for mac in grp.get("macs", []):
                ad = find_by_mac(adapters, mac)
                if not ad:
                    continue
                connected = is_connected(ad)
                matched = profile_matches(grp, ad, self._config.settings)
                entries.append({
                    "group": grp,
                    "adapter": ad,
                    "connected": connected,
                    "matched": matched,
                })
                if connected and matched:
                    ok = True  # one live match inside a group is enough
        self.network_state.emit({
            "point": point, "ok": ok, "entries": entries,
            "transition": transition, "silent": False,
        })

    def _sleep(self, seconds):
        """Interruptible sleep; returns True when stopping"""
        for _ in range(int(seconds * 2)):
            if self._stop or self._force_scan:
                if self._force_scan:
                    self._force_scan = False
                    return False
                return True
            time.sleep(0.5)
        return False
