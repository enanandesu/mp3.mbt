"""Reproduce MPEG1 scalefactor, Huffman, linbits/count1 and f32 oracle vectors."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "ea99364f61c14656440e8d77e9c233ccf3124633"
SHA = "57e437c5c1f0e8b243885d3929c8973b5e6c778451e0100ab4251d19915cb3ad"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    raw = (ROOT / "third_party/minimp3/minimp3.h").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA
    source = raw.decode()
    def table(name: str) -> list[int]:
        match = re.search(r"\b" + name + r"\[[^]]*\]\s*=\s*\{([^}]+)\}", source)
        assert match
        return [int(x.strip()) for x in match[1].split(",") if x.strip()]
    tabs, indices, linbits = table("tabs"), table("tabindex"), table("g_linbits")
    count32, count33 = table("tab32"), table("tab33")

    def codes(tab: int) -> dict[tuple[int, int], str]:
        result: dict[tuple[int, int], str] = {}
        def visit(offset: int, width: int, prefix: str) -> None:
            for index in range(1 << width):
                leaf = tabs[indices[tab] + offset + index]
                digits = format(index, f"0{width}b")
                if leaf < 0:
                    visit(-(leaf >> 3), leaf & 7, prefix + digits)
                else:
                    key = (leaf & 15, (leaf >> 4) & 15)
                    code = prefix + digits[:leaf >> 8]
                    assert key not in result or result[key] == code
                    result[key] = code
        visit(0, 5, "")
        return result

    def count_codes(choice: int) -> dict[int, str]:
        tab = count33 if choice else count32
        result: dict[int, str] = {}
        for index in range(64):
            bits = format(index, "06b")
            leaf = tab[int(bits[:4], 2)]
            if not leaf & 8:
                leaf = tab[(leaf >> 3) + int(bits[4:4 + (leaf & 3)], 2)]
            code = bits[:leaf & 7]
            mask = leaf >> 4
            assert mask not in result or result[mask] == code
            result[mask] = code
        assert len(result) == 16
        return result

    requests, specs = [], []
    for layout in range(3):
        for compress in range(16):
            for reuse in (range(16) if layout == 0 else [0]):
                ident = len(specs)
                spec = [layout, compress, reuse, (ident * 29) % 256,
                        ident % 2, (ident // 2) % 2, (ident // 3) % 2, ident % 2]
                specs.append(spec)
                requests.append("0 " + str(ident) + " " + " ".join(map(str, spec)))
    huffman = []
    def add_huffman(tab: int, big: int, choice: int, digits: str) -> None:
        padded = digits + "0" * ((-len(digits)) % 8)
        data = [int(padded[i:i + 8], 2) for i in range(0, len(padded), 8)]
        ident = len(huffman)
        huffman.append([tab, big, choice, len(digits), data])
        requests.append("1 " + " ".join(map(str, [ident, tab, big, choice, len(digits), len(data), *data])))
    for tab in range(32):
        if tab in (4, 14):
            continue
        mapping = codes(tab)
        keys = sorted(mapping)
        for variation in range(3):
            digits = ""
            for pair in range(12):
                x, y = keys[(pair * 17 + variation * (len(keys) - 1)) % len(keys)]
                digits += mapping[x, y]
                for side, magnitude in enumerate([x, y]):
                    if magnitude == 15 and linbits[tab]:
                        extra = ((pair * 113 + variation * ((1 << linbits[tab]) - 1)) % (1 << linbits[tab]))
                        digits += format(extra, f"0{linbits[tab]}b")
                    if magnitude:
                        digits += str((pair + side + variation) % 2)
            add_huffman(tab, 12, variation % 2, digits)
        # Every distinct tree leaf, including long multi-level codewords.
        digits = ""
        for pair, (x, y) in enumerate(keys):
            digits += mapping[x, y]
            for side, magnitude in enumerate([x, y]):
                if magnitude == 15 and linbits[tab]:
                    extra = (1 << linbits[tab]) - 1
                    digits += format(extra, f"0{linbits[tab]}b")
                if magnitude:
                    digits += str((pair + side) % 2)
        add_huffman(tab, len(keys), 0, digits)
    for choice in range(2):
        mapping = count_codes(choice)
        for variation in range(4):
            digits = ""
            for group in range(16):
                mask = (group + variation * 3) % 16
                digits += mapping[mask]
                for value in range(4):
                    if mask & (8 >> value):
                        digits += str((group + value + variation) % 2)
            add_huffman(0, 0, choice, digits)
    # 287 zero big-value pairs leave exactly two output slots. Table 33's
    # other two sign bits are deliberately absent: C stops at the band sentinel.
    add_huffman(0, 287, 1, "000001")
    powers = list(range(129)) + [129,130,191,192,255,256,511,512,1023,1024,1025,2047,4095,8191,8206]
    for ident, value in enumerate(powers):
        requests.append(f"2 {ident} {value}")
    build = ROOT / "target/reference/spectral-oracle"
    build.mkdir(parents=True, exist_ok=True)
    exe = build / ("spectral.exe" if os.name == "nt" else "spectral")
    subprocess.run([args.cc, "-std=c99", "-O2", "-ffp-contract=off", "-Wall", "-Wextra",
                    str(ROOT / "tools/spectral_oracle.c"), "-o", str(exe), "-lm"], check=True, cwd=ROOT)
    result = subprocess.check_output([str(exe)], input=("\n".join(requests) + "\n").encode(), cwd=ROOT).decode()
    rows = [line.split(",") for line in result.splitlines()]
    assert len(rows) == len(requests)
    lines = ["// Generated by tools/generate_spectral_vectors.py; do not edit.",
             f"// Scalar minimp3 oracle: {COMMIT} (CC0-1.0).", f"// Source SHA-256: {SHA}",
             "// Complete codewords only. Malformed final groups are tested separately.",
             "///|", "let spectral_scalefactor_vectors : Array[Array[Int]] = ["]
    for row in rows:
        if row[0] == "S":
            values = list(map(int, row[1:]))
            ident = values[0]
            signed = [v if v < 2147483648 else v - 4294967296 for v in values[1:]]
            lines.append("  [" + ", ".join(map(str, [ident, *specs[ident], *signed])) + "],")
    lines += ["]", "///|", "let spectral_huffman_inputs : Array[Array[Int]] = ["]
    for tab, big, choice, length, data in huffman:
        lines.append("  [" + ", ".join(map(str, [tab, big, choice, length, *data])) + "],")
    lines += ["]", "///|", "let spectral_huffman_expected : Array[Array[Int]] = ["]
    for row in rows:
        if row[0] == "H":
            bits = list(map(int, row[3:]))
            # Exact f32 bits for nonzero prefix; check every other sample is zero.
            end = max((i + 1 for i, v in enumerate(bits) if v), default=0)
            signed = [v if v < 2147483648 else v - 4294967296 for v in bits[:end]]
            lines.append("  [" + ", ".join(map(str, [int(row[2]), *signed])) + "],")
    lines += ["]", "///|", "let spectral_power_vectors : Array[(Int, Int)] = ["]
    for row in rows:
        if row[0] == "P":
            lines.append(f"  ({powers[int(row[1])]}, {row[2]}),")
    lines += ["]", ""]
    data = subprocess.check_output(["moonfmt", "-"], input="\n".join(lines).encode(), cwd=ROOT).replace(b"\r\n", b"\n")
    path = ROOT / "internal/layer3/spectral_vectors_wbtest.mbt"
    if args.check:
        if path.read_bytes() != data:
            raise SystemExit("Spectral vectors differ; regenerate and review")
        print(f"Verified {len(rows)} scalar spectral oracle cases")
    else:
        path.write_bytes(data)
        print(f"Generated {len(rows)} scalar spectral oracle cases")


if __name__ == "__main__":
    main()
