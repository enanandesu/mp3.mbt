"""Explain reference lengths from encoded frame positions and decoder state.

Runs the unchanged minimp3 decoder with shadow calls to its own side-info and
reservoir helpers, and ffprobe's decoded-frame packet trace. No PCM alignment
search, sample insertion, truncation, or acceptance-threshold change occurs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from diagnostic_text import normalized

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "ea99364f61c14656440e8d77e9c233ccf3124633"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, check=True):
    process = subprocess.run([str(item) for item in command], cwd=ROOT,
                             capture_output=True, text=True, timeout=30)
    if check and process.returncode:
        raise RuntimeError(f"{command}: {process.returncode}: {process.stderr}")
    return process


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / "target/reference/baseline.json")
    parser.add_argument("--output", type=Path, default=ROOT / "target/reference/diagnostics.json")
    args = parser.parse_args()
    target = ROOT / "target/agents/tags/diagnostics"
    target.mkdir(parents=True, exist_ok=True)
    executable = target / "reference_diagnostics.exe"
    build = ["gcc", "-std=c99", "-O2", "-ffp-contract=off",
             "tools/reference_diagnostics.c", "-lm", "-o", executable]
    run(build)
    manifest = json.loads((ROOT / "tests/corpus/manifest.json").read_text())
    cases = {case["id"]: case for case in manifest["cases"]}
    baseline = json.loads(args.baseline.read_text())
    records = {case["id"]: case for category in ("normal", "boundary", "alignment")
               for case in baseline.get(category, [])}
    selected = ["l3-compl", "l3-sin1k0db", "l3-he_free"]
    selected += sorted(name for name, record in records.items()
                       if record.get("upstream_length_delta_samples", 0) and name not in selected)
    report = {
        "upstream_commit": COMMIT,
        "purpose": "Explanation only; strict PCM lengths remain unchanged and no offset search is used.",
        "source_sha256": {name: sha(ROOT / "third_party/minimp3" / name)
                          for name in ("minimp3.h", "minimp3_ex.h")},
        "diagnostic_source_sha256": sha(ROOT / "tools/reference_diagnostics.c"),
        "diagnostic_script_sha256": sha(Path(__file__).resolve()),
        "baseline_sha256": sha(args.baseline),
        "compiler": run(["gcc", "--version"]).stdout.splitlines()[0],
        "ffprobe_version": run(["ffprobe", "-version"]).stdout.splitlines()[0],
        "build_command": [normalized(str(item)) for item in build],
        "definitions": ["MINIMP3_ONLY_MP3", "MINIMP3_NO_SIMD", "MINIMP3_FLOAT_OUTPUT"],
        "helper_contract": {
            "mp3dec_decode_frame": "A synchronization fallback clears history; invalid side info or insufficient reservoir produces zero output.",
            "L3_restore_reservoir": "Succeeds exactly when effective reservoir bytes >= main_data_begin; a zero-output frame still saves available data.",
            "tail": "A valid MPEG header with fewer than its declared frame bytes is not decoded by minimp3.",
            "frame_indices": "Zero based, after minimp3 synchronization; byte offsets are relative to the original file.",
        },
        "cases": [],
    }
    for name in selected:
        case = cases[name]
        path = ROOT / case["path"]
        if sha(path) != case["sha256"]:
            raise RuntimeError(f"Changed corpus input: {name}")
        trace_process = run([executable, path])
        repeat_process = run([executable, path])
        if trace_process.stdout != repeat_process.stdout:
            raise RuntimeError(f"Nonrepeatable diagnostic trace: {name}")
        trace = json.loads(trace_process.stdout)
        (target / (name + ".json")).write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
        summary = trace["summary"]
        if summary["sample_count"] != records[name]["metadata"]["sample_count"]:
            raise RuntimeError(f"Diagnostic decoder samples differ from baseline: {name}")
        command = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                   "frame=nb_samples,pkt_pos,pkt_size", "-of", "json", path]
        ff_result = run(command, check=False)
        ff_frames = json.loads(ff_result.stdout or "{}").get("frames", [])
        ff_frames = [{key: int(value) for key, value in frame.items()} for frame in ff_frames]
        ff_by_position = {frame["pkt_pos"]: frame for frame in ff_frames if "pkt_pos" in frame}
        zero = [frame for frame in trace["frames"] if frame["samples_per_channel"] == 0]
        for frame in zero:
            frame["ffmpeg_packet_output"] = ff_by_position.get(frame["byte_offset"])
        tail = trace["tail"]
        tail["ffmpeg_packet_output"] = ff_by_position.get(tail["byte_offset"])
        observed_ff_samples = sum(frame.get("nb_samples", 0) for frame in ff_frames)
        actual_samples = summary["sample_count"] // summary["channels"]
        zero_extra = sum((frame["ffmpeg_packet_output"] or {}).get("nb_samples", 0) for frame in zero)
        tail_extra = (tail["ffmpeg_packet_output"] or {}).get("nb_samples", 0)
        entry = {
            "id": name, "input_sha256": case["sha256"],
            "trace_repeat_exact": True,
            "trace_sha256": hashlib.sha256(trace_process.stdout.encode()).hexdigest(),
            "minimp3": summary,
            "zero_output_frames": zero, "tail": tail,
            "ffprobe_command": [normalized(str(item)) for item in command],
            "ffprobe_returncode": ff_result.returncode,
            "ffprobe_diagnostics": normalized(ff_result.stderr),
            "ffmpeg_decoded_frame_count": len(ff_frames),
            "ffmpeg_samples_per_channel": observed_ff_samples,
            "ffmpeg_first_packets": ff_frames[:3], "ffmpeg_last_packets": ff_frames[-3:],
            "length_accounting": {
                "ffmpeg_minus_minimp3_per_channel": observed_ff_samples - actual_samples,
                "ffmpeg_output_for_zero_sample_frames": zero_extra,
                "ffmpeg_output_for_incomplete_tail_frame": tail_extra,
                "fully_explained_by_observed_packets": observed_ff_samples - actual_samples == zero_extra + tail_extra,
            },
        }
        if "reference_pcm" in case:
            reference = ROOT / case["reference_pcm"]
            if sha(reference) != case["reference_sha256"]:
                raise RuntimeError(f"Changed legacy PCM: {name}")
            legacy_samples = reference.stat().st_size // 2
            delta = summary["sample_count"] - legacy_samples
            entry["legacy_pcm"] = {
                "sample_count": legacy_samples, "minimp3_extra_interleaved_samples": delta,
                "minimp3_extra_per_channel": delta // summary["channels"],
                "baseline_fixed_prefix_diagnostic": records[name]["upstream_prefix_diagnostic"],
                "acceptance": "Length mismatch remains a strict failure. The unchanged upstream test permits 1152 or 2304 extra interleaved samples; the historical reason for the shorter fixture is not established.",
            }
        if name == "l3-he_free":
            forced = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "mp3",
                      "-i", path, "-f", "null", "-"]
            forced_result = run(forced, check=False)
            entry["forced_mp3_demux"] = {"command": [normalized(str(item)) for item in forced],
                                         "returncode": forced_result.returncode,
                                         "diagnostics": normalized(forced_result.stderr)}
            entry["interpretation"] = "Automatic demux chooses bit and yields no decoded frames. Forcing mp3 also fails to find consecutive MPEG frames. FFmpeg is not a usable oracle for this free-format fixture in the pinned environment."
        report["cases"].append(entry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote packet/state diagnostics for {len(report['cases'])} cases to {args.output}")


if __name__ == "__main__":
    main()
