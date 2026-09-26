"""Run the declared full coded-bitrate/channel-mode PCM differential matrix.

504 syntax rows cross every supported rate with every non-free bitrate index
and all four channel modes, including complete true Dual Channel streams.
Another 54 independently encoded chirps cross rate, channels and CBR/VBR/ABR.
Synthetic rows use proper MPEG-1 versus LSF side information and nonzero,
independently coded channels. They are explicitly not real-encoder recordings.
No oracle cropping, alignment search, exceptions or threshold relaxation is used.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import wave

from pcm_compare import compare, read_pcm
from validate_compatibility import bits, frame_records, fields
from validate_mpeg1 import ROOT, BACKENDS, literal, snapshot_module, build_native_adapter
from verify_environment import moon_environment, verify

OUT = ROOT / "target/matrix-validation"
MANIFEST = ROOT / "tests/differential_matrix.json"


def command(args, timeout=60):
    result = subprocess.run(list(map(str, args)), cwd=ROOT, env=moon_environment(),
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def syntax_stream(version, rate, bitrate, mode, frames):
    """Construct every frame from fields; there is no relabelled encoded payload.

    Each granule's left channel has one table-1 nonzero Huffman pair; the right
    has two pairs and a different global gain/sign. The complete part2_3 bit
    budget is consumed, scalefactor-compress is zero, and main_data_begin=0.
    All frames are normal long blocks, with alternating physical padding.
    """
    mpeg1 = version["header_version"] == 3
    channels = mode["channels"]
    sr = version["rates"].index(rate)
    br = version["bitrates_kbps"].index(bitrate) + 1
    stream = bytearray()
    for index in range(frames):
        padding = index % 2
        header = bytes((255, 0xe3 | version["header_version"] << 3,
                        br << 4 | sr << 2 | padding << 1,
                        mode["header_mode"] << 6 | mode["extension"] << 4))
        side = bits(0, 9 if mpeg1 else 8)
        side += bits(0, (5 if channels == 1 else 3) if mpeg1 else (1 if channels == 1 else 2))
        if mpeg1:
            side += bits(0, 4) * channels  # scfsi
        payload = ""
        for granule in range(2 if mpeg1 else 1):
            for ch in range(channels):
                pairs = ch + 1
                encoded = ("010" if (index + granule + ch) % 2 == 0 else "011") * pairs
                side += bits(len(encoded), 12) + bits(pairs, 9) + bits(174 - ch * 4, 8)
                side += bits(0, 4 if mpeg1 else 9) + bits(0, 1)  # compress, long block
                side += bits(1, 5) * 3 + bits(0, 4) + bits(0, 3)  # tables and regions
                if mpeg1:
                    side += bits(0, 1)  # preflag
                side += bits(0, 1) * 2  # scalefac_scale, count1table_select
                payload += encoded
        assert len(side) == ((17 if channels == 1 else 32) if mpeg1 else (9 if channels == 1 else 17)) * 8
        encoded = side + payload
        encoded += "0" * (-len(encoded) % 8)
        frame = header + int(encoded, 2).to_bytes(len(encoded) // 8, "big")
        size = (144000 if mpeg1 else 72000) * bitrate // rate + padding
        assert len(frame) <= size, (rate, bitrate, mode, len(frame), size)
        stream += frame + bytes(size - len(frame))
    return bytes(stream)


def generate_inputs(manifest):
    result = []
    for version in manifest["versions"]:
        for rate in version["rates"]:
            for bitrate in version["bitrates_kbps"]:
                for mode in manifest["modes"]:
                    name = f"syntax-mpeg{version['version']}-{rate}-{bitrate}k-{mode['name']}"
                    data = syntax_stream(version, rate, bitrate, mode, manifest["frames_per_syntax_stream"])
                    path = OUT / f"{name}.mp3"
                    path.write_bytes(data)
                    records = frame_records(data)
                    assert len(records) == manifest["frames_per_syntax_stream"]
                    for offset, *_ in records:
                        assert fields(data, offset)[:3] == (version["header_version"], rate, bitrate)
                        assert data[offset + 3] >> 6 == mode["header_mode"]
                    result.append({"id": name, "origin": "synthetic nonzero long-block syntax",
                                   "path": path, "version": version["version"], "sample_rate": rate,
                                   "channels": mode["channels"], "channel_mode": mode["name"],
                                   "bitrate_kbps": bitrate, "frames": len(records), "sha256": hashlib.sha256(data).hexdigest()})
    assert len(result) == manifest["expected_syntax_rows"] == 504
    for version in manifest["versions"]:
        for rate in version["rates"]:
            for channels in manifest["real_encoder"]["channels"]:
                source = OUT / f"chirp-{rate}-{channels}ch.wav"
                sample_frames = rate // 5
                samples = []
                for n in range(sample_frames):
                    envelope = min(1, n / 100, (sample_frames - 1 - n) / 100)
                    for ch in range(channels):
                        phase = 2 * math.pi * ((233 + ch * 178) * n / rate + 137 * (n / rate) ** 2)
                        samples.append(round(13000 * envelope * math.sin(phase)))
                with wave.open(str(source), "wb") as output:
                    output.setnchannels(channels)
                    output.setsampwidth(2)
                    output.setframerate(rate)
                    output.writeframes(struct.pack(f"<{len(samples)}h", *samples))
                for control in manifest["real_encoder"]["rate_controls"]:
                    name = f"encoded-mpeg{version['version']}-{rate}-{channels}ch-{control}"
                    path = OUT / f"{name}.mp3"
                    bitrate = "24k" if rate < 16000 else "64k" if rate < 32000 else "128k"
                    options = ["-q:a", "4"] if control == "vbr" else (["-abr", "1"] if control == "abr" else []) + ["-b:a", bitrate]
                    command(["ffmpeg", "-v", "error", "-y", "-i", source, "-map_metadata", "-1",
                             "-c:a", "libmp3lame", *options, "-write_xing", "0", "-id3v2_version", "0", path])
                    data = path.read_bytes()
                    records = frame_records(data)
                    assert all(row[2:5] == (version["header_version"], rate, channels) for row in records)
                    result.append({"id": name, "origin": "FFmpeg/libmp3lame encoded chirp",
                                   "path": path, "version": version["version"], "sample_rate": rate,
                                   "channels": channels, "rate_control": control, "frames": len(records),
                                   "actual_header_modes": sorted({data[row[0]+3] >> 6 for row in records}),
                                   "actual_bitrates_kbps": sorted({fields(data, row[0])[2] for row in records}),
                                   "sha256": hashlib.sha256(data).hexdigest()})
    assert len(result) == 504 + manifest["real_encoder"]["expected_rows"] == 558
    return result


def references(case, reference, native, policy):
    path = case["path"]
    c_pcm, c_meta = path.with_suffix(".c.pcm"), path.with_suffix(".c.json")
    command([reference, "raw", path, c_pcm, c_meta])
    metadata = json.loads(c_meta.read_text())
    assert metadata["sample_rate"] == case["sample_rate"] and metadata["channels"] == case["channels"]
    assert metadata["decoded_frames"] == case["frames"]
    assert metadata["skipped_bytes"] == metadata["trailing_bytes"] == metadata["zero_sample_frames"] == 0
    expected = read_pcm(c_pcm, "f32le")
    assert any(abs(value) > 1e-7 for value in expected), case["id"]
    if case["channels"] == 2:
        assert any(abs(value) > 1e-7 for value in expected[::2]), case["id"]
        assert any(abs(value) > 1e-7 for value in expected[1::2]), case["id"]
        assert any(abs(left - right) > 1e-7 for left, right in zip(expected[::2], expected[1::2])), case["id"]
    ff_pcm = path.with_suffix(".ffmpeg.pcm")
    command(["ffmpeg", "-v", "error", "-y", "-c:a", "mp3float", "-i", path,
             "-map", "0:a:0", "-c:a", "pcm_f32le", "-f", "f32le", ff_pcm])
    probe = json.loads(command(["ffprobe", "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels", "-of", "json", path]))["streams"][0]
    ff_values = read_pcm(ff_pcm, "f32le")
    fm = {"sample_rate": int(probe["sample_rate"]), "channels": probe["channels"], "sample_count": len(ff_values)}
    independent = compare(expected, ff_values, metadata, fm, **policy["f32"])
    assert independent["passed"], (case["id"], "FFmpeg", independent)
    moon_pcm = path.with_suffix(".moon.pcm")
    env = {**moon_environment(), "MP3_VALIDATION_INPUT": str(path), "MP3_VALIDATION_OUTPUT": str(moon_pcm)}
    run = subprocess.run([str(native)], cwd=ROOT, env=env, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=30, check=True)
    rate, channels, count = map(int, run.stdout.split())
    mm = {"sample_rate": rate, "channels": channels, "sample_count": count}
    actual = read_pcm(moon_pcm, "f32le")
    moon = compare(expected, actual, metadata, mm, **policy["f32"])
    ff_moon = compare(ff_values, actual, fm, mm, **policy["f32"])
    assert moon["passed"] and ff_moon["passed"], (case["id"], moon, ff_moon)
    return {**case, "pcm": c_pcm, "ffmpeg_pcm": ff_pcm, "metadata": metadata, "minimp3": moon,
            "ffmpeg": ff_moon, "independent_references": independent}


def generate_suite(cases, policy):
    workspace = snapshot_module(output_root=OUT)
    lines = ['''///|
fn matrix_bytes(parts : Array[Bytes]) -> Bytes {
  let bytes : Array[Byte] = []
  for part in parts { for byte in part { bytes.push(byte) } }
  Bytes::from_array(bytes)
}
///|
fn matrix_float(data : Bytes, index : Int) -> Double {
  let p = index * 4
  Float::reinterpret_from_uint(data[p].to_uint() | (data[p+1].to_uint() << 8) |
    (data[p+2].to_uint() << 16) | (data[p+3].to_uint() << 24)).to_double()
}''']
    pcm_ids = {}
    for case in cases:
        expected_vectors = []
        for path in (case["pcm"], case["ffmpeg_pcm"]):
            pcm = path.read_bytes()
            digest = hashlib.sha256(pcm).hexdigest()
            if digest not in pcm_ids:
                variable = f"matrix_pcm_{len(pcm_ids)}"
                pcm_ids[digest] = variable
                lines += [f'///|\nlet {variable} : Bytes = matrix_bytes({literal(pcm)})']
            expected_vectors.append(pcm_ids[digest])
        meta = case["metadata"]
        lines += [f'test "matrix {case["id"]}" {{',
                  f'  let audio = decode_all(matrix_bytes({literal(case["path"].read_bytes())}))',
                  f'  assert_eq(audio.sample_rate, {meta["sample_rate"]})',
                  f'  assert_eq(audio.channels, {meta["channels"]})',
                  f'  assert_eq(audio.samples.length(), {meta["sample_count"]})',
                  f'  for expected in [{", ".join(expected_vectors)}] {{',
                  '  let mut squared = 0.0', '  let mut maximum = 0.0',
                  '  for i = 0; i < audio.samples.length(); i = i + 1 {',
                  '    let value = audio.samples[i].to_double()',
                  '    assert_true(!value.is_nan() && !value.is_inf())',
                  '    let error = (value - matrix_float(expected, i)).abs()',
                  '    squared += error * error', '    if error > maximum { maximum = error }', '  }',
                  f'  assert_true(maximum <= {policy["f32"]["max_abs_error"]})',
                  f'  assert_true(squared / audio.samples.length().to_double() <= {policy["f32"]["max_rmse"] ** 2:.16e})',
                  f'  assert_true(squared / audio.samples.length().to_double() <= {(32767/32768)**2 * 10**(-policy["f32"]["min_psnr_db"]/10):.16e})', '  }', '}']
    (workspace / "integration_wbtest.mbt").write_text('\n\n'.join(lines) + '\n', encoding="utf-8")
    return workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=BACKENDS)
    parser.add_argument("--jobs", type=int, default=4, help="Independent bounded reference workers")
    parser.add_argument("--timeout", type=int, default=900, help="Hard seconds per backend including compilation")
    args = parser.parse_args()
    if not 1 <= args.jobs <= 16 or args.timeout <= 0:
        parser.error("--jobs must be 1..16 and --timeout must be positive")
    verify()
    OUT.mkdir(parents=True, exist_ok=True)
    report_path = OUT / "results.json"
    report_path.write_text(json.dumps({"status": "preparing", "backend_timeout_seconds": args.timeout}) + '\n')
    manifest = json.loads(MANIFEST.read_text())
    policy = json.loads((ROOT / "tests/reference_policy.json").read_text())
    cases = generate_inputs(manifest)
    print(f"Prepared {len(cases)} complete streams: 504 syntax matrix + 54 encoded chirps", flush=True)
    reference = OUT / ("reference.exe" if os.name == "nt" else "reference")
    command(["gcc", "-std=c99", "-O2", "-ffp-contract=off", "-DMINIMP3_ONLY_MP3", "-DMINIMP3_NO_SIMD",
             "-DMINIMP3_FLOAT_OUTPUT", ROOT / "tools/reference_decode.c", "-lm", "-o", reference])
    native = build_native_adapter("decode_all", output_root=OUT)
    verified = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        for index, result in enumerate(executor.map(lambda case: references(case, reference, native, policy), cases), 1):
            verified.append(result)
            if index % 100 == 0 or index == len(cases):
                print(f"PASS native + minimp3 + FFmpeg {index}/{len(cases)}", flush=True)
    workspace = generate_suite(verified, policy)
    report = {"status": "running", "backend_timeout_seconds": args.timeout,
              "matrix": manifest, "thresholds": policy["f32"], "backends": [],
              "cases": [{key: str(value.relative_to(ROOT)) if isinstance(value, Path) else value
                         for key, value in case.items()} for case in verified]}
    report_path = OUT / "results.json"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    for backend in args.backends:
        print(f"Checking all {len(cases)} complete PCM outputs on {backend}", flush=True)
        result = command(["moon", "-C", workspace, "test", "--target", backend, "--release", "--deny-warn"], timeout=args.timeout)
        (OUT / f"{backend}.log").write_text(result, encoding="utf-8")
        totals = re.findall(r"Total tests: (\d+), passed: (\d+), failed: (\d+)", result)
        assert totals == [(str(len(cases)), str(len(cases)), "0")], (backend, totals)
        report["backends"].append({"backend": backend, "passed": len(cases), "failed": 0})
        report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        print(f"PASS {backend}: {len(cases)} full PCM rows, including 126 Dual Channel streams", flush=True)
    report["status"] = "passed"
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        report_path = OUT / "results.json"
        if report_path.exists():
            report = json.loads(report_path.read_text())
            report.update(status="failed", failure=str(error))
            report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        raise
