"""Apply IP profiles via elevated netsh (UAC).

The elevated child is launched with -EncodedCommand (UTF-16LE base64), so
Chinese interface names never travel through raw command-line text and no
codepage issues can occur. Result is written to a temp file and read back.
"""
import base64
import ctypes
import os
import time
import uuid

from .ip_utils import valid_ipv4, effective_dns, mask_to_prefix  # noqa: F401


class ApplyError(Exception):
    pass


def _quote(name):
    return '"' + (name or "").replace('"', '') + '"'


def build_netsh_commands(name, prof, settings=None):
    """Build netsh command list from a profile dict (+ global DNS settings).

    Address follows the profile (DHCP or static); DNS follows dns_mode:
    custom values, global DNS, or DHCP-provided.
    """
    q = _quote(name)
    cmds = []
    if prof.get("dhcp"):
        cmds.append(f'netsh interface ip set address name={q} source=dhcp')
    else:
        ip, mask = prof.get("ip", ""), prof.get("mask", "")
        if not valid_ipv4(ip) or not valid_ipv4(mask):
            raise ApplyError("IP 或子网掩码格式无效")
        addr = f'netsh interface ip set address name={q} source=static addr={ip} mask={mask}'
        if prof.get("gateway"):
            if not valid_ipv4(prof["gateway"]):
                raise ApplyError("网关格式无效")
            addr += f' gateway={prof["gateway"]}'
        cmds.append(addr)

    dns1, dns2 = effective_dns(prof, settings)
    if dns1:
        if not valid_ipv4(dns1):
            raise ApplyError("DNS1 格式无效")
        cmds.append(f'netsh interface ip set dnsservers name={q} source=static address={dns1} register=primary validate=no')
        if dns2:
            if not valid_ipv4(dns2):
                raise ApplyError("DNS2 格式无效")
            cmds.append(f'netsh interface ip add dnsservers name={q} address={dns2} index=2 validate=no')
    else:
        # DNS follows DHCP (explicit dhcp mode, or global DNS disabled)
        cmds.append(f'netsh interface ip set dnsservers name={q} source=dhcp')
    return cmds


_PS_TEMPLATE = r"""
$ErrorActionPreference = 'Continue'
$log = New-Object System.Collections.Generic.List[string]
$log.Add('BEGIN')
$cmds = @(
__CMDS__
)
foreach ($c in $cmds) {
    $log.Add("RUN: $c")
    Invoke-Expression $c 2>&1 | ForEach-Object { $log.Add([string]$_) }
    $log.Add("EXIT=$LASTEXITCODE")
}
$log.Add('DONE')
Set-Content -LiteralPath '__RESULT__' -Value $log -Encoding UTF8
"""


def apply_profile(name, prof, settings=None, timeout=60):
    """Apply a profile to adapter `name` (UAC elevation).

    Returns (success: bool, output_text: str)
    """
    cmds = build_netsh_commands(name, prof, settings)
    result_path = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")),
                               f"wifiip_apply_{uuid.uuid4().hex}.log")
    if os.path.exists(result_path):
        os.remove(result_path)

    ps_lines = ",\n".join(f"    '{c}'" for c in cmds)
    script = _PS_TEMPLATE.replace("__CMDS__", ps_lines).replace("__RESULT__", result_path)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")

    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "powershell.exe",
        f"-NoProfile -WindowStyle Hidden -EncodedCommand {encoded}", None, 0)
    if rc <= 32:
        raise ApplyError("提权被取消或失败（UAC 未确认）")

    deadline = time.time() + timeout
    text = ""
    while time.time() < deadline:
        try:
            with open(result_path, "r", encoding="utf-8-sig") as f:
                text = f.read()
            if "DONE" in text:
                break
        except OSError:
            pass
        time.sleep(0.5)
    else:
        raise ApplyError("等待应用结果超时")

    try:
        os.remove(result_path)
    except OSError:
        pass

    ok = "EXIT=0" in text
    return ok, text.strip()
