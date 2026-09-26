"""Execute all frozen malformed files and reproducible fuzz inputs on four backends.

This is a bounded regression gate, not proof over every possible byte string.
The checked-in expectations describe the default strict API, independently of
the tolerant C reference's behavior. No corpus or reference-policy is rewritten.
Compatible mode also compares partial frames and recovery records, including
when decoding later fails. Test failures identify the fixed seed and iteration.
"""
import argparse
import hashlib
import json
import re
import subprocess

from validate_mpeg1 import ROOT, BACKENDS, literal, snapshot_module
from verify_environment import moon_environment, verify

OUT = ROOT / "target/robustness-validation"
EXPECTATIONS = ROOT / "tests/robustness_expectations.json"
SEEDS = (0x98BADCFE, 0x31504159, 0x5A713D91, 0x20260926)


def generate_suite():
    manifest = json.loads((ROOT / "tests/corpus/manifest.json").read_text())
    abnormal = {c["id"]: c for c in manifest["cases"] if c["category"] == "abnormal"}
    expected = json.loads(EXPECTATIONS.read_text())
    assert len(abnormal) == 16 and set(abnormal) == set(expected["cases"])
    workspace = snapshot_module(output_root=OUT)
    template = (ROOT / "tools/robustness_check.mbt.in").read_text(encoding="utf-8")
    lines = [template, (ROOT / "tools/compatible_robustness_check.mbt.in").read_text(encoding="utf-8")]
    records = []
    for name, case in abnormal.items():
        data = (ROOT / case["path"]).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        assert digest == case["sha256"] == expected["cases"][name]["sha256"]
        contract = expected["cases"][name]
        lines += [f'test "frozen malformed {name}" {{',
                  f'  let data = robustness_bytes({literal(data)})']
        if contract["status"] == "error":
            lines += [f'  robustness_fixed(data, {json.dumps(contract["error"])})']
        else:
            assert contract["status"] == "audio" and contract["all_zero"]
            lines += ['  let audio = decode_all(data)',
                      f'  assert_eq(audio.sample_rate, {contract["sample_rate"]})',
                      f'  assert_eq(audio.channels, {contract["channels"]})',
                      f'  assert_eq(audio.samples.length(), {contract["sample_count"]})',
                      '  for sample in audio.samples { assert_eq(sample, 0.0) }',
                      '  for chunks in [[1], [17, 113, 4096], [8192], [7, 1, 65536]] { robustness_same(data, chunks) }']
        lines += ['}']
        records.append({"id": name, **contract})
    for seed in SEEDS:
        lines += [f'test "reproducible random seed {seed:08x}" {{',
                  '  for case = 0; case < 64; case = case + 1 {',
                  f'    let length = (case * 7919 + {seed % 32769}) % 32769',
                  f'    let data = robustness_random({seed}U + case.to_uint(), length)',
                  f'    robustness_label(data, [1, 17, 113, 4096], "seed {seed:08x}, random case \\{{case}}, small chunks")',
                  f'    robustness_label(data, [65536, 7], "seed {seed:08x}, random case \\{{case}}, large chunks")', '  }', '}']
        lines += [f'test "long random seed {seed:08x}" {{',
                  f'  let data = robustness_random({seed}U, 1048576)',
                  '  robustness_same(data, [1, 257, 8192])',
                  '  robustness_same(data, [65536, 7])', '}']
    # Mutate real nonzero compressed streams, spanning all MPEG versions.
    originals = ("generated-32000-2ch-cbr", "generated-22050-2ch-vbr", "generated-8000-2ch-cbr")
    by_id = {c["id"]: c for c in manifest["cases"]}
    for name in originals:
        case = by_id[name]
        data = (ROOT / case["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == case["sha256"]
        lines += [f'test "real-stream mutations and long input {name}" {{',
                  f'  let original = robustness_bytes({literal(data)})',
                  '  for seed in [' + ', '.join(f'{s}U' for s in SEEDS) + '] {',
                  '    let mut state = seed',
                  '    for iteration = 0; iteration < 32; iteration = iteration + 1 {',
                  '      state = state * 1664525U + 1013904223U',
                  '      let index = (state % original.length().to_uint()).reinterpret_as_int()',
                  '      let changed = Bytes::makei(original.length(), fn(i) {',
                  '        if i == index { (original[i].to_int() ^ (1 << (iteration % 8))).to_byte() } else { original[i] }',
                  '      })',
                  '      robustness_label(changed, [1, 31, 257], "seed \\{seed}, flip \\{iteration}, small chunks")',
                  '      robustness_label(changed, [65536, 7], "seed \\{seed}, flip \\{iteration}, large chunks")',
                  '      robustness_label(original[:index].to_bytes(), [1, 17, 4096], "seed \\{seed}, truncation \\{iteration}, cut \\{index}")',
                  '    }', '  }',
                  '  let long = Bytes::makei(1048576, i => original[i % original.length()])',
                  '  robustness_same(long, [257, 1, 8192])',
                  '  robustness_same(long, [65536, 7])', '}']
    recovery_cases = ("l3-compl", "l3-hecommon", "l3-sin1k0db", "l3-he_mode")
    for name in recovery_cases:
        case = by_id[name]
        data = (ROOT / case["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == case["sha256"]
        lines += [f'test "compatible recoveries across fragmentation {name}" {{',
                  f'  let data = robustness_bytes({literal(data)})',
                  '  for chunks in [[1], [17, 113, 4096], [8192], [7, 1, 65536]] { robustness_compatible_same(data, chunks) }', '}']
    path = workspace / "integration_wbtest.mbt"
    path.write_text('\n\n'.join(lines) + '\n', encoding="utf-8")
    return workspace, records, len(abnormal) + len(SEEDS) * 2 + len(originals) + len(recovery_cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=BACKENDS)
    parser.add_argument("--timeout", type=int, default=600, help="Hard seconds per backend, including compilation")
    parser.add_argument("--portable-tools", action="store_true",
                        help="Hosted regression: verify MoonBit/core/Node hashes and record host tools; no PCM reference environment claim")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.portable_tools:
        from verify_environment import verify_portable_tools
        environment = verify_portable_tools()
    else:
        environment = verify()
    OUT.mkdir(parents=True, exist_ok=True)
    workspace, fixtures, expected_tests = generate_suite()
    report = {"description": "Bounded strict and compatible malformed-input regression; not exhaustive fuzzing",
              "environment": environment,
              "status": "running", "backend_timeout_seconds": args.timeout,
              "fixtures": fixtures, "seeds": list(SEEDS), "random_cases": 256,
              "random_max_bytes": 32768, "long_input_bytes": 1048576,
              "mutations": 384, "truncations": 384,
              "compatible_observations": "whole API, partial frames (rate/channels/source_offset/PCM), errors, ordered recovery strings",
              "backends": []}
    report_path = OUT / "results.json"
    # Write coverage before execution so a timeout still leaves reproducible inputs.
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    for backend in args.backends:
        command = ["moon", "-C", str(workspace), "test", "--target", backend,
                   "--release", "--deny-warn"]
        print('+ ' + ' '.join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, env=moon_environment(),
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=args.timeout)
        (OUT / f"{backend}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        totals = re.findall(r"Total tests: (\d+), passed: (\d+), failed: (\d+)", result.stdout + result.stderr)
        assert result.returncode == 0 and totals == [(str(expected_tests), str(expected_tests), "0")], (backend, result.stdout, result.stderr)
        report["backends"].append({"backend": backend, "passed": expected_tests, "failed": 0})
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(f"PASS {backend}: {expected_tests} strict+compatible suites; 16 frozen files, 256 random, 384 mutations, 384 truncations, 7 long inputs", flush=True)
    report["status"] = "passed"
    report_path.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        report_path = OUT / "results.json"
        if report_path.exists():
            report = json.loads(report_path.read_text())
            report.update(status="failed", failure=str(error))
            report_path.write_text(json.dumps(report, indent=2) + '\n')
        raise
