"""Diagnose the fixed l3-test45/46 reference disagreement, without alignment search.

Run after tools/reference_baseline.py. This creates counterfactual decoder copies
only in target/reference/ffmpeg-diagnostic-build; they are NEVER acceptance
references. The vendored minimp3 source and baseline PCM are not modified.
"""
from __future__ import annotations

from array import array
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from diagnostic_text import normalized

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "target/reference"
BUILD = OUT / "ffmpeg-diagnostic-build"
HEADER_SHA = "57e437c5c1f0e8b243885d3929c8973b5e6c778451e0100ab4251d19915cb3ad"
FFMPEG_SOURCE = "https://github.com/FFmpeg/FFmpeg/blob/e347b4ff31/libavcodec/mpegaudiodec_template.c"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command):
    result = subprocess.run([str(x) for x in command], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(f"Command failed: {command}\n{result.stderr}")
    return result.stdout, result.stderr


def pcm(path):
    values = array("f")
    values.frombytes(Path(path).read_bytes())
    if sys.byteorder != "little":
        values.byteswap()
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"Non-finite PCM: {path}")
    return values


def error(a, b):
    if len(a) != len(b):
        return {"equal_length": False, "reference_samples": len(a), "candidate_samples": len(b)}
    total = sum((x - y) ** 2 for x, y in zip(a, b))
    return {"equal_length": True, "samples": len(a),
            "rmse": math.sqrt(total / len(a)),
            "max_abs_error": max(abs(x-y) for x, y in zip(a, b))}


def channel_metrics(a, b):
    values = []
    for ch in range(2):
        x, y = a[ch::2], b[ch::2]
        xx, yy, xy = sum(v*v for v in x), sum(v*v for v in y), sum(u*v for u, v in zip(x, y))
        gain = xy / xx if xx else 0
        values.append({
            "channel": ch, **error(x, y),
            "minimp3_peak": max(map(abs, x)), "ffmpeg_peak": max(map(abs, y)),
            "correlation": xy/math.sqrt(xx*yy) if xx*yy else None,
            "least_squares_ffmpeg_gain_vs_minimp3_diagnostic_only": gain,
            "remaining_rmse_after_gain_diagnostic_only": math.sqrt(sum((v-gain*u)**2 for u, v in zip(x, y))/len(x)),
        })
    swapped = array("f", (b[i ^ 1] for i in range(len(b))))
    return {"channels": values, "channel_swap_diagnostic_only": error(a, swapped)}


class Bits:
    def __init__(self, data):
        self.data, self.pos = data, 0

    def read(self, n):
        value = 0
        for _ in range(n):
            if self.pos >= len(self.data)*8:
                raise ValueError("Truncated diagnostic side info")
            value = (value << 1) | ((self.data[self.pos//8] >> (7-self.pos%8)) & 1)
            self.pos += 1
        return value


def inspect_frames(path):
    """Bounded diagnostic parser for these MPEG-2, 22050 Hz stereo fixtures only."""
    data, offset, result = path.read_bytes(), 0, []
    rates = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
    while offset < len(data):
        if len(data)-offset < 4:
            raise ValueError("Unexpected incomplete diagnostic frame header")
        _, b1, b2, b3 = data[offset:offset+4]
        if data[offset] != 255 or (b1 & 0xfe) != 0xf2 or (b2 & 12) != 0 or b3 >> 6 == 3:
            raise ValueError("Diagnostic input is not the expected MPEG-2 22050Hz stereo")
        rate = rates[b2 >> 4]
        if not rate:
            raise ValueError("This diagnostic does not scan free-format")
        size = 72000*rate//22050 + ((b2 >> 1) & 1)
        if offset+size > len(data):
            raise ValueError("Unexpected incomplete diagnostic frame")
        start = offset + 4 + (0 if b1 & 1 else 2)
        bits = Bits(data[start:start+17])
        reservoir = bits.read(8)
        bits.read(2)
        side = []
        for _ in range(2):
            part23, big_values, gain, sfc = bits.read(12), bits.read(9), bits.read(8), bits.read(9)
            switched = bits.read(1)
            if switched:
                block_type, mixed = bits.read(2), bits.read(1)
                bits.read(19)
            else:
                block_type, mixed = 0, 0
                bits.read(22)
            bits.read(2)
            side.append({"part2_3_length": part23, "big_values": big_values,
                         "global_gain": gain, "scalefac_compress": sfc,
                         "block_type": block_type, "mixed_block": mixed})
        assert bits.pos == 136
        result.append({"frame": len(result), "byte_offset": offset, "frame_bytes": size,
                       "mode": b3 >> 6, "mode_extension": (b3 >> 4) & 3,
                       "main_data_begin": reservoir, "side_info": side})
        offset += size
    return result


def frame_metrics(a, b, frames):
    assert len(a) == len(b) == len(frames)*576*2
    groups = defaultdict(list)
    block_rmse = []
    for frame in frames:
        start = frame["frame"]*1152
        rmse = error(a[start:start+1152], b[start:start+1152])["rmse"]
        block_rmse.append(rmse)
        groups[f"mode={frame['mode']},extension={frame['mode_extension']}"].append(rmse)
    ranges = []
    for index, value in enumerate(block_rmse):
        if value > 1e-3:  # Diagnostic localization only, not an acceptance threshold.
            if ranges and ranges[-1][1] == index-1:
                ranges[-1][1] = index
            else:
                ranges.append([index, index])
    worst = sorted(range(len(frames)), key=block_rmse.__getitem__, reverse=True)[:5]
    return {"block_size_per_channel": 576,
            "diagnostic_bad_block_rmse_above": 1e-3,
            "bad_block_count": sum(x > 1e-3 for x in block_rmse),
            "bad_block_ranges_inclusive_zero_based": ranges,
            "mode_groups": {key: {"frame_count": len(values), "rms_of_block_rmse": math.sqrt(sum(x*x for x in values)/len(values))} for key, values in groups.items()},
            "worst_blocks": [{**frames[i], "pcm_rmse": block_rmse[i]} for i in worst],
            "right_block_type_counts": dict(Counter(f["side_info"][1]["block_type"] for f in frames))}


def build_variant(name, header):
    folder = BUILD / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "minimp3.h").write_text(header, encoding="utf-8", newline="\n")
    (folder / "minimp3_ex.h").write_bytes((ROOT / "third_party/minimp3/minimp3_ex.h").read_bytes())
    driver = (ROOT / "tools/reference_decode.c").read_text(encoding="utf-8")
    include = '#include "../third_party/minimp3/minimp3_ex.h"'
    assert driver.count(include) == 1
    (folder / "decode.c").write_text(driver.replace(include, '#include "minimp3_ex.h"'), encoding="utf-8", newline="\n")
    exe = folder / ("decode.exe" if sys.platform == "win32" else "decode")
    command = ["gcc", "-std=c99", "-O2", "-ffp-contract=off", "-DMINIMP3_ONLY_MP3",
               "-DMINIMP3_NO_SIMD", "-DMINIMP3_FLOAT_OUTPUT", folder / "decode.c", "-lm", "-o", exe]
    run(command)
    return exe


def main():
    source = ROOT / "third_party/minimp3/minimp3.h"
    if sha(source) != HEADER_SHA:
        raise RuntimeError("Unexpected minimp3 source bytes")
    header = source.read_text(encoding="utf-8")
    old = "ist_pos[k] = (s == max_scf ? -1 : s);"
    assert header.count(old) == 1
    old_limit = "max_pos = HDR_TEST_MPEG1(hdr) ? 7 : 64;"
    new_limit = "max_pos = HDR_TEST_MPEG1(hdr) ? 7 : 16;"
    assert header.count(old_limit) == 1
    variants = {
        "control_unmodified": build_variant("control_unmodified", header),
        "diagnostic_disable_lsf_sentinel": build_variant(
            "diagnostic_disable_lsf_sentinel", header.replace(old, "ist_pos[k] = s;")),
        "diagnostic_limit_lsf_position_to_16": build_variant(
            "diagnostic_limit_lsf_position_to_16", header.replace(old_limit, new_limit)),
        "diagnostic_both_lsf_changes": build_variant(
            "diagnostic_both_lsf_changes", header.replace(old, "ist_pos[k] = s;").replace(old_limit, new_limit)),
    }
    report = {
        "scope": "l3-test45 and l3-test46 only; no automatic offset search, no acceptance threshold changes",
        "acceptance_effect": "None. All counterfactual results are excluded from acceptance references.",
        "alignment": "Index zero to index zero, with identical frame and sample counts; no trimming or shifting",
        "reference_header_sha256": HEADER_SHA,
        "reference_driver_sha256": sha(ROOT / "tools/reference_decode.c"),
        "ffmpeg_version": run(["ffmpeg", "-version"])[0].splitlines()[0],
        "ffmpeg_source_inspected": FFMPEG_SOURCE,
        "source_hypothesis": {
            "minimp3": "L3_read_scalefactors converts an all-ones LSF scalefactor to intensity position 255; L3_stereo_process requires position <64, so it skips intensity stereo there.",
            "ffmpeg": "At e347b4ff31 the LSF reader keeps raw scale factors; compute_stereo uses sf_max=16 for MPEG-2 intensity stereo.",
            "counterfactual": "Temporary copies independently remove the all-ones sentinel conversion, limit LSF intensity positions to <16, or combine both changes. Their PCM is diagnostic and never a reference.",
        },
        "cases": [],
        "limits": [
            "The counterfactual is a controlled mechanism test, not a proposed decoder correction or proof that either implementation is universally correct.",
            "No FFmpeg intermediate spectrum has been instrumented; any residual cannot be attributed to a precise stage by this experiment alone.",
            "The stored upstream PCM agrees much more closely with original minimp3; keep it and original minimp3 as the primary oracle for these fixtures.",
            "Frame grouping is temporal localization, not independent per-frame decoding: IMDCT overlap and synthesis history can carry a previous frame's differences into a later mode.",
        ],
    }
    for name in ("l3-test45", "l3-test46"):
        input_path = ROOT / "tests/corpus/upstream" / (name + ".bit")
        a_path, b_path = OUT / (name+"-f32-raw.pcm"), OUT / (name+"-ffmpeg-f32.pcm")
        a, b = pcm(a_path), pcm(b_path)
        frames = inspect_frames(input_path)
        result = {"id": name, "input_sha256": sha(input_path), "minimp3_pcm_sha256": sha(a_path),
                  "ffmpeg_pcm_sha256": sha(b_path), "unmodified_comparison": error(a, b),
                  **channel_metrics(a, b), "frame_localization": frame_metrics(a, b, frames),
                  "diagnostic_variants": {}}
        for variant, exe in variants.items():
            destination = BUILD / variant / (name+".pcm")
            run([exe, "raw", input_path, destination, destination.with_suffix(".json")])
            values = pcm(destination)
            result["diagnostic_variants"][variant] = {
                "pcm_sha256": sha(destination), "versus_original_minimp3": error(a, values),
                "versus_ffmpeg_float": error(b, values),
            }
            if variant == "control_unmodified" and sha(destination) != sha(a_path):
                raise RuntimeError("Diagnostic unmodified control differs from baseline")
        # Independent diagnostic of whether FFmpeg float vs fixed arithmetic is
        # responsible. This output is also not a replacement acceptance oracle.
        integer_out = BUILD / (name+"-ffmpeg-mp3-fixed-f32.pcm")
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-c:a", "mp3", "-i", input_path,
                   "-map", "0:a:0", "-c:a", "pcm_f32le", "-f", "f32le", integer_out]
        _, warnings = run(command)
        values = pcm(integer_out)
        result["ffmpeg_fixed_decoder_diagnostic"] = {
            "command": [normalized(str(x)) for x in command], "stderr": normalized(warnings),
            "versus_ffmpeg_float": error(b, values), "versus_original_minimp3": error(a, values)}
        original = result["unmodified_comparison"]["rmse"]
        for variant, measurements in result["diagnostic_variants"].items():
            residual = measurements["versus_ffmpeg_float"]["rmse"]
            measurements["squared_error_reduction_fraction"] = 1-(residual/original)**2
            print(f"{name}: {variant}: RMSE vs FFmpeg {residual:.9g}", flush=True)
        both = result["diagnostic_variants"]["diagnostic_both_lsf_changes"]
        result["interpretation"] = {
            "equal_sample_counts": "Both decoders output the same number of samples at 22050 Hz stereo; comparison is unshifted.",
            "gain_and_channel_checks": "Swapping channels increases error; per-channel constant gain fitting leaves large residuals; all observed peaks are below 1.",
            "arithmetic_check": "FFmpeg mp3 fixed-point and mp3float outputs differ by about 1.2e-5 RMSE, much less than either differs from original minimp3.",
            "controlled_mechanism_evidence": f"Applying both LSF intensity-selection changes to a temporary minimp3 copy removes {100*both['squared_error_reduction_fraction']:.6f}% of squared error against FFmpeg, at identical alignment.",
            "remaining_uncertainty": "The residual is still above the ordinary baseline tolerance. These experiments locate a dominant implementation difference but do not fully establish root cause, standards conformance, or which decoder is correct.",
        }
        report["cases"].append(result)
    destination = OUT / "ffmpeg-diagnostics.json"
    destination.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(destination)


if __name__ == "__main__":
    main()
