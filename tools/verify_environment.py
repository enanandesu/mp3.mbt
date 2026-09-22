"""Verify the local reference toolchain and canonical upstream Git blobs.

Use --record explicitly only when intentionally establishing a new baseline.
Normal validation never rewrites the lock.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "tools/toolchain.lock.json"
UPSTREAM = {
    "minimp3.h": "57e437c5c1f0e8b243885d3929c8973b5e6c778451e0100ab4251d19915cb3ad",
    "minimp3_ex.h": "8437f3fc1d4d8ab2269a1624f5380a08df1967a048f8887789bae6e25db7db79",
    "minimp3_test.c": "b9432b7143a988613d983c0dfd046a56ba0d69738b852588f350e8876affb122",
    "LICENSE": "6a1ee543e5282cd9061881edf462e6fdab181f328da71fc2c9a6950a80e94d01",
    "README.md": "ce8a219c5783d7b991070a7aca4c31f8dfcafc183925bf947b80b835ed36b45d",
}
COMMANDS = {"moon": ["version"], "moonc": ["-v"], "moonrun": ["--version"],
            "gcc": ["-dumpfullversion"], "cc": ["-dumpfullversion"],
            "python": ["--version"], "node": ["--version"],
            "ffmpeg": ["-version"], "ffprobe": ["-version"]}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def current():
    for name, expected in UPSTREAM.items():
        if sha(ROOT / "third_party/minimp3" / name) != expected:
            raise RuntimeError(f"Pinned upstream content changed: {name}")
    tools = {}
    for name, args in COMMANDS.items():
        executable = shutil.which(name)
        if not executable:
            raise RuntimeError(f"Required tool not found: {name}")
        process = subprocess.run([executable, *args], capture_output=True, text=True, check=True)
        version = (process.stdout or process.stderr).splitlines()[0].strip()
        tools[name] = {"version": version, "executable_sha256": sha(executable)}
    formatter = shutil.which("moonfmt")
    if not formatter:
        raise RuntimeError("Required tool not found: moonfmt")
    tools["moonfmt"] = {"executable_sha256": sha(formatter)}
    core = Path(shutil.which("moon")).resolve().parents[1] / "lib/core/moon.mod.json"
    tools["moonbitlang/core"] = {"version": json.loads(core.read_text())["version"], "manifest_sha256": sha(core)}
    return {"system": platform.system(), "machine": platform.machine(),
            "upstream_commit": "ea99364f61c14656440e8d77e9c233ccf3124633",
            "upstream_files": UPSTREAM, "tools": tools}


def verify():
    actual = current()
    expected = json.loads(LOCK.read_text(encoding="utf-8"))
    if actual != expected:
        raise RuntimeError("Toolchain differs from tools/toolchain.lock.json; review and recalibrate explicitly")
    return actual


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    if args.record:
        LOCK.write_text(json.dumps(current(), indent=2) + "\n", encoding="utf-8")
        print(f"Recorded {LOCK}")
    else:
        verify()
        print("Pinned toolchain and all upstream source hashes verified")
