"""Wrap a PNG file into an ICO container (PNG-compressed entry, Vista+).

Usage: python make_ico.py input.png output.ico
The input PNG must be 256x256.
"""
import struct
import sys


def main():
    if len(sys.argv) != 3:
        print("usage: make_ico.py <input.png> <output.ico>")
        sys.exit(1)
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, "rb") as f:
        png = f.read()

    # verify PNG signature and IHDR size
    if png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR":
        print("ERROR: not a valid PNG file")
        sys.exit(1)
    import struct as _s
    w = _s.unpack(">I", png[16:20])[0]
    h = _s.unpack(">I", png[20:24])[0]
    if w != 256 or h != 256:
        print(f"ERROR: PNG must be 256x256, got {w}x{h}")
        sys.exit(1)

    ico = struct.pack("<HHH", 0, 1, 1)                      # reserved, type=icon, count=1
    ico += struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)  # 0 => 256px
    ico += png
    with open(dst, "wb") as f:
        f.write(ico)
    print(f"OK: wrote {dst} ({len(ico)} bytes)")


if __name__ == "__main__":
    main()
