"""WiFi scan via the native Windows WLAN API (wlanapi.dll)

No command-line text parsing involved - all data comes from native
structures, so results are identical on any system language.
"""
import ctypes
from ctypes import wintypes

_DOT11_SSID_MAX_LEN = 32
_DOT11_RATE_SET_MAX = 126

# --- native structures (packed per MSVC rules; ctypes matches) ---

class DOT11_SSID(ctypes.Structure):
    _fields_ = [("uSSIDLength", ctypes.c_ulong),
                ("ucSSID", ctypes.c_ubyte * _DOT11_SSID_MAX_LEN)]


class WLAN_RATE_SET(ctypes.Structure):
    _fields_ = [("uRateSetLength", ctypes.c_ulong),
                ("usRateSet", ctypes.c_ushort * _DOT11_RATE_SET_MAX)]


class WLAN_BSS_ENTRY(ctypes.Structure):
    _fields_ = [
        ("dot11Ssid", DOT11_SSID),
        ("uPhyId", ctypes.c_ulong),
        ("dot11Bssid", ctypes.c_ubyte * 6),
        ("dot11BssType", ctypes.c_uint),
        ("dot11BssPhyType", ctypes.c_uint),
        ("lRssi", ctypes.c_long),
        ("uLinkQuality", ctypes.c_ulong),
        ("bInRegDomain", ctypes.c_ubyte),
        ("usBeaconPeriod", ctypes.c_ushort),
        ("ullTimestamp", ctypes.c_ulonglong),
        ("ullHostTimestamp", ctypes.c_ulonglong),
        ("usCapabilityInformation", ctypes.c_ushort),
        ("ulChCenterFrequency", ctypes.c_ulong),
        ("wlanRateSet", WLAN_RATE_SET),
        ("ulIeOffset", ctypes.c_ulong),
        ("ulIeSize", ctypes.c_ulong),
    ]


class WLAN_BSS_LIST(ctypes.Structure):
    _fields_ = [("dwTotalSize", ctypes.c_ulong),
                ("dwNumberOfItems", ctypes.c_ulong),
                ("wlanBssEntries", WLAN_BSS_ENTRY * 1)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [("InterfaceGuid", GUID),
                ("strInterfaceDescription", ctypes.c_wchar * 256),
                ("isState", ctypes.c_uint)]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", ctypes.c_ulong),
                ("dwIndex", ctypes.c_ulong),
                ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)]


_ENTRY_SIZE = ctypes.sizeof(WLAN_BSS_ENTRY)

_wlan = ctypes.WinDLL("wlanapi")
_wlan.WlanOpenHandle.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
_wlan.WlanOpenHandle.restype = ctypes.c_ulong
_wlan.WlanCloseHandle.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_wlan.WlanCloseHandle.restype = ctypes.c_ulong
_wlan.WlanFreeMemory.argtypes = [ctypes.c_void_p]
_wlan.WlanFreeMemory.restype = None
_wlan.WlanEnumInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(WLAN_INTERFACE_INFO_LIST))]
_wlan.WlanEnumInterfaces.restype = ctypes.c_ulong
_wlan.WlanGetNetworkBssList.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(DOT11_SSID),
                                        ctypes.c_uint, ctypes.c_int, ctypes.c_void_p,
                                        ctypes.POINTER(ctypes.POINTER(WLAN_BSS_LIST))]
_wlan.WlanGetNetworkBssList.restype = ctypes.c_ulong
_wlan.WlanScan.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(DOT11_SSID),
                           ctypes.c_void_p, ctypes.c_void_p]
_wlan.WlanScan.restype = ctypes.c_ulong


class WlanError(Exception):
    pass


def _guid(guid_struct):
    d = guid_struct
    return "%08X-%04X-%04X-%s-%s" % (
        d.Data1, d.Data2, d.Data3,
        "".join("%02X" % b for b in d.Data4[:2]),
        "".join("%02X" % b for b in d.Data4[2:]),
    )


def _mac(b):
    return "".join("%02X" % x for x in b)


def _ssid(entry):
    n = entry.dot11Ssid.uSSIDLength
    if n == 0 or n > _DOT11_SSID_MAX_LEN:
        return "<hidden>"
    raw = bytes(entry.dot11Ssid.ucSSID[:n])
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def list_interfaces(handle):
    plist = ctypes.POINTER(WLAN_INTERFACE_INFO_LIST)()
    rc = _wlan.WlanEnumInterfaces(handle, None, ctypes.byref(plist))
    if rc != 0:
        raise WlanError(f"WlanEnumInterfaces failed (error {rc})")
    try:
        out = []
        lst = plist.contents
        for i in range(lst.dwNumberOfItems):
            info = lst.InterfaceInfo[i]
            out.append({"guid": _guid(info.InterfaceGuid),
                        "desc": info.strInterfaceDescription})
        return out
    finally:
        _wlan.WlanFreeMemory(plist)


def _read_bss_list(handle, guid_struct):
    plist = ctypes.POINTER(WLAN_BSS_LIST)()
    rc = _wlan.WlanGetNetworkBssList(handle, ctypes.byref(guid_struct), None,
                                     3, False, None, ctypes.byref(plist))  # 3 = dot11_BSS_type_any
    if rc != 0:
        raise WlanError(f"WlanGetNetworkBssList failed (error {rc})")
    try:
        blob = ctypes.string_at(plist.contents, plist.contents.dwTotalSize)
        count = plist.contents.dwNumberOfItems
        entries = []
        for i in range(count):
            off = 8 + i * _ENTRY_SIZE
            if off + _ENTRY_SIZE > len(blob):
                break
            e = WLAN_BSS_ENTRY.from_buffer_copy(blob[off:off + _ENTRY_SIZE])
            freq_mhz = e.ulChCenterFrequency // 1000
            entries.append({
                "bssid": _mac(e.dot11Bssid),
                "ssid": _ssid(e),
                "rssi": int(e.lRssi),
                "link": int(e.uLinkQuality),
                "freq_mhz": freq_mhz,
                "channel": _freq_to_channel(freq_mhz),
            })
        return entries
    finally:
        _wlan.WlanFreeMemory(plist)


def _freq_to_channel(freq):
    if 2412 <= freq <= 2484:
        return (freq - 2412) // 5 + 1
    if freq == 2484:
        return 14
    if 5160 <= freq <= 5885:
        return (freq - 5000) // 5
    if 5955 <= freq <= 7115:
        return (freq - 5950) // 5
    return 0


def trigger_scan(handle, guid_struct):
    """Ask the driver to refresh the BSS list (async, returns immediately)"""
    _wlan.WlanScan(handle, ctypes.byref(guid_struct), None, None, None)


def scan_wifi(scan_wait_ms=2200):
    """Scan surrounding APs.

    Returns a list of dicts: {bssid, ssid, rssi, link, freq_mhz, channel}
    Deduplicated by BSSID (keep strongest signal).

    Raises WlanError when no wireless adapter is present or the service fails.
    """
    handle = ctypes.c_void_p()
    rc = _wlan.WlanOpenHandle(2, None, ctypes.byref(ctypes.c_ulong()), ctypes.byref(handle))
    if rc != 0:
        raise WlanError(f"WlanOpenHandle failed (error {rc}) - WLAN 服务可能未运行")
    try:
        interfaces = list_interfaces(handle)
        if not interfaces:
            raise WlanError("未检测到无线网卡")
        import time
        for if_info in interfaces:
            g = _string_to_guid(if_info["guid"])
            trigger_scan(handle, g)
        time.sleep(scan_wait_ms / 1000.0)
        result = {}
        for if_info in interfaces:
            g = _string_to_guid(if_info["guid"])
            for entry in _read_bss_list(handle, g):
                b = entry["bssid"]
                if not b or set(b) == {"0"}:
                    continue
                old = result.get(b)
                if old is None or entry["rssi"] > old["rssi"]:
                    result[b] = entry
        return sorted(result.values(), key=lambda x: -x["rssi"])
    finally:
        _wlan.WlanCloseHandle(handle, None)


def _string_to_guid(s):
    import uuid as _uuid
    u = _uuid.UUID(s)
    g = GUID()
    g.Data1 = u.time_low
    g.Data2 = u.time_mid
    g.Data3 = u.time_hi_version
    for i in range(8):
        g.Data4[i] = u.bytes[8 + i]
    return g
