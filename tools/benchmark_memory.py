"""Measure OS peak resident memory of the release native MP3-to-WAV example.

This is whole-process memory, including startup, file I/O and WAV conversion;
it must not be presented as decoder-only memory or compared to V8 heap bytes.
"""
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import wave

from verify_environment import ROOT, moon_environment, verify

OUT = ROOT / "target/performance-memory"
CASES = ("l3-he_32khz", "M2L3_compl24", "generated-8000-2ch-cbr")


def peak_process(command, log):
    """Read the kernel's per-process high water mark, never a sampling maximum."""
    with log.open("wb") as stdout:
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        peak_file = log.with_suffix(".peak-kib")
        invocation = command
        if platform.system() == "Linux":
            # Direct Python wait4 measurements inherit Python's pre-exec RSS floor.
            # GNU time forks the measured program after its own small runtime starts.
            if not Path("/usr/bin/time").is_file():
                raise RuntimeError("Native Linux peak measurement requires GNU time at /usr/bin/time")
            invocation = ["/usr/bin/time", "-f", "%M", "-o", str(peak_file), "--", *command]
        process = subprocess.Popen(invocation, cwd=ROOT, stdout=stdout,
                                   stderr=subprocess.STDOUT, **kwargs)
        try:
            if platform.system() == "Windows":
                class Counters(ctypes.Structure):
                    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
                        (name, ctypes.c_size_t) for name in (
                            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                            "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
                counters = Counters()
                counters.cb = ctypes.sizeof(counters)
                get_memory = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
                get_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
                get_memory.restype = ctypes.c_int
                process.wait(timeout=60)
                # Popen retains the kernel process handle after wait, preserving the peak counter.
                if not get_memory(int(process._handle), ctypes.byref(counters), counters.cb):
                    raise ctypes.WinError(ctypes.get_last_error())
                peak = counters.PeakWorkingSetSize
                method = "Windows GetProcessMemoryInfo.PeakWorkingSetSize after process exit"
            elif platform.system() == "Linux":
                process.wait(timeout=60)
                peak = int(peak_file.read_text().strip()) * 1024 if not process.returncode else 0
                method = "Linux GNU time %M child rusage.ru_maxrss (KiB converted to bytes)"
            else:
                raise RuntimeError(f"Unsupported peak accounting platform: {platform.system()}")
            if process.returncode:
                raise RuntimeError(f"Native decoder failed ({process.returncode}): {log.read_text()}")
            if peak <= 0:
                raise RuntimeError("Kernel did not return a positive process memory high water mark")
            return peak, method
        finally:
            if process.returncode is None:
                process.kill()
                process.wait()


def main():
    environment = verify()
    subprocess.run(["moon", "build", "examples/mp3-to-wav", "--target", "native", "--release",
                    "--deny-warn"], cwd=ROOT, env=moon_environment(), check=True)
    # This pinned Moon build uses .exe for native executable artifacts on Linux too.
    executable = ROOT / "_build/native/release/build/examples/mp3-to-wav/mp3-to-wav.exe"
    if not executable.is_file():
        raise RuntimeError(f"Missing release native example: {executable}")
    cases = {item["id"]: item for item in json.loads(
        (ROOT / "tests/corpus/manifest.json").read_text(encoding="utf8"))["cases"]}
    policy = json.loads((ROOT / "tests/reference_policy.json").read_text(encoding="utf8"))
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix="native-", dir=OUT) as temporary:
        folder = Path(temporary)
        for name in CASES:
            item = cases[name]
            source = ROOT / item["path"]
            assert hashlib.sha256(source.read_bytes()).hexdigest() == item["sha256"], name
            expected = policy["expected"][name]["metadata"]
            samples = []
            for repeat in range(3):
                destination = folder / f"{name}-{repeat}.wav"
                peak, method = peak_process([str(executable), str(source), str(destination)],
                                            folder / f"{name}-{repeat}.log")
                with wave.open(str(destination), "rb") as wav:
                    assert wav.getframerate() == expected["sample_rate"], name
                    assert wav.getnchannels() == expected["channels"], name
                    assert wav.getnframes() * wav.getnchannels() == expected["sample_count"], name
                    assert wav.getsampwidth() == 2, name
                assert destination.stat().st_size == 44 + expected["sample_count"] * 2, name
                samples.append(peak)
            rows.append({"case": name, "input_sha256": item["sha256"], "input_bytes": source.stat().st_size,
                         "peak_resident_bytes": samples, "max_peak_resident_bytes": max(samples)})
            print(f"{name}: native process peaks {[round(n / 1048576, 3) for n in samples]} MiB")
    report = {"date_utc": datetime.now(timezone.utc).isoformat(), "system": platform.platform(),
              "processor": platform.processor(), "moon": environment["tools"]["moon"]["version"],
              "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
              "method": method, "scope": "3 fresh release native MP3-to-WAV processes per case; "
              "includes runtime, input, decoded PCM, WAV conversion and I/O; not decoder-only memory", "results": rows}
    if platform.system() == "Linux":
        report["gnu_time"] = {"version": subprocess.check_output(
            ["/usr/bin/time", "--version"], text=True).splitlines()[0],
            "executable_sha256": hashlib.sha256(Path("/usr/bin/time").read_bytes()).hexdigest()}
    (OUT / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")


if __name__ == "__main__":
    main()
