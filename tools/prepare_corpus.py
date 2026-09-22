"""Rebuild the pinned stage-one corpus; never run implicitly during validation."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import struct
import subprocess
import wave

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "ea99364f61c14656440e8d77e9c233ccf3124633"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, default=ROOT / "target/upstream/minimp3")
    args = parser.parse_args()
    source = args.upstream.resolve()
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != COMMIT:
        raise SystemExit("Unexpected upstream commit")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
        raise SystemExit("Upstream tracked files were modified; refusing to label them as the pinned commit")
    corpus = ROOT / "tests/corpus"
    for name in ("upstream", "generated", "abnormal"):
        (corpus / name).mkdir(parents=True, exist_ok=True)
    entries = []

    def add(path, kind, origin, **extra):
        item = {"id": path.stem, "category": kind, "path": path.relative_to(ROOT).as_posix(),
                "sha256": digest(path), "bytes": path.stat().st_size, "origin": origin, **extra}
        entries.append(item)
        return item

    for path in sorted((source / "vectors").glob("*.bit")):
        if ((path.name.startswith("l3-") and "nonstandard" not in path.name)
                or path.name.startswith("M2L3_")):
            dest = corpus / "upstream" / path.name
            reference = path.with_suffix(".pcm")
            shutil.copyfile(path, dest)
            shutil.copyfile(reference, dest.with_suffix(".pcm"))
            category = ("out_of_scope" if path.name == "l3-he_mode.bit" else
                        "boundary" if path.name in ("l3-compl.bit", "l3-sin1k0db.bit") else "normal")
            add(dest, category, f"minimp3@{COMMIT}/vectors/{path.name}",
                reference_pcm=dest.with_suffix(".pcm").relative_to(ROOT).as_posix(),
                reference_sha256=digest(reference))
    abnormal = ["l3-nonstandard-small.bit", "l3-nonstandard-sideinfo-size.bit",
                "l3-nonstandard-compl-sideinfo-bigvalues.bit",
                "l3-nonstandard-compl-sideinfo-blocktype.bit",
                "l3-nonstandard-compl-sideinfo-size.bit",
                "l3-nonstandard-vbrtag-corrupted.bit", "l3-nonstandard-vbrtag-oob-read.bit",
                "l3-nonstandard-he_44_48khz.bit"]
    for name in abnormal:
        dest = corpus / "abnormal" / name
        shutil.copyfile(source / "vectors" / name, dest)
        add(dest, "abnormal", f"minimp3@{COMMIT}/vectors/{name}")
    temp = ROOT / "target/corpus-source"
    temp.mkdir(parents=True, exist_ok=True)
    ffmpeg_version = subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0]
    for i, rate in enumerate((8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000, 44100)):
        tagged = i == 9
        channels = 2 if tagged or i % 2 == 0 else 1
        mode = ("cbr", "vbr", "abr")[i % 3] if not tagged else "vbr"
        name = "generated-gapless-tagged" if tagged else f"generated-{rate}-{channels}ch-{mode}"
        wav = temp / (name + ".wav")
        frames = rate * 7 // 20
        with wave.open(str(wav), "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(2)
            out.setframerate(rate)
            # Two distinct chirps with a smooth envelope detect swaps/shifts/gain.
            samples = []
            for n in range(frames):
                envelope = min(1, n / 100, (frames - 1 - n) / 100)
                for channel in range(channels):
                    phase = 2 * math.pi * ((233 + 178 * channel) * n / rate + 137 * (n/rate)**2)
                    samples.append(round(13000 * envelope * math.sin(phase)))
            out.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        dest = corpus / "generated" / (name + ".mp3")
        bitrate = "24k" if rate < 16000 else "64k" if rate < 32000 else "128k"
        options = ["-b:a", bitrate] if mode == "cbr" else ["-q:a", "4"] if mode == "vbr" else ["-abr", "1", "-b:a", bitrate]
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
               "-map_metadata", "-1", "-c:a", "libmp3lame", *options,
               "-write_xing", "1" if tagged else "0", "-id3v2_version", "4" if tagged else "0", str(dest)]
        subprocess.run(cmd, check=True, timeout=30)
        add(dest, "alignment" if tagged else "normal", "deterministic synthetic chirp encoded with libmp3lame",
            sample_rate=rate, channels=channels, source_frames_per_channel=frames,
            mode=mode, ffmpeg_version=ffmpeg_version,
            command=[part.replace(str(ROOT), "<ROOT>") for part in cmd])
    valid = (corpus / "generated/generated-44100-1ch-vbr.mp3").read_bytes()
    rng = random.Random(20260921)
    generated_bad = {
        "empty": b"", "random-seed-20260921": bytes(rng.randrange(256) for _ in range(1024)),
        "truncated-header": valid[:3], "truncated-tail": valid[:-17],
        "id3-truncated": b"ID3\x04\x00\x00\x00\x00\x01\x00hello",
        "id3-bad-synchsafe": b"ID3\x04\x00\x00\x80\x00\x00\x00",
        "id3-huge-declaration": b"ID3\x04\x00\x00\x7f\x7f\x7f\x7f",
        "false-sync": b"\xff\xfb\xfc\x00" * 100,
    }
    for name, content in generated_bad.items():
        dest = corpus / "abnormal" / (name + ".bit")
        dest.write_bytes(content)
        add(dest, "abnormal", "deterministic malformed boundary fixture")
    manifest = {"upstream_commit": COMMIT, "note": "Selected Layer III inputs, not a count of ISO conformance cases.",
                "cases": entries}
    (corpus / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(entries)} cases")


if __name__ == "__main__":
    main()
