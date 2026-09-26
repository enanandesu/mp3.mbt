"""Verify the local reference toolchain and canonical upstream Git blobs.

Use --record explicitly only when intentionally establishing a new baseline.
Normal validation never rewrites the lock.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tomllib

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
            "gcc": ["-dumpfullversion"], "cc": ["-dumpfullversion"], "ar": ["--version"],
            "python": ["--version"], "node": ["--version"],
            "ffmpeg": ["-version"], "ffprobe": ["-version"]}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def platform_lock():
    """Keep the original Windows baseline; other platforms get separate locks."""
    if platform.system() == "Windows" and platform.machine() == "AMD64":
        return LOCK
    return ROOT / "tools" / f"toolchain.{platform.system().lower()}-{platform.machine().lower()}.lock.json"


def moon_environment():
    env = os.environ.copy()
    if platform.system() == "Windows":
        archiver = shutil.which("ar")
        if not archiver:
            raise RuntimeError("Required tool not found: ar")
        env["MOON_CC"] = str(ROOT / "tools/moon-cc-mingw.cmd")
        env["MOON_AR"] = archiver
    return env


def current(tool_names=None):
    for name, expected in UPSTREAM.items():
        if sha(ROOT / "third_party/minimp3" / name) != expected:
            raise RuntimeError(f"Pinned upstream content changed: {name}")
    tools = {}
    commands = dict(COMMANDS)
    if platform.system() == "Linux":
        commands["time"] = ["--version"]
    if tool_names is not None:
        commands = {name: args for name, args in commands.items() if name in tool_names}
    for name, args in commands.items():
        executable = shutil.which(name)
        if name == "python" and not executable:
            executable = shutil.which("python3")
        if not executable:
            raise RuntimeError(f"Required tool not found: {name}")
        process = subprocess.run([executable, *args], capture_output=True, text=True, check=True)
        version = (process.stdout or process.stderr).splitlines()[0].strip()
        tools[name] = {"version": version, "executable_sha256": sha(executable)}
    formatter = shutil.which("moonfmt")
    if not formatter:
        raise RuntimeError("Required tool not found: moonfmt")
    tools["moonfmt"] = {"executable_sha256": sha(formatter)}
    core = Path(shutil.which("moon")).resolve().parents[1] / "lib/core/moon.mod"
    tools["moonbitlang/core"] = {"version": tomllib.loads(core.read_text(encoding="utf-8"))["version"],
                                 "manifest_sha256": sha(core)}
    return {"system": platform.system(), "machine": platform.machine(),
            "upstream_commit": "ea99364f61c14656440e8d77e9c233ccf3124633",
            "upstream_files": UPSTREAM, "tools": tools}


def verify():
    actual = current()
    lock = platform_lock()
    if not lock.is_file():
        raise RuntimeError(f"No reviewed toolchain baseline for this platform: {lock.name}")
    expected = json.loads(lock.read_text(encoding="utf-8"))
    if actual != expected:
        changed = [name for name in sorted(actual["tools"].keys() | expected["tools"].keys())
                   if actual["tools"].get(name) != expected["tools"].get(name)]
        detail = ", ".join(changed) or "platform or upstream identity"
        raise RuntimeError(f"Toolchain differs from tools/{lock.name}: {detail}; "
                           "review and recalibrate explicitly")
    return actual


def verify_portable_tools():
    """Verify pure decoder test tools without claiming full reference parity.

    Hosted C/Python system tools are recorded, while MoonBit/core/Node and
    upstream are strictly checked against the platform lock. PCM reference
    gates must keep calling verify().
    """
    pinned = {"moon", "moonc", "moonrun", "moonfmt", "moonbitlang/core", "node"}
    observed = {"gcc", "cc", "ar", "python"}
    actual = current(pinned | observed)
    lock = platform_lock()
    if not lock.is_file():
        raise RuntimeError(f"No reviewed toolchain baseline for this platform: {lock.name}")
    expected = json.loads(lock.read_text(encoding="utf-8"))
    for field in ("system", "machine", "upstream_commit", "upstream_files"):
        if actual[field] != expected[field]:
            raise RuntimeError(f"Portable toolchain identity mismatch: {field}")
    for name in sorted(pinned):
        if actual["tools"].get(name) != expected["tools"].get(name):
            raise RuntimeError(f"Portable toolchain differs from tools/{lock.name}: {name}")
    actual["verification_scope"] = "portable-decoder-tools; not a full reference environment"
    actual["observed_host_tools"] = {name: actual["tools"].pop(name) for name in sorted(observed)}
    return actual


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true")
    mode.add_argument("--portable-tools", action="store_true",
                      help="Verify MoonBit/core/Node hashes and record host C/Python identities; not the PCM reference environment")
    args = parser.parse_args()
    if args.record:
        lock = platform_lock()
        lock.write_text(json.dumps(current(), indent=2) + "\n", encoding="utf-8")
        print(f"Recorded {lock}")
    elif args.portable_tools:
        print(json.dumps(verify_portable_tools(), indent=2))
    else:
        verify()
        print("Pinned toolchain and all upstream source hashes verified")
