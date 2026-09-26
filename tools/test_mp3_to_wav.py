"""Build the native example and verify WAV metadata, PCM, and failure cleanup."""

import json
import math
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

from verify_environment import ROOT, moon_environment


CASES = ("l3-he_32khz", "M2L3_compl24", "M2L3_noise")


def main():
    env = moon_environment()
    subprocess.run(
        ["moon", "build", "examples/mp3-to-wav", "--target", "native", "--release", "--deny-warn"],
        cwd=ROOT, env=env, check=True,
    )
    base = ROOT / "_build/native/release/build/examples/mp3-to-wav/mp3-to-wav"
    executable = next((path for path in (base.with_suffix(".exe"), base) if path.is_file()), None)
    assert executable is not None, f"Native WAV example was not produced: {base}"
    manifest = {case["id"]: case for case in json.loads(
        (ROOT / "tests/corpus/manifest.json").read_text(encoding="utf-8"))["cases"]}
    policy = json.loads((ROOT / "tests/reference_policy.json").read_text(encoding="utf-8"))
    (ROOT / "target").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wav-cli-", dir=ROOT / "target") as directory:
        folder = Path(directory)
        for name in CASES:
            item = manifest[name]
            expected = policy["expected"][name]["metadata"]
            output = folder / f"{name}.wav"
            command = [str(executable), str(ROOT / item["path"]), str(output)]
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
            with wave.open(str(output), "rb") as audio:
                assert audio.getnchannels() == expected["channels"], name
                assert audio.getframerate() == expected["sample_rate"], name
                assert audio.getsampwidth() == 2, name
                assert audio.getnframes() * audio.getnchannels() == expected["sample_count"], name
                actual = audio.readframes(audio.getnframes())
            assert output.stat().st_size == 44 + len(actual), name
            reference = (ROOT / item["reference_pcm"]).read_bytes()
            comparable = min(len(actual), len(reference))
            comparable -= comparable % 2
            samples = struct.unpack(f"<{comparable // 2}h", actual[:comparable])
            baseline = struct.unpack(f"<{comparable // 2}h", reference[:comparable])
            mse = sum((a - b) ** 2 for a, b in zip(samples, baseline)) / len(samples)
            psnr = math.inf if mse == 0 else 10 * math.log10(32768 ** 2 / mse)
            assert psnr >= 96, (name, psnr)
            original = output.read_bytes()
            repeated = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            assert repeated.returncode != 0 and output.read_bytes() == original, name
            print(f"{name}: {expected['sample_rate']} Hz, {expected['channels']} ch, "
                  f"{expected['sample_count']} samples, {psnr:.2f} dB; existing output kept")
        failed_output = folder / "invalid.wav"
        failed = subprocess.run(
            [str(executable), str(ROOT / manifest["l3-compl"]["path"]), str(failed_output)],
            cwd=ROOT, capture_output=True, text=True,
        )
        assert failed.returncode != 0 and not failed_output.exists(), failed
        print("truncated input: nonzero exit and no partial WAV")


if __name__ == "__main__":
    main()
