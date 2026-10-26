"""IP math helpers (mask <-> prefix, validation)"""
import re

_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")


def valid_ipv4(value):
    if not value or not _IPV4_RE.match(value):
        return False
    return all(0 <= int(p) <= 255 for p in value.split("."))


def mask_to_prefix(mask):
    if not valid_ipv4(mask):
        return 0
    bits = "".join(bin(int(p))[2:].zfill(8) for p in mask.split("."))
    # contiguous ones check (a valid netmask must be 1*0*)
    if "01" in bits:
        return 0
    return bits.count("1")


def prefix_to_mask(prefix):
    if not 0 <= int(prefix) <= 32:
        return ""
    bits = "1" * int(prefix) + "0" * (32 - int(prefix))
    return ".".join(str(int(bits[i:i + 8], 2)) for i in range(0, 32, 8))


def effective_dns(prof, settings=None):
    """Resolve (dns1, dns2) a NIC group will actually use.

    dns_mode: 'global' (default), 'custom', 'dhcp'.
    Empty dns1 means "let DHCP provide DNS".
    """
    mode = (prof or {}).get("dns_mode", "global")
    if mode == "custom":
        return ((prof.get("dns1") or "").strip(), (prof.get("dns2") or "").strip())
    if mode == "dhcp":
        return ("", "")
    s = settings or {}
    if s.get("global_dns_enabled"):
        return ((s.get("global_dns1") or "").strip(), (s.get("global_dns2") or "").strip())
    return ("", "")
