"""Exercise every Layer III conformance row in the pinned minimp3 README.

Results are written only below target/. --require-all turns incomplete
conformance into a failing exit status for a future acceptance gate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from pcm_compare import compare, read_pcm
from reference_baseline import build as build_reference, decode as decode_reference
from validate_mpeg1 import ROOT, build_native_adapter, to_s16
from verify_environment import verify


OUT = ROOT / "target/iso-layer3"
MANIFEST = ROOT / "tests/iso_layer3_manifest.json"


def cases_from_readme():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source = ROOT / manifest["source"]
    table = source.read_text(encoding="utf-8").split("Conformance test passed", 1)[0]
    listed = re.findall(r"^\|([A-Za-z0-9_]+\.bit)\s*\|", table, re.MULTILINE)
    names = manifest["vector_names"]
    if len(names) != 11 or names != listed or len(names) != len(set(names)):
        raise RuntimeError("ISO Layer III inventory differs from the pinned minimp3 README table")
    corpus = json.loads((ROOT / "tests/corpus/manifest.json").read_text(encoding="utf-8"))
    if manifest["upstream_commit"] != corpus["upstream_commit"]:
        raise RuntimeError("ISO inventory and corpus use different upstream commits")
    by_id = {case["id"]: case for case in corpus["cases"]}
    result = []
    for name in names:
        case = by_id["l3-" + Path(name).stem]
        if case["origin"] != f"minimp3@{manifest['upstream_commit']}/vectors/{case['id']}.bit":
            raise RuntimeError(f"Unexpected vector source: {name}")
        for path, digest in ((case["path"], case["sha256"]),
                             (case["reference_pcm"], case["reference_sha256"])):
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"Vector hash changed: {path}")
        result.append(case)
    return manifest, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    verify()
    manifest, cases = cases_from_readme()
    OUT.mkdir(parents=True, exist_ok=True)
    build_reference()
    executable = build_native_adapter(api="decode_all", output_root=OUT)
    policy = json.loads((ROOT / "tests/reference_policy.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        name = case["id"]
        output = OUT / f"{name}-moon.pcm"
        env = {**os.environ,
               "MP3_VALIDATION_INPUT": str(ROOT / case["path"]),
               "MP3_VALIDATION_OUTPUT": str(output)}
        run = subprocess.run([str(executable)], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=90)
        item = {"id": name, "upstream_name": name.removeprefix("l3-") + ".bit"}
        if run.returncode != 0:
            item.update(status="error", exit_code=run.returncode,
                        detail=run.stdout.strip() or run.stderr.strip())
        else:
            rate, channels, count = map(int, run.stdout.split())
            actual = read_pcm(output, "f32le")
            reference_path, reference_meta = decode_reference(case, "f32")
            actual_meta = {"sample_rate": rate, "channels": channels, "sample_count": count}
            f32 = compare(read_pcm(reference_path, "f32le"), actual,
                          reference_meta, actual_meta, **policy["f32"])
            supplied = read_pcm(ROOT / case["reference_pcm"], "s16le")
            extra = policy["legacy_pcm_extra_interleaved_samples"].get(name, 0)
            extent_ok = len(actual) - len(supplied) == extra
            supplied_meta = {"sample_rate": rate, "channels": channels,
                             "sample_count": len(supplied)}
            s16 = compare(supplied, [to_s16(value) / 32768 for value in actual[:len(supplied)]],
                          supplied_meta, supplied_meta, **policy["s16"]) if extent_ok else {
                              "passed": False, "reason": "sample_count",
                              "reference": len(supplied), "candidate": len(actual)}
            item.update(status="passed" if f32["passed"] and s16["passed"] else "pcm_mismatch",
                        sample_rate=rate, channels=channels, sample_count=count,
                        f32=f32, supplied_s16=s16, approved_reference_tail_samples=extra)
        results.append(item)
        detail = (f"RMSE={item['f32']['rmse']:.9g}, s16 PSNR="
                  f"{item['supplied_s16']['psnr_db']:.2f} dB"
                  if item["status"] == "passed" else item.get("detail", item["status"]))
        print(f"{name}: {item['status']} ({detail})", flush=True)
    passed = sum(item["status"] == "passed" for item in results)
    report = {"upstream_commit": manifest["upstream_commit"],
              "source": manifest["source"], "total": len(results),
              "passed": passed, "all_passed": passed == len(results), "cases": results}
    (OUT / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                                       encoding="utf-8")
    print(f"ISO Layer III README vectors: {passed}/{len(results)} full PCM checks passed")
    return 1 if args.require_all and not report["all_passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
