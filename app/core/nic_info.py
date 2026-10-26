"""Read current network adapter configuration via PowerShell.

Dual channel:
1. Modern cmdlets (Get-NetAdapter / Get-NetIPAddress / ...) - preferred.
2. Legacy WMI (Win32_NetworkAdapter + Win32_NetworkAdapterConfiguration in
   the rarely-broken root/cimv2 namespace) - automatic fallback when the
   cmdlet path fails or returns nothing (e.g. corrupted root/StandardCimv2,
   HRESULT 0x80041010 "invalid class").

Each adapter is serialized as ONE compressed JSON line (no array wrapper,
no array-typed fields) so even partially broken PowerShell environments
can be parsed. Enum values are .NET enum names and culture-invariant.
"""
import json
import re
import subprocess

# ---------------------------------------------------------------- preflight

_PS_PREFLIGHT = (
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
    "Write-Output ('PSVER=' + $PSVersionTable.PSVersion.Major + "
    "';JSON=' + [bool](Get-Command ConvertTo-Json -ErrorAction SilentlyContinue))"
)

_ps_preflight_ok = False


class AdapterError(Exception):
    pass


def _check_environment():
    """One-time capability check so failures get an actionable message.

    A missing Get-NetAdapter cmdlet is NOT fatal here: the WMI fallback
    channel can still enumerate adapters on old or damaged systems.
    """
    global _ps_preflight_ok
    if _ps_preflight_ok:
        return
    proc = _run_ps(_PS_PREFLIGHT, timeout=15)
    m = re.search(r"PSVER=(\d+);JSON=(True|False)", proc["out"])
    if not m:
        raise AdapterError(
            f"PowerShell 预检失败（退出码 {proc['rc']}）："
            f"{proc['err'][:300] or '无输出，可能被执行策略或安全软件拦截'}")
    ver, has_json = int(m.group(1)), m.group(2) == "True"
    if ver < 3:
        raise AdapterError(f"PowerShell 版本过低（{ver}.0，需 3.0+），无法列出网卡")
    if not has_json:
        raise AdapterError("缺少 ConvertTo-Json Cmdlet：需要 PowerShell 3.0+")
    _ps_preflight_ok = True


# ------------------------------------------------------------ channel 1: cmdlet

# Per-adapter output as one compressed JSON line; dns as "a|b" string to
# avoid array-typed fields entirely (some broken environments choke on them)
_PS_QUERY = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Get-NetAdapter -ErrorAction SilentlyContinue | ForEach-Object {
    $n = $_.Name
    $ip = Get-NetIPAddress -InterfaceAlias $n -AddressFamily IPv4 -ErrorAction SilentlyContinue |
          Where-Object { $_.PrefixOrigin -ne 'WellKnown' } | Select-Object -First 1
    $gw = Get-NetRoute -InterfaceAlias $n -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
          Sort-Object RouteMetric | Select-Object -First 1
    $ipif = Get-NetIPInterface -InterfaceAlias $n -AddressFamily IPv4 -ErrorAction SilentlyContinue
    $dnsRec = Get-DnsClientServerAddress -InterfaceAlias $n -AddressFamily IPv4 -ErrorAction SilentlyContinue |
          Select-Object -First 1
    $dns = ''
    if ($dnsRec) { $dns = ($dnsRec.ServerAddresses -join '|') }
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
        dns     = $dns
    } | ConvertTo-Json -Compress
}
"""

# ------------------------------------------------------------ channel 2: WMI

_PS_WMI = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$map = New-Object 'System.Collections.Generic.Dictionary[string,object]'
Get-WmiObject Win32_NetworkAdapterConfiguration -ErrorAction SilentlyContinue | ForEach-Object {
    $map[[string]$_.Index] = $_
}
Get-WmiObject Win32_NetworkAdapter -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.NetConnectionID -eq $null) { return }
    $c = $map[[string]$_.Index]
    if ($c -eq $null) { return }
    $ip = ''
    $prefix = 0
    if ($c.IPAddress -ne $null) {
        for ($i = 0; $i -lt $c.IPAddress.Count; $i++) {
            if ($c.IPAddress[$i] -match '^\d+\.\d+\.\d+\.\d+$') {
                $ip = $c.IPAddress[$i]
                if ($c.IPSubnet -ne $null -and $i -lt $c.IPSubnet.Count) {
                    $bits = 0
                    $ok = $true
                    foreach ($p in $c.IPSubnet[$i].Split('.')) {
                        $v = 0
                        if (-not [int]::TryParse($p, [ref]$v)) { $ok = $false; break }
                        $bits += ([convert]::ToString($v, 2) -replace '0', '').Length
                    }
                    if ($ok) { $prefix = $bits }
                }
                break
            }
        }
    }
    $gw = ''
    if ($c.DefaultIPGateway -ne $null -and $c.DefaultIPGateway.Count -gt 0) { $gw = $c.DefaultIPGateway[0] }
    $dns = ''
    if ($c.DNSServerSearchOrder -ne $null) { $dns = ($c.DNSServerSearchOrder -join '|') }
    $status = 'Other'
    $media = 'Disconnected'
    switch ([int]$_.NetConnectionStatus) {
        0 { $status = 'Disconnected' }
        2 { $status = 'Up'; $media = 'Connected' }
        4 { $status = 'Not Present' }
        5 { $status = 'Disabled' }
        7 { $status = 'Disconnected' }
    }
    [pscustomobject]@{
        name    = [string]$_.NetConnectionID
        mac     = [string]$_.MACAddress
        desc    = [string]$_.Name
        status  = $status
        media   = $media
        dhcp    = $(if ($c.DHCPEnabled) { 'Enabled' } else { 'Disabled' })
        ip      = $ip
        prefix  = $prefix
        gateway = $gw
        dns     = $dns
    } | ConvertTo-Json -Compress
}
"""

_netadapter_ok = None  # None=unknown, True=working, False=confirmed broken


# ---------------------------------------------------------------- plumbing

def _run_ps(script, timeout=20):
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, timeout=timeout, creationflags=flags)
    except FileNotFoundError as exc:
        raise AdapterError("未找到 powershell.exe：系统缺少 Windows PowerShell，无法列出网卡") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("PowerShell 查询超时（可能被安全软件拦截），无法列出网卡") from exc
    except OSError as exc:
        raise AdapterError(f"无法启动 PowerShell：{exc}") from exc
    return {
        "out": proc.stdout.decode("utf-8", errors="replace"),
        "err": proc.stderr.decode("utf-8", errors="replace"),
        "rc": proc.returncode,
    }


def _parse_json_lines(out):
    """Parse one-compressed-JSON-object-per-line output"""
    items = []
    for line in out.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            items.append(json.loads(line))
        except ValueError:
            continue  # skip partial/garbage lines from a broken environment
    return items


_NOISE_PATTERNS = ("wan miniport", "wi-fi direct", "wifi direct",
                   "bluetooth device (personal area network)")


def _normalize(item):
    mac = re.sub(r"[^0-9A-Fa-f]", "", item.get("mac") or "").upper()
    desc = item.get("desc") or ""
    low = desc.lower()
    if not mac:
        return None
    if any(p in low for p in _NOISE_PATTERNS):
        return None
    dns = item.get("dns") or ""
    if isinstance(dns, str):
        dns = [d for d in dns.split("|") if d]
    return {
        "name": item.get("name") or "",
        "mac": mac,
        "desc": desc,
        "status": item.get("status") or "",
        "media": item.get("media") or "",
        "dhcp": item.get("dhcp") or "",
        "ip": item.get("ip") or "",
        "prefix": int(item.get("prefix") or 0),
        "gateway": item.get("gateway") or "",
        "dns": dns,
    }


def _query_netadapter(timeout=20):
    proc = _run_ps(_PS_QUERY, timeout=timeout)
    if proc["rc"] != 0 and not proc["out"].strip():
        raise AdapterError(f"Get-NetAdapter 查询失败（退出码 {proc['rc']}）：{proc['err'][:300]}")
    return _parse_json_lines(proc["out"])


def _query_wmi(timeout=30):
    proc = _run_ps(_PS_WMI, timeout=timeout)
    if proc["rc"] != 0 and not proc["out"].strip():
        raise AdapterError(f"WMI 回退查询失败（退出码 {proc['rc']}）：{proc['err'][:300]}")
    return _parse_json_lines(proc["out"])


def get_adapters(timeout=20, include_all=False):
    """Return list of adapter dicts.

    {name, mac, desc, status, media, dhcp, ip, prefix, gateway, dns[]}
    mac normalized to 12 hex chars uppercase.
    By default adapters without a MAC address and Bluetooth PAN devices
    are excluded (they are useless for IP configuration).

    Tries the modern cmdlet channel first; on failure or empty result
    automatically falls back to legacy WMI (root/cimv2). Raises
    AdapterError with the real cause when both channels fail.
    """
    _check_environment()
    global _netadapter_ok
    raw = []
    if _netadapter_ok is not False:
        try:
            raw = _query_netadapter(timeout)
        except AdapterError:
            if _netadapter_ok is True:
                raise  # worked before: this is a real transient error
            _netadapter_ok = False
        if raw:
            _netadapter_ok = True
        elif _netadapter_ok is None:
            _netadapter_ok = False  # empty result too: try the WMI fallback
    if not raw and _netadapter_ok is False:
        raw = _query_wmi(timeout)

    result = [ad for ad in (_normalize(item) for item in raw) if ad is not None]
    if not include_all and not result:
        raise AdapterError("未检测到任何可用网卡（现代与 WMI 双通道均无结果；"
                           "无 MAC 的虚拟网卡与蓝牙网卡已被过滤）")
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
    m = re.sub(r"[^0-9A-Fa-f]", "", mac or "").upper()
    for a in adapters:
        if a["mac"] == m:
            return a
    return None
