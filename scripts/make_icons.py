"""Regenerate static/icon-192.png and icon-512.png (black tile, gold and white caption bars). Pure stdlib."""
import struct
import zlib
from pathlib import Path

BLACK, GOLD, WHITE = (17, 17, 17), (201, 162, 39), (255, 255, 255)


def make(size: int) -> bytes:
    s = size / 512
    bars = [(116, 196, 280, 40, GOLD), (156, 276, 200, 40, WHITE)]
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            color = BLACK
            for bx, by, bw, bh, c in bars:
                x0, y0, x1, y1 = bx * s, by * s, (bx + bw) * s, (by + bh) * s
                r = bh * s / 2
                if y0 <= y < y1 and x0 <= x < x1:
                    cx = min(max(x, x0 + r), x1 - r)
                    cy = (y0 + y1) / 2
                    if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                        color = c
            row += bytes(color)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "static"
    for n in (192, 512):
        (out / f"icon-{n}.png").write_bytes(make(n))
        print("wrote", out / f"icon-{n}.png")
