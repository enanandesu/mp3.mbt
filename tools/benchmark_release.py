"""Measure release decoding on fixed corpus bytes and enforce realtime targets."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import platform
import re
import subprocess

from validate_mpeg1 import ROOT, literal, snapshot_module
from verify_environment import moon_environment, verify


OUT = ROOT / "target/performance-validation"
CASES = ("l3-he_32khz", "M2L3_compl24", "generated-8000-2ch-cbr")
BACKENDS = ("native", "wasm")
TARGETS = {"native": 10.0, "wasm": 1.0}
PERF = re.compile(
    r"PERF case=(\S+) api=(\S+) audio_seconds=([\d.]+) "
    r"median_us=([\d.]+) slowest_batch_us=([\d.]+) batch_us=\[([^\]]+)\]"
)


def generate_suite(cases, policy):
    workspace = snapshot_module(output_root=OUT, benchmark=True)
    lines = [
        "///|",
        "fn performance_bytes(chunks : Array[Bytes]) -> Bytes {",
        "  let bytes : Array[Byte] = []",
        "  for chunk in chunks { for value in chunk { bytes.push(value) } }",
        "  Bytes::from_array(bytes)",
        "}",
        "///|",
        "fn performance_whole(data : Bytes) -> (Int, Double) raise {",
        "  let audio = decode_all(data)",
        "  let mut checksum = 0.0",
        "  for i = 0; i < audio.samples.length(); i = i + 257 {",
        "    checksum += audio.samples[i].to_double()",
        "  }",
        "  (audio.samples.length(), checksum)",
        "}",
        "///|",
        "fn performance_stream(data : Bytes) -> (Int, Double) raise {",
        "  let decoder = Decoder::new()",
        "  let mut offset = 0",
        "  let mut samples = 0",
        "  let mut checksum = 0.0",
        "  let mut finished = false",
        "  while true {",
        "    match decoder.next_frame() {",
        "      Frame(frame) => {",
        "        samples += frame.samples.length()",
        "        for i = 0; i < frame.samples.length(); i = i + 257 {",
        "          checksum += frame.samples[i].to_double()",
        "        }",
        "      }",
        "      NeedMoreInput => {",
        "        if offset == data.length() {",
        "          assert_true(!finished, msg=\"stream stalled after EOF\")",
        "          decoder.finish_input()",
        "          finished = true",
        "        } else {",
        "          let accepted = decoder.push(data, offset~)",
        "          assert_true(accepted > 0)",
        "          offset += accepted",
        "        }",
        "      }",
        "      EndOfInput => break",
        "    }",
        "  }",
        "  (samples, checksum)",
        "}",
    ]
    for name in CASES:
        case = cases[name]
        data = (ROOT / case["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != case["sha256"]:
            raise RuntimeError(f"Corpus hash changed: {name}")
        meta = policy["expected"][name]["metadata"]
        duration = meta["sample_count"] / meta["channels"] / meta["sample_rate"]
        for api in ("whole", "stream"):
            invocation = ("performance_whole(data)" if api == "whole"
                          else "performance_stream(data)")
            lines += [
                "///|",
                f'test "release performance {name} {api}" {{',
                "  let data = performance_bytes(" + literal(data) + ")",
                "  let mut sink = 0.0",
                "  for warmup = 0; warmup < 3; warmup = warmup + 1 {",
                f"    let (count, checksum) = {invocation}",
                f"    assert_eq(count, {meta['sample_count']})",
                "    sink += checksum",
                "  }",
                "  let times : Array[Double] = []",
                "  for run = 0; run < 7; run = run + 1 {",
                "    let start = @bench.monotonic_clock_start()",
                "    for repeat = 0; repeat < 5; repeat = repeat + 1 {",
                f"      let (count, checksum) = {invocation}",
                f"      assert_eq(count, {meta['sample_count']})",
                "      sink += checksum",
                "    }",
                "    times.push(@bench.monotonic_clock_end(start) / 5.0)",
                "  }",
                "  assert_true(!sink.is_nan() && !sink.is_inf())",
                "  let batches = times.copy()",
                "  times.sort()",
                (f'  println("PERF case={name} api={api} audio_seconds={duration:.9f} '
                 'median_us=\\{times[3]} slowest_batch_us=\\{times[6]} batch_us=\\{batches}")'),
                "}",
            ]
    (workspace / "performance_wbtest.mbt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=BACKENDS)
    args = parser.parse_args()
    environment = verify()
    cases = {case["id"]: case for case in json.loads(
        (ROOT / "tests/corpus/manifest.json").read_text(encoding="utf-8"))["cases"]}
    policy = json.loads((ROOT / "tests/reference_policy.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    workspace = generate_suite(cases, policy)
    results = []
    for backend in args.backends:
        command = ["moon", "-C", str(workspace), "test", "--target", backend,
                   "--release", "--deny-warn", "--no-parallelize"]
        run = subprocess.run(command, cwd=ROOT, env=moon_environment(),
                             capture_output=True, text=True, timeout=180)
        output = run.stdout + run.stderr
        (OUT / f"{backend}.log").write_text(output, encoding="utf-8")
        if run.returncode:
            raise RuntimeError(f"{backend} benchmark failed:\n{output}")
        rows = PERF.findall(output)
        if len(rows) != len(CASES) * 2:
            raise RuntimeError(f"Expected six {backend} timing rows:\n{output}")
        for name, api, duration, median, slowest, batch_values in rows:
            duration, median, slowest = float(duration), float(median), float(slowest)
            batches = [float(value.strip()) for value in batch_values.split(",")]
            if len(batches) != 7 or sorted(batches)[3] != median or max(batches) != slowest:
                raise RuntimeError(f"Invalid benchmark batch statistics: {name} {api}")
            row = {"backend": backend, "case": name, "api": api,
                   "input_sha256": cases[name]["sha256"],
                   "audio_seconds": duration, "batch_us": batches, "median_us": median,
                   "slowest_batch_us": slowest,
                   "median_realtime": duration * 1_000_000 / median,
                   "slowest_batch_realtime": duration * 1_000_000 / slowest,
                   "target_realtime": TARGETS[backend]}
            row["passed"] = row["median_realtime"] >= row["target_realtime"]
            results.append(row)
            print(f"{backend} {name} {api}: median {row['median_realtime']:.1f}x, "
                  f"slowest batch {row['slowest_batch_realtime']:.1f}x "
                  f"(target {row['target_realtime']:.0f}x)", flush=True)
    sources = sorted([*workspace.glob("*.mbt"), *(workspace / "internal").rglob("*.mbt")])
    source_hash = hashlib.sha256()
    production_hash = hashlib.sha256()
    for source in sources:
        entry = source.relative_to(workspace).as_posix().encode() + b"\0" + source.read_bytes()
        source_hash.update(entry)
        if not source.name.endswith(("_test.mbt", "_wbtest.mbt")):
            production_hash.update(entry)
    report = {"date_utc": datetime.now(timezone.utc).isoformat(),
              "system": platform.platform(), "machine": platform.processor(),
              "toolchain": environment["tools"]["moon"]["version"],
              "environment": environment, "benchmark_source_sha256": source_hash.hexdigest(),
              "production_source_sha256": production_hash.hexdigest(),
              "method": "release; 3 warmups; 7 sequential batches of 5; no file I/O",
              "results": results, "all_passed": all(row["passed"] for row in results)}
    (OUT / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Release performance target: {'passed' if report['all_passed'] else 'FAILED'}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
