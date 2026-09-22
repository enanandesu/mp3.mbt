"""Reproduce real consecutive-frame inputs used by decoder state tests.

Fixtures are unchanged byte slices from the committed corpus. Expected state
behavior is asserted directly by tests; no execution report is generated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("decoder_stereo_frames", "tests/corpus/generated/generated-32000-2ch-cbr.mp3", 4),
    ("decoder_mono_frames", "tests/corpus/generated/generated-44100-1ch-vbr.mp3", 2),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "tests/corpus/manifest.json").read_text())
    hashes = {row["path"]: row["sha256"] for row in manifest["cases"]}
    lines = []
    for name, path, count in CASES:
        data = (ROOT / path).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != hashes[path]:
            raise SystemExit("Corpus source does not match committed manifest.")
        assert not data.startswith(b"ID3")
        lines += [f"// Unmodified source: {path}", f"// SHA-256: {digest}",
                  "///|", f"let {name} : Array[Bytes] = ["]
        offset = 0
        for _ in range(count):
            h = data[offset:offset + 4]
            assert h[0] == 255 and h[1] & 0xFE == 0xFA
            kbps = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160,
                    192, 224, 256, 320][h[2] >> 4]
            rate = [44100, 48000, 32000][(h[2] >> 2) & 3]
            length = 144000 * kbps // rate + ((h[2] >> 1) & 1)
            frame = data[offset:offset + length]
            assert len(frame) == length and length > 36
            lines += [f"  // Bytes [{offset}, {offset + length}).",
                      '  b"' + "".join(f"\\x{b:02x}" for b in frame) + '",']
            offset += length
        lines += ["]", ""]
    generated = subprocess.check_output(["moonfmt", "-"],
        input="\n".join(lines).encode(), cwd=ROOT).decode().replace("\r\n", "\n")
    dest = ROOT / "internal/layer3/decoder_wbtest.mbt"
    source = dest.read_text(encoding="utf-8")
    start = "// BEGIN GENERATED DECODER STATE INPUTS\n"
    end = "// END GENERATED DECODER STATE INPUTS"
    updated = source.split(start)[0] + start + "\n" + generated + end + source.split(end)[1]
    if args.check:
        if updated != source:
            raise SystemExit("Decoder state fixtures differ; regenerate and review.")
        print("Verified 6 unchanged continuous-frame inputs for decoder state tests")
    else:
        dest.write_text(updated, encoding="utf-8", newline="\n")
        print("Generated 6 unchanged continuous-frame inputs for decoder state tests")


if __name__ == "__main__":
    main()
