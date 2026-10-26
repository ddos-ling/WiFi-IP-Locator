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
