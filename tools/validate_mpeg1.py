"""Validate continuous MPEG-1 decoding; print results, never persist a report.

The native adapter performs file I/O only. The representative four-backend
suite embeds immutable corpus bytes and C PCM into a temporary MoonBit module
under target/, so the same pure MoonBit decoder runs on every backend.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from pcm_compare import compare, read_pcm
from verify_environment import moon_environment, verify

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "target/mpeg1-validation"
BACKENDS = ("native", "wasm", "wasm-gc", "js")
REPRESENTATIVES = ("generated-32000-2ch-cbr", "generated-44100-1ch-vbr",
                   "generated-48000-2ch-abr", "generated-gapless-tagged",
                   "l3-he_32khz", "l3-si_block", "l3-si_huff", "l3-hecommon")
INTENSITY_CASES = ("joint-intensity", "joint-ms-intensity")


def run(args, **kwargs):
    print("+ " + " ".join(map(str, args)), flush=True)
    kwargs.setdefault("env", moon_environment())
    return subprocess.run(list(map(str, args)), cwd=ROOT, check=True, **kwargs)


def frame_prefix(data, count):
    """Select unchanged complete CBR/VBR MPEG-1 frames, with no resync."""
    pos = 0
    if data[:3] == b"ID3":
        size = 0
        for byte in data[6:10]:
            assert byte < 128
            size = (size << 7) | byte
        pos = 10 + size + (10 if data[5] & 16 else 0)
    for _ in range(count):
        b0, b1, b2, _ = data[pos:pos+4]
        assert b0 == 255 and b1 & 0xfe == 0xfa
        rate = (44100, 48000, 32000)[b2 >> 2 & 3]
        kbps = (0,32,40,48,56,64,80,96,112,128,160,192,224,256,320)[b2 >> 4]
        assert kbps
        pos += 144000 * kbps // rate + ((b2 >> 1) & 1)
        assert pos <= len(data)
    return data[:pos]


def literal(data):
    return "[\n" + "\n".join('b"'+''.join(f"\\x{v:02x}" for v in data[i:i+256])+'",'
                             for i in range(0, len(data), 256)) + "\n]"


def intensity_cases(cases):
    """Create legal header-only intensity variants; never alter corpus files.

    Coding each granule is independent of mode-extension interpretation. These
    fixtures deliberately exercise the complete intensity pipeline, not the
    acoustic meaning of the originally encoded stereo recording.
    """
    source = (ROOT / cases["generated-48000-2ch-abr"]["path"]).read_bytes()
    result = dict(cases)
    for extension, name in ((1, INTENSITY_CASES[0]), (3, INTENSITY_CASES[1])):
        outputs = []
        for mode, suffix in ((extension, ""), (extension - 1, "-control")):
            data = bytearray(source)
            pos = len(frame_prefix(source, 0))
            while pos < len(data):
                assert data[pos] == 255 and data[pos+1] & 0xfe == 0xfa
                b2 = data[pos+2]
                rate = (44100,48000,32000)[b2 >> 2 & 3]
                kbps = (0,32,40,48,56,64,80,96,112,128,160,192,224,256,320)[b2 >> 4]
                data[pos+3] = (data[pos+3] & 15) | 0x40 | (mode << 4)
                pos += 144000 * kbps // rate + ((b2 >> 1) & 1)
            assert pos == len(data)
            input_path = OUT / f"{name}{suffix}.mp3"
            input_path.write_bytes(data)
            pcm_path = OUT / f"{name}{suffix}.pcm"
            run([ROOT / "target/reference/decode-f32.exe", "raw", input_path, pcm_path,
                 OUT / f"{name}{suffix}.json"])
            outputs.append(pcm_path.read_bytes())
            if not suffix:
                result[name] = {"id": name, "path": input_path.relative_to(ROOT).as_posix()}
        assert outputs[0] != outputs[1], f"Intensity processing was not exercised: {name}"
    return result


def snapshot_module(directory="module", output_root=OUT, benchmark=False):
    workspace = output_root / directory
    workspace.mkdir(parents=True, exist_ok=True)
    # Use only current production sources. Numeric fixtures are added below.
    sources = [path for path in [ROOT / "moon.mod", ROOT / "moon.pkg", *ROOT.glob("*.mbt"),
               *ROOT.glob("internal/**/*.mbt"), *ROOT.glob("internal/**/moon.pkg")]
               if not path.name.endswith(("_test.mbt", "_wbtest.mbt"))]
    current = {path.relative_to(ROOT) for path in sources}
    generated = {Path("integration_wbtest.mbt"), Path("internal/layer3/continuous_trace_wbtest.mbt")}
    for old in [*workspace.glob("*.mbt"), *workspace.glob("moon.*"),
                *workspace.glob("internal/**/*.mbt"), *workspace.glob("internal/**/moon.pkg*")]:
        assert old.resolve().is_relative_to(workspace.resolve()), "Temporary source escaped its workspace"
        if old.relative_to(workspace) not in current | generated:
            old.unlink()
    for path in sources:
        target = workspace / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    if benchmark:
        package = workspace / "moon.pkg"
        package.write_text(
            package.read_text(encoding="utf-8")
            + '\nimport {\n  "moonbitlang/core/bench",\n} for "wbtest"\n',
            encoding="utf-8",
        )
    return workspace


def generate_integration_suite(cases, policy):
    cases = intensity_cases(cases)
    workspace = snapshot_module(benchmark=True)
    lines = ['// Generated transient corpus checks; no local paths or execution logs.',
             '///|', 'fn integration_bytes(chunks : Array[Bytes]) -> Bytes {',
             '  let bytes : Array[Byte] = []',
             '  for chunk in chunks { for b in chunk { bytes.push(b) } }',
             '  Bytes::from_array(bytes)', '}',
             '///|', 'fn integration_float(data : Bytes, i : Int) -> Float {',
             '  let p = i * 4',
             '  Float::reinterpret_from_uint(data[p].to_uint() | (data[p+1].to_uint() << 8) |',
             '    (data[p+2].to_uint() << 16) | (data[p+3].to_uint() << 24))', '}']
    for name in (*REPRESENTATIVES, *INTENSITY_CASES):
        data = (ROOT / cases[name]["path"]).read_bytes()
        if name.startswith("l3-") and name != "l3-si_block":
            data = frame_prefix(data, 10 if name == "l3-hecommon" else 16)
        input_path = OUT / f"{name}-representative.mp3"
        input_path.write_bytes(data)
        expected_path = OUT / f"{name}-representative.pcm"
        metadata_path = OUT / f"{name}-representative.json"
        run([ROOT / "target/reference/decode-f32.exe", "raw", input_path, expected_path, metadata_path])
        meta = json.loads(metadata_path.read_text())
        expected = expected_path.read_bytes()
        assert len(expected) == meta["sample_count"] * 4
        lines += ['///|', f'test "continuous MPEG1 PCM {name}" {{',
                  '  let data = integration_bytes(' + literal(data) + ')',
                  '  let expected = integration_bytes(' + literal(expected) + ')',
                  '  let audio = decode_mpeg1(data)',
                  f'  assert_eq(audio.sample_rate, {meta["sample_rate"]})',
                  f'  assert_eq(audio.channels, {meta["channels"]})',
                  f'  assert_eq(audio.samples.length(), {meta["sample_count"]})',
                  '  let mut squared = 0.0', '  let mut maximum = 0.0',
                  '  for i = 0; i < audio.samples.length(); i = i + 1 {',
                  '    let value = audio.samples[i].to_double()',
                  '    assert_true(!value.is_nan() && !value.is_inf())',
                  '    let error = (value - integration_float(expected, i).to_double()).abs()',
                  '    squared += error * error',
                  '    if error > maximum { maximum = error }', '  }',
                  f'  assert_true(maximum <= {policy["f32"]["max_abs_error"]})',
                  f'  assert_true(squared / audio.samples.length().to_double() <= {policy["f32"]["max_rmse"]**2:.16e})',
                  f'  assert_true(squared / audio.samples.length().to_double() <= {(32767/32768)**2 * 10**(-policy["f32"]["min_psnr_db"]/10)})', '}']
        if name == "generated-48000-2ch-abr":
            duration = meta["frames_per_channel"] / meta["sample_rate"]
            lines += ['///|', 'test "MPEG1 release performance excludes file IO" {',
                      '  let data = integration_bytes(' + literal(data) + ')',
                      '  let mut sink = 0.0',
                      '  for i = 0; i < 3; i = i + 1 {',
                      '    let audio = decode_mpeg1(data)',
                      '    sink += audio.samples[2000].to_double()', '  }',
                      '  let times : Array[Double] = []',
                      '  for run = 0; run < 7; run = run + 1 {',
                      '    let start = @bench.monotonic_clock_start()',
                      '    for repeat = 0; repeat < 5; repeat = repeat + 1 {',
                      '      let audio = decode_mpeg1(data)',
                      '      sink += audio.samples[2000].to_double()', '    }',
                      '    times.push(@bench.monotonic_clock_end(start) / 5.0)', '  }',
                      '  assert_true(!sink.is_nan() && !sink.is_inf())', '  times.sort()',
                      f'  println("PERF audio_seconds={duration} median_us=\\{{times[3]}} slowest_batch_us=\\{{times[6]}}")', '}']
    path = workspace / "integration_wbtest.mbt"
    path.write_text("\n".join(lines)+"\n", encoding="utf-8")
    generate_trace_suite(workspace, cases)
    return workspace


def generate_trace_suite(workspace, cases):
    executable = OUT / "layer3_trace.exe"
    run(["gcc", "-std=c99", "-O2", "-ffp-contract=off", "-Wall", "-Wextra", "-Werror",
         "tools/layer3_trace.c", "-lm", "-o", executable])
    lines = [(ROOT / "tools/trace_check.mbt.in").read_text(encoding="utf-8")]
    names = ("generated-48000-2ch-abr", "l3-si_huff", "l3-si_block", "l3-he_32khz",
             "generated-44100-1ch-vbr", "generated-gapless-tagged", *INTENSITY_CASES)
    for name in names:
        count = 28 if name == "l3-si_block" else 8
        expected = OUT / f"{name}-trace.bin"
        run([executable, ROOT / cases[name]["path"], expected, count])
        data = frame_prefix((ROOT / cases[name]["path"]).read_bytes(), count)
        lines += ['///|', f'test "continuous C checkpoints {name}" {{',
                  '  let data = trace_bytes(' + literal(data) + ')',
                  '  let reference = trace_bytes(' + literal(expected.read_bytes()) + ')',
                  f'  check_continuous_trace(data, reference, {count})', '}']
    (workspace / "internal/layer3/continuous_trace_wbtest.mbt").write_text("\n".join(lines)+"\n", encoding="utf-8")


def native_corpus(cases, policy):
    executable = OUT / "native-module/target/native/release/build/validation_driver/validation_driver.exe"
    successes = 0
    for case in cases.values():
        name = case["id"]
        if case["category"] not in ("normal", "alignment") or name in ("l3-he_free", "l3-hecommon"):
            continue
        meta = json.loads((ROOT / f"target/reference/{name}-f32-raw.json").read_text())
        if meta["sample_rate"] < 32000:
            continue
        output = OUT / f"{name}-moon.pcm"
        env = {**os.environ, "MP3_VALIDATION_INPUT": str(ROOT / case["path"]), "MP3_VALIDATION_OUTPUT": str(output)}
        result = subprocess.run([str(executable)], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        rate, channels, count = map(int, result.stdout.split())
        actual_meta = {"sample_rate": rate, "channels": channels, "sample_count": count}
        actual = read_pcm(output, "f32le")
        expected = read_pcm(ROOT / f"target/reference/{name}-f32-raw.pcm", "f32le")
        comparison = compare(expected, actual, meta, actual_meta, **policy["f32"])
        assert comparison["passed"], (name, comparison)
        if "reference_pcm" in case:
            original = read_pcm(ROOT / case["reference_pcm"], "s16le")
            # Only the pre-existing named short reference tails may be omitted.
            extra = policy["legacy_pcm_extra_interleaved_samples"].get(name, 0)
            assert len(actual) - len(original) == extra
            rounded = [to_s16(v) / 32768 for v in actual]
            original_meta = {**meta, "sample_count": len(original)}
            result_s16 = compare(original, rounded[:len(original)], original_meta, original_meta, **policy["s16"])
            assert result_s16["passed"], (name, result_s16)
        # Independent FFmpeg gate retains precisely the already frozen exceptions.
        ffmpeg_pcm = ROOT / f"target/reference/{name}-ffmpeg-f32.pcm"
        ff = read_pcm(ffmpeg_pcm, "f32le")
        ff_result = compare(ff, actual, {**meta, "sample_count": len(ff)}, actual_meta, **policy["f32"])
        if name in policy["ffmpeg_exceptions"]:
            assert not ff_result["passed"] and ff_result["reason"] == policy["ffmpeg_exceptions"][name]["reason"]
        else:
            assert ff_result["passed"], (name, ff_result)
        print(f"PASS {name}: {count} samples, RMSE={comparison['rmse']:.9g}, max={comparison['max_abs_error']:.9g}", flush=True)
        successes += 1
    assert successes == 10, "MPEG1 corpus scope changed; review coverage explicitly"
    rejected = {"l3-hecommon": "InvalidHeader(4179)", "l3-sin1k0db": "InsufficientHistory",
                "l3-compl": "TruncatedFrame", "l3-he_free": "UnsupportedFreeFormat",
                "generated-24000-1ch-abr": "UnsupportedVersion"}
    for name, expected_error in rejected.items():
        env = {**os.environ, "MP3_VALIDATION_INPUT": str(ROOT / cases[name]["path"]),
               "MP3_VALIDATION_OUTPUT": str(OUT / "rejected.pcm")}
        result = subprocess.run([str(executable)], cwd=ROOT, env=env, capture_output=True, text=True)
        assert result.returncode == 2 and expected_error in result.stdout, (name, result.returncode, result.stdout)
        print(f"PASS strict boundary {name}: {result.stdout.strip()}", flush=True)


def to_s16(value):
    # minimp3 mp3dec_f32_to_s16 scalar path, including binary32 addition.
    sample = value * 32768
    if sample >= 32766.5:
        return 32767
    if sample <= -32767.5:
        return -32768
    rounded = int(struct.unpack("<f", struct.pack("<f", sample + 0.5))[0])
    return rounded - (rounded < 0)


def build_native_adapter(api="decode_mpeg1", output_root=OUT):
    assert api in ("decode_mpeg1", "decode_all")
    workspace = snapshot_module("native-module", output_root=output_root)
    package = workspace / "validation_driver"
    package.mkdir(parents=True, exist_ok=True)
    legacy_package = package / "moon.pkg.json"
    if legacy_package.exists():
        legacy_package.unlink()
    for name in ("main.mbt", "moon.pkg", "io.c"):
        source = ROOT / "tools/native_decode" / (name + ".in" if name != "io.c" else name)
        shutil.copyfile(source, package / name)
    main_path = package / "main.mbt"
    main_path.write_text(main_path.read_text(encoding="utf-8").replace("@mp3.decode_all(data)", f"@mp3.{api}(data)"), encoding="utf-8")
    run(["moon", "-C", workspace, "build", "--target", "native", "--release",
         "--target-dir", workspace / "target", "--deny-warn"])
    return workspace / "target/native/release/build/validation_driver/validation_driver.exe"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-foundation", action="store_true", help="Use only after the unchanged foundation validator passed in this run")
    args = parser.parse_args()
    verify()
    OUT.mkdir(parents=True, exist_ok=True)
    if not args.skip_foundation:
        run([sys.executable, "tools/validate_stage1.py"])
    for generator in ("side_info_vectors", "spectral_tables", "spectral_vectors", "transform_tables", "transform_vectors", "synthesis_tables", "synthesis_vectors", "decoder_state_vectors"):
        run([sys.executable, f"tools/generate_{generator}.py", "--check"])
    cases = {case["id"]: case for case in json.loads((ROOT / "tests/corpus/manifest.json").read_text())["cases"]}
    for case in cases.values():
        assert hashlib.sha256((ROOT / case["path"]).read_bytes()).hexdigest() == case["sha256"]
    policy = json.loads((ROOT / "tests/reference_policy.json").read_text())
    build_native_adapter()
    native_corpus(cases, policy)
    workspace = generate_integration_suite(cases, policy)
    for backend in BACKENDS:
        run(["moon", "test", "--target", backend, "--release", "--deny-warn"])
        run(["moon", "-C", workspace, "test", "--target", backend, "--release", "--deny-warn"])
    print("All MPEG-1 continuous PCM, strict-boundary, backend and checkpoint checks passed.")


if __name__ == "__main__":
    main()
