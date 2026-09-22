"""Build scalar references and record repeatability, lengths and numerical errors."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from pcm_compare import compare, read_pcm
from diagnostic_text import normalized

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "target/reference"


class CommandError(RuntimeError):
    def __init__(self, command, result):
        self.returncode = result.returncode
        self.stderr = result.stderr
        super().__init__(f"{command}: exit {result.returncode}: {result.stdout}\n{result.stderr}")


def run(command, timeout=60):
    result = subprocess.run([str(x) for x in command], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise CommandError(command, result)
    return result.stdout


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    for fmt in ("s16", "f32", "f32-to-s16"):
        args = ["gcc", "-std=c99", "-O2", "-ffp-contract=off", "-DMINIMP3_ONLY_MP3", "-DMINIMP3_NO_SIMD"]
        if fmt in ("f32", "f32-to-s16"):
            args.append("-DMINIMP3_FLOAT_OUTPUT")
        if fmt == "f32-to-s16":
            args.append("-DREFERENCE_CONVERT_S16")
        run([*args, "tools/reference_decode.c", "-lm", "-o", OUT / f"decode-{fmt}.exe"])
    run(["gcc", "-O2", "-ffp-contract=off", "-DMINIMP3_ONLY_MP3", "-DMINIMP3_NO_SIMD", "-DMINIMP3_NO_WAV",
         "third_party/minimp3/minimp3_test.c", "-lm", "-o", OUT / "upstream-test.exe"])


def decode(case, fmt, mode="raw", suffix=""):
    base = OUT / (case["id"] + "-" + fmt + "-" + mode + suffix)
    pcm, meta = base.with_suffix(".pcm"), base.with_suffix(".json")
    run([OUT / f"decode-{fmt}.exe", mode, ROOT / case["path"], pcm, meta], timeout=10)
    return pcm, json.loads(meta.read_text())


def ffmpeg_decode(case, fmt, metadata):
    path = OUT / (case["id"] + "-ffmpeg-" + fmt + ".pcm")
    wire = "s16le" if fmt == "s16" else "f32le"
    probe = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                           "stream=sample_rate,channels", "-of", "json", ROOT / case["path"]], timeout=15))["streams"][0]
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-c:a", "mp3float", "-i", ROOT / case["path"],
               "-map", "0:a:0", "-c:a", "pcm_" + wire, "-f", wire, path]
    process = subprocess.run([str(x) for x in command], cwd=ROOT, capture_output=True, text=True, timeout=15)
    if process.returncode:
        raise CommandError(command, process)
    count = path.stat().st_size // (2 if fmt == "s16" else 4)
    return path, {"sample_rate": int(probe["sample_rate"]), "channels": probe["channels"],
                  "format": wire, "sample_count": count,
                  "frames_per_channel": count // probe["channels"]}, process.stderr


def baseline():
    build()
    cases = json.loads((ROOT / "tests/corpus/manifest.json").read_text())["cases"]
    results = {"normal": [], "boundary": [], "abnormal": [], "out_of_scope": [], "alignment": [], "commands": {
        "c_flags": ["-O2", "-ffp-contract=off", "MINIMP3_ONLY_MP3", "MINIMP3_NO_SIMD"],
        "f32_extra": "MINIMP3_FLOAT_OUTPUT",
        "ffmpeg": "ffmpeg -c:a mp3float -i INPUT -map 0:a:0 -c:a pcm_f32le -f f32le OUTPUT"}}
    for case in cases:
        path = ROOT / case["path"]
        if sha(path) != case["sha256"]:
            raise RuntimeError(f"corpus hash mismatch: {path}")
        if "reference_pcm" in case and sha(ROOT / case["reference_pcm"]) != case["reference_sha256"]:
            raise RuntimeError(f"upstream PCM hash mismatch: {path}")
        if case["category"] in ("abnormal", "out_of_scope"):
            try:
                pcm, meta = decode(case, "f32")
                result = {"id": case["id"], "status": "returned", "metadata": meta, "pcm_sha256": sha(pcm)}
            except CommandError as error:
                if error.returncode != 2 or "project contract rejects changing" not in error.stderr:
                    raise
                result = {"id": case["id"], "status": "rejected", "exit_code": error.returncode, "detail": normalized(error.stderr)}
            results[case["category"]].append(result)
            continue
        s16, sm = decode(case, "s16")
        f32, fm = decode(case, "f32")
        repeat, repeat_meta = decode(case, "f32", suffix="-repeat")
        s16_repeat, s16_repeat_meta = decode(case, "s16", suffix="-repeat")
        converted, converted_meta = decode(case, "f32-to-s16")
        sp, fp = read_pcm(s16, "s16le"), read_pcm(f32, "f32le")
        result = {"id": case["id"], "metadata": fm, "s16_sha256": sha(s16), "f32_sha256": sha(f32),
                  "repeat_exact": sha(f32) == sha(repeat) and fm == repeat_meta,
                  "s16_repeat_exact": sha(s16) == sha(s16_repeat) and sm == s16_repeat_meta,
                  "float_to_s16_exact": sha(s16) == sha(converted) and sm == converted_meta}
        if "reference_pcm" in case:
            ref = read_pcm(ROOT / case["reference_pcm"], "s16le")
            refm = {**sm, "sample_count": len(ref)}
            result["upstream_length_delta_samples"] = len(sp) - len(ref)
            result["upstream_strict"] = compare(ref, sp, refm, sm)
            # Calibration ONLY: explicit prefix diagnostic, never the acceptance comparator.
            result["upstream_prefix_diagnostic"] = compare(ref, sp[:len(ref)], refm, refm)
            result["upstream_test"] = normalized(run([OUT / "upstream-test.exe", path, ROOT / case["reference_pcm"]]).strip())
        ff = ffm = None
        try:
            ff, ffm, warnings = ffmpeg_decode(case, "f32", fm)
            result["ffmpeg"] = compare(fp, read_pcm(ff, "f32le"), fm, ffm)
            result["ffmpeg_frames_per_channel"] = ffm["frames_per_channel"]
            result["ffmpeg_sha256"] = sha(ff)
            result["ffmpeg_diagnostics"] = normalized(warnings)
        except CommandError as error:
            result["ffmpeg"] = {"passed": False, "reason": "decoder_rejected", "detail": normalized(str(error))}
        if case["category"] == "alignment":
            if ff is None or ffm is None:
                raise RuntimeError("The gapless alignment case requires a successful independent FFmpeg decode")
            gap, gm = decode(case, "f32", "gapless")
            gp = read_pcm(gap, "f32le")
            result["gapless_metadata"] = gm
            start_frames = fm["first_frame_samples"] + fm["delay"]
            end_frames = fm["padding"]
            channels = fm["channels"]
            end = len(fp) - end_frames * channels
            aligned_samples = fp[start_frames * channels:end]
            result["declared_alignment"] = {"start_frames": start_frames, "end_frames": end_frames,
                "raw_to_gapless": compare(gp, aligned_samples, gm, {**fm, "sample_count": len(aligned_samples)}),
                "gapless_to_ffmpeg": compare(gp, read_pcm(ff, "f32le"), gm, ffm)}
        results[case["category"]].append(result)
        print(f"{case['id']}: {fm['frames_per_channel']} frames/channel, FFmpeg {result['ffmpeg'].get('reason')}", flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "target/reference/baseline.json")
    args = parser.parse_args()
    result = baseline()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
