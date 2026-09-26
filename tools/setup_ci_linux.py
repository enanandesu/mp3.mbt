"""Install checksum-pinned Linux tools below target/ for portable CI checks.

This installs MoonBit, its matching core, and Node without changing the system.
--with-reference additionally installs the separately pinned static FFmpeg.
The full reference gate still requires verify_environment.py to match the
reviewed platform lock, including the host Python and C compiler binaries.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import tarfile
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "target/ci-portability"
ARCHIVES = {
    "moonbit-linux-x86_64.tar.gz": {
        "url": "https://cli.moonbitlang.com/binaries/0.10.14%2B7d59c7ec9/moonbit-linux-x86_64.tar.gz",
        "sha256": "9226694de9ff978db1ecf820b7710c4224e84ec7a76b19a222d96f0cd4e31b6a",
        "destination": "moon",
        # This pinned archive stores native programs as 0664. Do not infer
        # executability from its modes or chmod the adjacent .wasm data files.
        "executables": [
            "bin/moon", "bin/moonc", "bin/moonrun", "bin/moonfmt",
            "bin/mooninfo", "bin/mooncake", "bin/moon-lsp",
            "bin/moon_cove_report", "bin/moon-wasm-opt", "bin/moon-ide",
            "bin/moon-cram", "bin/moondoc", "bin/internal/tcc",
        ],
    },
    "core.tar.gz": {
        "url": "https://cli.moonbitlang.com/cores/core-0.10.14%2B7d59c7ec9.tar.gz",
        "sha256": "6f18b8fdea18f85e628a75e4a1bd3977c5a5c9c6a836fd8824192b0e6bd91b14",
        "destination": "moon/lib",
    },
    "node-linux.tar.xz": {
        "url": "https://nodejs.org/dist/v20.17.0/node-v20.17.0-linux-x64.tar.xz",
        "sha256": "a24db3dcd151a52e75965dba04cf1b3cd579ff30d6e0af9da1aede4d0f17486b",
        "destination": "node",
        "prefix": "node-v20.17.0-linux-x64/",
    },
    "ffmpeg-linux.tar.xz": {
        "url": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
        "sha256": "abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67",
        "destination": "ffmpeg",
        "prefix": "ffmpeg-7.0.2-amd64-static/",
        "reference_only": True,
    },
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(name, specification):
    archive = OUT / "downloads" / name
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.is_file():
        temporary = archive.with_suffix(archive.suffix + ".part")
        print(f"Downloading {name}", flush=True)
        with urllib.request.urlopen(specification["url"], timeout=180) as source:
            with temporary.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
        if digest(temporary) != specification["sha256"]:
            raise RuntimeError(f"Archive checksum mismatch: {name}")
        temporary.replace(archive)
    if digest(archive) != specification["sha256"]:
        raise RuntimeError(f"Cached archive checksum mismatch: {name}")
    destination = OUT / specification["destination"]
    destination.mkdir(parents=True, exist_ok=True)
    prefix = specification.get("prefix", "")
    with tarfile.open(archive) as source:
        members = source.getmembers()
        if prefix:
            for member in members:
                if member.name + "/" == prefix:
                    member.name = "."
                elif member.name.startswith(prefix):
                    member.name = member.name[len(prefix):]
                else:
                    raise RuntimeError(f"Unexpected archive layout: {name}/{member.name}")
        source.extractall(destination, members=members, filter="data")
    # Also runs for cached archives, before any installed tool is invoked.
    for relative_path in specification.get("executables", []):
        executable = destination / relative_path
        executable.chmod(executable.stat().st_mode | 0o111)
    print(f"Verified and installed {name}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-reference", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("This bootstrap is pinned for Linux x86_64 only")
    for name, specification in ARCHIVES.items():
        if not specification.get("reference_only") or args.with_reference:
            install(name, specification)
    aliases = OUT / "bin"
    aliases.mkdir(exist_ok=True)
    python_alias = aliases / "python"
    if not python_alias.exists():
        python_alias.symlink_to(Path(sys.executable).resolve())
    folders = [OUT / "moon/bin", OUT / "node/bin", aliases]
    if args.with_reference:
        folders.append(OUT / "ffmpeg")
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(map(str, folders)) + os.pathsep + env["PATH"]
    for target in ("all", "wasm-gc"):
        command = [str(OUT / "moon/bin/moon"), "-C", str(OUT / "moon/lib/core"),
                   "bundle", "--warn-list", "-a"]
        command += ["--all"] if target == "all" else ["--target", target]
        subprocess.run(command, env=env, check=True, timeout=180)
    exports = "export PATH=" + shlex.quote(os.pathsep.join(map(str, folders))) + ':"$PATH"\n'
    (OUT / "environment.sh").write_text(exports, encoding="utf-8")
    if github_path := os.environ.get("GITHUB_PATH"):
        with open(github_path, "a", encoding="utf-8") as output:
            output.write("\n".join(map(str, folders)) + "\n")
    # Preserve a machine-readable download identity alongside ignored outputs.
    (OUT / "downloads.json").write_text(json.dumps(ARCHIVES, indent=2) + "\n", encoding="utf-8")
    print(f"Local shell: source {OUT / 'environment.sh'}")


if __name__ == "__main__":
    main()
