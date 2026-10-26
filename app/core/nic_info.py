"""Read current network adapter configuration via PowerShell cmdlets.

Structured JSON output; enum values (Up/Enabled/Connected...) are .NET enum
names and culture-invariant, so no localized-text parsing is involved.
"""
import json
import os
import re
import subprocess

from .ip_utils import mask_to_prefix  # noqa: F401  (re-export convenience)

_PS_QUERY = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$adapters = Get-NetAdapter -ErrorAction SilentlyContinue | ForEach-Object {
    $n = $_.Name
    $ip = Get-NetIPAddress -InterfaceAlias $n -AddressFamily IPv4 -ErrorAction SilentlyContinue |
          Where-Object { $_.PrefixOrigin -ne 'WellKnown' } | Select-Object -First 1
    $gw = Get-NetRoute -InterfaceAlias $n -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
          Sort-Object RouteMetric | Select-Object -First 1
    $ipif = Get-NetIPInterface -InterfaceAlias $n -AddressFamily IPv4 -ErrorAction SilentlyContinue
    $dns = Get-DnsClientServerAddress -InterfaceAlias $n -AddressFamily IPv4 -ErrorAction SilentlyContinue |
          Select-Object -First 1
    [pscustomobject]@{
        name    = $n
        mac     = $_.MacAddress
        desc    = [string]$_.InterfaceDescription
        status  = [string]$_.Status
        media   = [string]$_.MediaConnectState
        dhcp    = [string]$(if ($ipif) { $ipif.Dhcp } else { '' })
        ip      = $(if ($ip) { $ip.IPAddress } else { '' })
        prefix  = $(if ($ip) { $ip.PrefixLength } else { 0 })
        gateway = $(if ($gw) { $gw.NextHop } else { '' })
        dns     = @($dns.ServerAddresses)
    }
}
@($adapters) | ConvertTo-Json -Compress -Depth 4
"""


class AdapterError(Exception):
    pass


_PS_PREFLIGHT = (
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
    "$na = Get-Command Get-NetAdapter -ErrorAction SilentlyContinue;"
    "$js = Get-Command ConvertTo-Json -ErrorAction SilentlyContinue;"
    "Write-Output ('PSVER=' + $PSVersionTable.PSVersion.Major + "
    "';NETADAPTER=' + [bool]$na + ';JSON=' + [bool]$js)"
)

_ps_preflight_ok = False


def _check_environment():
    """One-time capability check so failures get an actionable message
    instead of a silently empty adapter list."""
    global _ps_preflight_ok
    if _ps_preflight_ok:
        return
    flags = 0 if os.name != "nt" else subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-Command", _PS_PREFLIGHT],
                              capture_output=True, timeout=15, creationflags=flags)
    except FileNotFoundError as exc:
        raise AdapterError("未找到 powershell.exe：系统缺少 Windows PowerShell，无法列出网卡") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("PowerShell 预检超时（可能被安全软件拦截），无法列出网卡") from exc
    except OSError as exc:
        raise AdapterError(f"无法启动 PowerShell：{exc}") from exc
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    m = re.search(r"PSVER=(\d+);NETADAPTER=(True|False);JSON=(True|False)", out)
    if not m:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()[:300]
        raise AdapterError(
            f"PowerShell 预检失败（退出码 {proc.returncode}）：{detail or '无输出，可能被执行策略或安全软件拦截'}")
    ver, has_na, has_json = int(m.group(1)), m.group(2) == "True", m.group(3) == "True"
    if ver < 3:
        raise AdapterError(f"PowerShell 版本过低（{ver}.0，需 3.0+），无法列出网卡")
    if not has_na:
        raise AdapterError("缺少 Get-NetAdapter Cmdlet：需要 Windows 8 / Server 2012 或以上系统")
    if not has_json:
        raise AdapterError("缺少 ConvertTo-Json Cmdlet：需要 PowerShell 3.0+")
    _ps_preflight_ok = True


def get_adapters(timeout=20, include_all=False):
    """Return list of adapter dicts.

    {name, mac, desc, status, media, dhcp, ip, prefix, gateway, dns[]}
    mac normalized to 12 hex chars uppercase.
    By default adapters without a MAC address and Bluetooth PAN devices
    are excluded (they are useless for IP configuration).

    Raises AdapterError with an actionable message when the PowerShell
    enumeration path is unavailable or returns nothing.
    """
    _check_environment()
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _PS_QUERY],
            capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdapterError(f"读取网卡信息失败: {exc}") from exc
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if not out:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()[:300]
        raise AdapterError(f"PowerShell 未返回网卡数据（退出码 {proc.returncode}）："
                           f"{detail or '无输出，可能被安全软件拦截'}")
    try:
        data = json.loads(out)
    except ValueError as exc:
        raise AdapterError(f"解析网卡信息失败: {exc}") from exc
    if isinstance(data, dict):
        data = [data]
    result = []
    for a in data:
        mac = re.sub(r"[^0-9A-Fa-f]", "", a.get("mac") or "").upper()
        desc = a.get("desc") or ""
        if not include_all:
            if not mac:
                continue
            if "bluetooth" in desc.lower():
                continue
        dns = a.get("dns") or []
        if isinstance(dns, str):
            dns = [dns]
        result.append({
            "name": a.get("name") or "",
            "mac": mac,
            "desc": desc,
            "status": a.get("status") or "",
            "media": a.get("media") or "",
            "dhcp": a.get("dhcp") or "",
            "ip": a.get("ip") or "",
            "prefix": int(a.get("prefix") or 0),
            "gateway": a.get("gateway") or "",
            "dns": [d for d in dns if d],
        })
    if not include_all and not result:
        raise AdapterError("未检测到任何可用网卡（无 MAC 的虚拟网卡与蓝牙网卡已被过滤；"
                           "如需查看全部可尝试恢复出厂过滤器）")
    return result


def is_connected(adapter):
    """Whether the adapter is effectively in use.

    Some drivers (and ICS networks) report media state inconsistently:
    an adapter that is Up and holds a live IPv4 with a gateway is treated
    as connected even when media state says otherwise.
    """
    if adapter.get("status", "").lower() != "up":
        return False
    if adapter.get("media", "").lower() == "connected":
        return True
    return bool(adapter.get("ip")) and bool(adapter.get("gateway"))


def find_by_mac(adapters, mac):
    from ..storage import normalize_mac
    m = normalize_mac(mac)
    for a in adapters:
        if a["mac"] == m:
            return a
    return None
