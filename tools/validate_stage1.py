"""Run stage-one gates offline; report results to the terminal, not a saved report."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from pcm_compare import compare, read_pcm
from reference_baseline import baseline, OUT
from verify_environment import verify

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(args):
    print("+ " + " ".join(args), flush=True)
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=180)
    output = result.stdout + result.stderr
    require(result.returncode == 0, f"Command failed: {args}\n{output}")
    return {"command": args, "exit_code": result.returncode, "output": output.strip()}


def reference_gates(report, policy):
    cases = {c["id"]: c for c in json.loads((ROOT / "tests/corpus/manifest.json").read_text())["cases"]}
    require(set(cases) == set(policy["expected"]), "Corpus identities differ from frozen policy")
    seen = set()
    for group, count in policy["categories"].items():
        require(len(report[group]) == count, f"Wrong {group} corpus coverage")
        for result in report[group]:
            name = result["id"]
            require(name not in seen, f"Duplicate reference result: {name}")
            seen.add(name)
            expected = policy["expected"][name]
            require(expected["category"] == group == cases[name]["category"], f"Category drift: {name}")
            for key, value in expected.items():
                if key != "category":
                    require(result.get(key) == value, f"Frozen reference outcome changed: {name}/{key}")
            if group in ("abnormal", "out_of_scope"):
                continue
            require(result["repeat_exact"] and result["s16_repeat_exact"], f"Nondeterministic PCM: {name}")
            require(result["float_to_s16_exact"], f"Scalar f32/s16 rounding drift: {name}")
            meta = result["metadata"]
            if "sample_rate" in cases[name]:
                require(meta["sample_rate"] == cases[name]["sample_rate"] and meta["channels"] == cases[name]["channels"],
                        f"Generated fixture format mismatch: {name}")
            if "reference_pcm" in cases[name]:
                delta = policy["legacy_pcm_extra_interleaved_samples"].get(name, 0)
                require(result["upstream_length_delta_samples"] == delta, f"Legacy PCM extent changed: {name}")
                # Only these named legacy assets have an explicitly frozen short extent.
                # The full decoded PCM SHA and sample count above ALWAYS include the tail.
                require(result["upstream_prefix_diagnostic"]["passed"], f"Legacy PCM numeric mismatch: {name}")
                psnr = result["upstream_prefix_diagnostic"]["psnr_db"]
                require(psnr is None or psnr >= policy["s16"]["min_psnr_db"], f"Frozen s16 threshold failed: {name}")
                if delta == 0:
                    require(result["upstream_strict"]["passed"], f"Unexpected structural mismatch: {name}")
            exception = policy["ffmpeg_exceptions"].get(name)
            if exception:
                require(not result["ffmpeg"]["passed"] and result["ffmpeg"]["reason"] == exception["reason"],
                        f"Independent reference discrepancy changed: {name}")
            else:
                numeric = result["ffmpeg"]
                require(numeric["passed"] and numeric["rmse"] <= policy["f32"]["max_rmse"]
                        and numeric["max_abs_error"] <= policy["f32"]["max_abs_error"]
                        and (numeric["psnr_db"] is None or numeric["psnr_db"] >= policy["f32"]["min_psnr_db"]),
                        f"Independent f32 comparison failed: {name}")
            if group == "alignment":
                alignment = result["declared_alignment"]
                gap = result["gapless_metadata"]
                require(alignment["raw_to_gapless"]["exact"], "Tag-declared normalization differs from upstream high-level API")
                require(gap["frames_per_channel"] == cases[name]["source_frames_per_channel"], "Gapless source length mismatch")
                require(meta["frames_per_channel"] - alignment["start_frames"] - alignment["end_frames"] == gap["frames_per_channel"],
                        "Tag-declared length equation failed")
                numeric = alignment["gapless_to_ffmpeg"]
                require(numeric["passed"] and numeric["rmse"] <= policy["f32"]["max_rmse"]
                        and numeric["max_abs_error"] <= policy["f32"]["max_abs_error"]
                        and (numeric["psnr_db"] is None or numeric["psnr_db"] >= policy["f32"]["min_psnr_db"]),
                        "Gapless independent comparison failed")
    require(seen == set(cases), "Missing reference result")


def real_pcm_mutations(report, policy):
    result = next(c for c in report["normal"] if c["id"] == "generated-48000-2ch-abr")
    meta = result["metadata"]
    pcm = read_pcm(OUT / (result["id"] + "-f32-raw.pcm"), "f32le")
    swapped = [value for i in range(0, len(pcm), 2) for value in (pcm[i+1], pcm[i])]
    mutations = {"channel_swap": swapped, "one_frame_shift": [0.0, 0.0] + pcm[:-2],
                 "gain_0.99": [v * 0.99 for v in pcm], "tail_deleted": pcm[:-2]}
    outcomes = {}
    require(compare(pcm, pcm, meta, meta, **policy["f32"])["passed"], "Control PCM comparison failed")
    for name, candidate in mutations.items():
        outcomes[name] = compare(pcm, candidate, meta, {**meta, "sample_count": len(candidate)}, **policy["f32"])
        require(not outcomes[name]["passed"], f"Comparator missed real PCM mutation: {name}")
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    verify()
    policy = json.loads((ROOT / "tests/reference_policy.json").read_text())
    for module in ("bitstream", "header", "tags"):
        command([sys.executable, f"tools/generate_{module}_vectors.py", "--check"])
    command([sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_*.py", "-v"])
    for backend in ("native", "wasm", "wasm-gc", "js"):
        for operation in ("check", "build", "test"):
            record = command(["moon", operation, "--target", backend, "--deny-warn"])
            if operation == "test":
                totals = re.findall(r"Total tests: (\d+), passed: (\d+), failed: (\d+)", record["output"])
                require(totals == [("27", "27", "0")], f"Unexpected MoonBit test coverage: {record}")
    command(["moon", "fmt", "--check"])
    command(["git", "diff", "--check"])
    report = baseline()
    reference_gates(report, policy)
    real_pcm_mutations(report, policy)
    (OUT / "baseline.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                                       encoding="utf-8", newline="\n")
    command([sys.executable, "tools/diagnose_references.py"])
    length_diagnostics = json.loads((OUT / "diagnostics.json").read_text())
    length_cases = {case["id"]: case for case in length_diagnostics["cases"]}
    require(len(length_cases) == 10, "Missing reference-length diagnostics")
    for name in ("l3-compl", "l3-sin1k0db"):
        require(length_cases[name]["length_accounting"]["fully_explained_by_observed_packets"],
                f"Unexplained reference length: {name}")
    for name in policy["legacy_pcm_extra_interleaved_samples"]:
        require(length_cases[name]["legacy_pcm"]["minimp3_extra_per_channel"] == 1152,
                f"Legacy short extent changed: {name}")
    require(length_cases["l3-he_free"]["forced_mp3_demux"]["returncode"] != 0,
            "FFmpeg free-format capability changed; reconsider the documented exception")
    command([sys.executable, "tools/diagnose_ffmpeg.py"])
    print("All stage-one gates passed (27 MoonBit tests per backend, reference checks, and four PCM mutations).")


if __name__ == "__main__":
    main()
