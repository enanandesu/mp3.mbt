"""Exercise every Layer III conformance row in the pinned minimp3 README.

Strict rejection and compatible full PCM acceptance are separate gates.
Results and generated four-backend frame checks stay below target/.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from pcm_compare import compare_samples, read_pcm
from validate_mpeg1 import ROOT, BACKENDS, build_native_adapter, to_s16, snapshot_module, literal, run
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


STRICT_ERRORS = {
    "l3-compl": "TruncatedFrame(41472, 192)",
    "l3-hecommon": "InvalidHeader(4179)",
    "l3-he_mode": "FormatChange(4179)",
    "l3-sin1k0db": "DecodeFailure(215, InsufficientHistory(461, 0))",
}


def read_candidate(executable, case, output):
    env = {**os.environ, "MP3_VALIDATION_INPUT": str(ROOT / case["path"]),
           "MP3_VALIDATION_OUTPUT": str(output)}
    result = subprocess.run([str(executable)], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=90)
    return result


def pcm_hashes(samples):
    import struct
    h1, h2 = 2166136261, 0
    for value in samples:
        word, = struct.unpack("<I", struct.pack("<f", value))
        h1 = ((h1 ^ word) * 16777619) & 0xffffffff
        h2 = (h2 * 65599 + word) & 0xffffffff
    return h1, h2


def expected_recoveries(data, reference):
    """Derive diagnostic offsets from compressed headers, independently of Moon.

    These pinned vectors contain contiguous coded frames except he_free, which
    has no recoveries. Reservoir gaps are restricted to the C zero-output prefix.
    """
    from validate_compatibility import audio_extent, fields
    start, end = audio_extent(data)
    start += reference["skipped_bytes"]
    events, previous, available, output_started = [], None, 0, False
    outputs = {f["source_offset"] for f in reference["frames"]}
    pos = start
    while pos + 4 <= end:
        version, rate, kbps, padding, channels = fields(data, pos)
        if not kbps:
            assert not reference["zero_sample_frames"] and not reference["trailing_bytes"]
            return []
        length = (144000 if version == 3 else 72000) * kbps // rate + padding
        if pos + length > end:
            events.append(f"TruncatedTail(offset={pos}, discarded_bytes={end-pos})")
            break
        if data[pos+3] & 3 == 2:
            events.append(f"ReservedEmphasis(offset={pos}, value=2)")
        if previous is not None and previous != channels:
            events.append(f"ChannelChange(offset={pos}, previous={previous}, current={channels})")
        crc = 0 if data[pos+1] & 1 else 2
        side = pos+4+crc
        required = (data[side] << 1) | (data[side+1] >> 7) if version == 3 else data[side]
        if pos not in outputs:
            assert not output_started and required > available
            events.append(f"MissingHistory(offset={pos}, frame_bytes={length}, required={required}, available={available})")
            side_length = (17 if channels == 1 else 32) if version == 3 else (9 if channels == 1 else 17)
            available = min(511, available + length - 4 - crc - side_length)
        else:
            output_started = True
        previous = channels
        pos += length
    else:
        if pos < end:
            events.append(f"TruncatedTail(offset={pos}, discarded_bytes={end-pos})")
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=list(BACKENDS))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps({"status": "running", "backends": args.backends})+"\n", encoding="utf-8")
    verify()
    manifest, cases = cases_from_readme()
    OUT.mkdir(parents=True, exist_ok=True)
    reference = OUT / ("reference-frames.exe" if os.name == "nt" else "reference-frames")
    run(["gcc", "-std=c99", "-O2", "-ffp-contract=off", ROOT / "tools/reference_frames.c", "-lm", "-o", reference])
    strict = build_native_adapter(api="decode_all", output_root=OUT / "strict")
    compatible = build_native_adapter(api="decode_all", output_root=OUT / "compatible",
                                      template=ROOT / "tools/native_decode/frames.mbt.in")
    policy = json.loads((ROOT / "tests/reference_policy.json").read_text(encoding="utf-8"))
    workspace = snapshot_module(output_root=OUT / "backends")
    suite = [(ROOT / "tools/iso_check.mbt.in").read_text(encoding="utf-8")]
    results = []
    for case in cases:
        name = case["id"]
        candidate_pcm, reference_pcm, reference_meta = (OUT / f"{name}{suffix}" for suffix in ("-moon.pcm", "-reference.pcm", "-reference.json"))
        run([reference, ROOT / case["path"], reference_pcm, reference_meta], timeout=90)
        meta = json.loads(reference_meta.read_text(encoding="utf-8"))
        assert meta["skipped_bytes"] == (215 if name == "l3-sin1k0db" else 0)
        expected = read_pcm(reference_pcm, "f32le")
        assert len(expected) == meta["sample_count"] == sum(f["sample_count"] for f in meta["frames"])
        strict_run = read_candidate(strict, case, OUT / f"{name}-strict.pcm")
        if name in STRICT_ERRORS:
            assert strict_run.returncode == 2 and strict_run.stdout.strip() == STRICT_ERRORS[name], (name, strict_run.stdout)
            strict_status = {"status": "expected_rejection", "detail": strict_run.stdout.strip()}
        else:
            assert strict_run.returncode == 0, (name, strict_run.stdout, strict_run.stderr)
            rate, channels, count = map(int, strict_run.stdout.split())
            assert all(f["sample_rate"] == rate and f["channels"] == channels for f in meta["frames"])
            strict_pcm = compare_samples(expected, read_pcm(OUT / f"{name}-strict.pcm", "f32le"), **policy["f32"])
            assert count == len(expected) and strict_pcm["passed"], (name, strict_pcm)
            strict_status = {"status": "pcm_passed", "f32": strict_pcm}
        result = read_candidate(compatible, case, candidate_pcm)
        assert result.returncode == 0, (name, result.stdout, result.stderr)
        frames, events = [], []
        for line in result.stdout.splitlines():
            if line.startswith("FRAME "):
                offset, rate, channels, count = map(int, line.split()[1:])
                frames.append(dict(source_offset=offset, sample_rate=rate, channels=channels, sample_count=count))
            elif line.startswith("RECOVERY "):
                events.append(line.removeprefix("RECOVERY "))
            else:
                raise AssertionError((name, line))
        assert frames == meta["frames"], (name, "frame metadata differs")
        actual = read_pcm(candidate_pcm, "f32le")
        assert len(actual) == sum(f["sample_count"] for f in frames)
        data = (ROOT / case["path"]).read_bytes()
        expected_events = expected_recoveries(data, meta)
        assert events == expected_events, (name, events, expected_events)
        f32 = compare_samples(expected, actual, **policy["f32"])
        supplied = read_pcm(ROOT / case["reference_pcm"], "s16le")
        extra = policy["legacy_pcm_extra_interleaved_samples"].get(name, 0)
        assert len(actual)-len(supplied) == extra, (name, len(actual), len(supplied), extra)
        s16 = compare_samples(supplied, [to_s16(x)/32768 for x in actual[:len(supplied)]], **policy["s16"])
        assert f32["passed"] and s16["passed"], (name, f32, s16)
        item = {"id": name, "strict": strict_status, "compatible": {"status": "passed", "frames": len(frames),
                "sample_count": len(actual), "f32": f32, "supplied_s16": s16,
                "approved_reference_tail_samples": extra, "recoveries": events}}
        results.append(item)
        entries, offset = [], 0
        for frame in frames:
            count = frame["sample_count"]
            h1, h2 = pcm_hashes(expected[offset:offset+count])
            entries.append(f"({frame['source_offset']}L,{frame['sample_rate']},{frame['channels']},{count},{h1}U,{h2}U)")
            offset += count
        suite.append(f'///|\ntest "ISO compatible {name}" {{\niso_check(iso_bytes({literal(data)}), [{",".join(entries)}], {json.dumps(events)})\n}}\n')
        print(f"PASS {name}: strict={strict_status['status']}, compatible PCM RMSE={f32['rmse']:.9g}, {len(events)} recoveries", flush=True)
    (workspace / "integration_wbtest.mbt").write_text("\n".join(suite), encoding="utf-8")
    for backend in args.backends:
        run(["moon", "-C", workspace, "test", "--target", backend, "--target-dir", OUT / backend,
             "--deny-warn"], timeout=600)
    report = {"status": "passed", "upstream_commit": manifest["upstream_commit"], "source": manifest["source"],
              "total": len(results), "passed": len(results), "all_passed": len(results) == 11,
              "strict_pcm_passed": sum(x["strict"]["status"] == "pcm_passed" for x in results),
              "strict_expected_rejections": len(STRICT_ERRORS), "backends": args.backends, "cases": results}
    (OUT / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(f"ISO subset: strict 7 PCM + 4 expected rejections; compatible {len(results)}/11 full PCM; backends {args.backends}")
    return 1 if args.require_all and not report["all_passed"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        path = OUT / "results.json"
        report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        report.update(status="failed", failure=str(error))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        raise
