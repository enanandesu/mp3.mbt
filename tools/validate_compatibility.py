"""Validate all three Layer III versions and bounded free-format decoding.

All 24 normal corpus entries plus the alignment entry are accounted for:
24 complete files must decode; the reserved-emphasis hecommon vector retains
its strict error contract and its unchanged first ten frames are compared.
Supplemental syntax fixtures are valid LSF frames with nonzero Huffman data,
not MPEG-1 payloads disguised by changing a version/sample-rate header.
Only temporary numerical fixtures are written beneath ignored target/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

from pcm_compare import compare, read_pcm
from validate_mpeg1 import (ROOT, BACKENDS, literal, run, snapshot_module,
                           build_native_adapter, to_s16)
from verify_environment import verify

OUT = ROOT / "target/compatibility-validation"
RATES = {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}
GENERATED = (
    "generated-8000-2ch-cbr", "generated-11025-1ch-vbr", "generated-12000-2ch-abr",
    "generated-16000-1ch-cbr", "generated-22050-2ch-vbr", "generated-24000-1ch-abr",
    "generated-32000-2ch-cbr", "generated-44100-1ch-vbr", "generated-48000-2ch-abr",
)

# Same-backend equality is meaningful here because the whole-buffer result is
# independently checked against C immediately before this fragmentation test.
STREAM_CHECK = r'''
///|
fn compatibility_fragmented(
  data : Bytes,
  whole : Audio,
  offsets : Array[Int64],
  mode : Int,
) -> Unit raise {
  let decoder = Decoder::new()
  let collected : Array[Float] = []
  let mut first_pcm : Array[Float] = []
  let mut first_copy : Array[Float] = []
  let mut position = 0
  let mut frames = 0
  let mut finished = false
  let mut random = 0x5a713d91U
  let mut turns = 0
  while true {
    turns += 1
    assert_true(turns < data.length() * 3 + offsets.length() * 2 + 100,
      msg="fragmented decoding must make progress")
    match decoder.next_frame() {
      Frame(frame) => {
        assert_eq(frame.sample_rate, whole.sample_rate)
        assert_eq(frame.channels, whole.channels)
        assert_true(frames < offsets.length())
        assert_eq(frame.source_offset, offsets[frames])
        if frames == 0 {
          first_pcm = frame.samples
          first_copy = frame.samples.copy()
        }
        for value in frame.samples { collected.push(value) }
        assert_eq(first_pcm, first_copy)
        frames += 1
      }
      NeedMoreInput => {
        assert_true(!finished, msg="finish_input must resolve a complete stream")
        if position == data.length() {
          decoder.finish_input()
          finished = true
        } else {
          random = random * 1664525U + 1013904223U
          let requested = match mode {
            0 => 1
            1 => 97
            2 => 1 + ((random >> 16) % 257U).reinterpret_as_int()
            _ => data.length() - position
          }
          let size = if requested < data.length() - position { requested } else { data.length() - position }
          let accepted = if mode == 3 {
            decoder.push(data, offset=position)
          } else {
            decoder.push(data[position:position + size].to_bytes())
          }
          assert_true(accepted > 0 && accepted <= size)
          position += accepted
        }
      }
      EndOfInput => {
        assert_true(finished)
        assert_eq(position, data.length())
        break
      }
    }
  }
  assert_eq(frames, offsets.length())
  assert_eq(collected, whole.samples, msg="fragment boundaries changed PCM")
  assert_eq(first_pcm, first_copy)
  match decoder.next_frame() {
    EndOfInput => ()
    _ => fail("EOF is not stable")
  }
  decoder.reset()
  assert_eq(first_pcm, first_copy, msg="reset mutated already returned PCM")
}
'''


def fields(data, pos):
    h = data[pos:pos+4]
    assert len(h) == 4 and h[0] == 255 and h[1] & 0xe0 == 0xe0
    version, layer, sr, br = (h[1] >> 3) & 3, (h[1] >> 1) & 3, (h[2] >> 2) & 3, h[2] >> 4
    assert version != 1 and layer == 1 and sr != 3 and br != 15
    rate = (44100, 48000, 32000)[sr] >> (0 if version == 3 else 1 if version == 2 else 2)
    table = (0,32,40,48,56,64,80,96,112,128,160,192,224,256,320) if version == 3 else (0,8,16,24,32,40,48,56,64,80,96,112,128,144,160)
    return version, rate, table[br], (h[2] >> 1) & 1, 1 if h[3] >> 6 == 3 else 2


def audio_extent(data):
    start, end = 0, len(data)
    while data[start:start+3] == b"ID3":
        assert start + 10 <= end
        size = 0
        for value in data[start+6:start+10]:
            assert value < 128
            size = (size << 7) | value
        start += 10 + size + (10 if data[start+5] & 16 else 0)
        assert start <= end
    if data[end-128:end-125] == b"TAG":
        end -= 128
    return start, end


def frame_records(data, count=None):
    """Read complete contiguous input frames. This indexes inputs, never PCM.

    Free-format requires three matching headers (or two exact EOF frames),
    with one unpadded base size. The independent C oracle must accept the same
    entire input and confirms every traced frame's size against its own finder.
    """
    pos, end = audio_extent(data)
    records, free = [], None
    while pos < end and (count is None or len(records) < count):
        version, rate, kbps, pad, channels = fields(data, pos)
        assert data[pos+3] & 3 != 2, "Reserved emphasis is not a compatible normal header"
        if kbps:
            length = (144000 if version == 3 else 72000) * kbps // rate + pad
        else:
            if free is None:
                for base in range(4, 2305):
                    next_pos = pos + base + pad
                    try:
                        v2, r2, k2, p2, c2 = fields(data, next_pos)
                    except (AssertionError, IndexError):
                        continue
                    if (v2, r2, k2, c2) != (version, rate, 0, channels):
                        continue
                    third = next_pos + base + p2
                    if third == end:
                        free = base
                        break
                    try:
                        v3, r3, k3, _, c3 = fields(data, third)
                    except (AssertionError, IndexError):
                        continue
                    if (v3, r3, k3, c3) == (version, rate, 0, channels):
                        free = base
                        break
                assert free is not None, "Cannot determine bounded free-format base"
            length = free + pad
        assert length >= 4 and pos + length <= end
        records.append((pos, length, version, rate, channels, free if not kbps else None))
        pos += length
    if count is not None:
        assert len(records) == count
    else:
        assert pos == end
    return records


def prefix(data, count):
    records = frame_records(data, count)
    return data[:records[-1][0]+records[-1][1]]


def c_decode(name, data):
    source, pcm, metadata = (OUT / f"{name}{suffix}" for suffix in (".mp3", ".pcm", ".json"))
    source.write_bytes(data)
    run([ROOT / "target/reference/decode-f32.exe", "raw", source, pcm, metadata])
    meta = json.loads(metadata.read_text())
    assert pcm.stat().st_size == meta["sample_count"] * 4
    assert meta["decoded_frames"] == len(frame_records(data))
    assert meta["skipped_bytes"] == meta["trailing_bytes"] == meta["zero_sample_frames"] == 0
    assert all(abs(x) < float("inf") for x in read_pcm(pcm, "f32le"))
    return {"id": name, "path": source, "pcm": pcm, "metadata": meta}


def bits(value, width):
    assert 0 <= value < 1 << width
    return f"{value:0{width}b}"


def lsf_syntax(rate, extension, shift, free=False):
    """Nine proper MPEG-2/2.5 frames with valid mixed/pure-short transitions.

    The left channel carries 40 nonzero table-1 big-value pairs (120 bits).
    The right channel is spectrally zero, with genuine LSF intensity scalefactor
    syntax (compress=144/145, first partition width 2) when intensity is on.
    The 40 nonzero values occupy 80 spectral slots and cross the mixed boundary.
    Mixed start/stop retain long windows in the low subbands; returning to long
    before a pure-short sequence avoids an invalid abrupt low-band window switch.
    Alternating padding is physically present; free-format clears bitrate only.
    """
    version = 0 if rate < 16000 else 2
    sr = {8000: 2, 12000: 1, 24000: 1}[rate]
    result = bytearray()
    sequence = ((0,0), (1,1), (2,1), (3,1), (0,0), (1,0), (2,0), (3,0), (0,0))
    for step, (block, mixed) in enumerate(sequence):
        pad = step % 2
        header = bytes((255, 0xe3 | (version << 3), ((0 if free else 8) << 4) | (sr << 2) | (pad << 1), 0x40 | (extension << 4)))
        is_intensity = extension & 1
        partition = 6 if block == 2 and mixed else 12 if block == 2 else 7
        right_scale = "".join(bits(1 + i % 2, 2) for i in range(partition)) if is_intensity else ""
        payload = ("010" if step % 2 == 0 else "011") * 40 + right_scale
        side = bits(0, 8) + bits(0, 2)
        for ch in range(2):
            part_length = 120 if ch == 0 else len(right_scale)
            compress = (144 + shift) if ch == 1 and is_intensity else 0
            side += bits(part_length,12) + bits(40 if ch == 0 else 0,9) + bits(170,8) + bits(compress,9)
            side += bits(block != 0,1)
            if block:
                side += bits(block,2) + bits(mixed,1) + bits(1,5)*2 + bits(0,3)*3
            else:
                side += bits(1,5)*3 + bits(0,4) + bits(0,3)
            side += bits(0,1)*2
        assert len(side) == 136
        encoded = side + payload
        encoded += "0" * (-len(encoded) % 8)
        frame = bytearray(header + int(encoded,2).to_bytes(len(encoded)//8,"big"))
        size = 72000 * 64 // rate + pad
        assert len(frame) <= size
        frame += bytes(size-len(frame))
        result += frame
    return bytes(result)


def ffmpeg_syntax(case, policy):
    output = case["path"].with_suffix(".ffmpeg.pcm")
    run(["ffmpeg", "-v", "error", "-y", "-i", case["path"], "-map", "0:a:0",
         "-c:a", "pcm_f32le", "-f", "f32le", output])
    pcm = read_pcm(output,"f32le")
    expected = read_pcm(case["pcm"],"f32le")
    probe = json.loads(subprocess.check_output(["ffprobe","-v","error",
        "-select_streams","a:0","-show_entries","stream=sample_rate,channels",
        "-of","json",str(case["path"])],text=True))["streams"][0]
    metadata = {"sample_rate":int(probe["sample_rate"]),"channels":probe["channels"],
                "sample_count":len(pcm)}
    result = compare(expected,pcm,case["metadata"],metadata,**policy["f32"])
    assert result["passed"], (case["id"],result)


def extras(cases,policy):
    result = []
    source = (ROOT / cases["generated-48000-2ch-abr"]["path"]).read_bytes()
    for extension in (1,3):
        variants = []
        for mode in (extension, extension-1):
            data = bytearray(source)
            for pos, *_ in frame_records(source):
                data[pos+3] = (data[pos+3] & 15) | 0x40 | (mode << 4)
            case = c_decode(f"syntax-mpeg1-joint-{mode}", data)
            variants.append(case)
        assert variants[0]["pcm"].read_bytes() != variants[1]["pcm"].read_bytes()
        result.append(variants[0])
    # Pinned C has an out-of-bounds 8-kHz mixed reorder. Use genuine 12-kHz
    # MPEG-2.5 mixed syntax here; real 8-kHz nonmixed audio remains in GENERATED.
    for rate in (12000,24000):
        controls = {mode: c_decode(f"syntax-lsf-{rate}-joint-{mode}", lsf_syntax(rate,mode,0)) for mode in (0,2)}
        for case in controls.values():
            ffmpeg_syntax(case,policy)
        result.extend(controls.values())
        for extension in (1,3):
            previous = None
            for shift in (0,1):
                data = lsf_syntax(rate,extension,shift)
                case = c_decode(f"syntax-lsf-{rate}-joint-{extension}-shift-{shift}", data)
                ffmpeg_syntax(case,policy)
                pcm = case["pcm"].read_bytes()
                assert pcm != controls[extension-1]["pcm"].read_bytes(), "Intensity branch was empty"
                if previous is not None:
                    assert pcm != previous, "LSF intensity-scale bit was not exercised"
                previous = pcm
                result.append(case)
        free_case = c_decode(f"syntax-free-{rate}-mixed-padding", lsf_syntax(rate,3,1,free=True))
        assert free_case["pcm"].read_bytes() == result[-1]["pcm"].read_bytes()
        free_data = free_case["path"].read_bytes()
        assert {free_data[pos+2] >> 1 & 1 for pos,*_ in frame_records(free_data)} == {0,1}
        result.append(free_case)
    return result


def verified_corpus(policy):
    cases = {c["id"]:c for c in json.loads((ROOT / "tests/corpus/manifest.json").read_text())["cases"]}
    for case in cases.values():
        assert hashlib.sha256((ROOT / case["path"]).read_bytes()).hexdigest() == case["sha256"]
        if "reference_pcm" in case:
            assert hashlib.sha256((ROOT / case["reference_pcm"]).read_bytes()).hexdigest() == case["reference_sha256"]
    applicable = [c for c in cases.values() if c["category"] in ("normal","alignment")]
    assert len(applicable) == 25 and sum(c["category"] == "normal" for c in applicable) == 24
    for case in applicable:
        name = case["id"]
        frozen = policy["expected"][name]
        assert json.loads((ROOT / f"target/reference/{name}-f32-raw.json").read_text()) == frozen["metadata"]
        for suffix, field in (("f32-raw","f32_sha256"),("ffmpeg-f32","ffmpeg_sha256")):
            assert hashlib.sha256((ROOT / f"target/reference/{name}-{suffix}.pcm").read_bytes()).hexdigest() == frozen[field]
    return cases, applicable


def native_gate(executable, cases, applicable, policy):
    successes = []
    for case in applicable:
        name = case["id"]
        if name == "l3-hecommon":
            continue
        meta = policy["expected"][name]["metadata"]
        output = OUT / f"{name}-moon.pcm"
        env = {**os.environ, "MP3_VALIDATION_INPUT": str(ROOT/case["path"]), "MP3_VALIDATION_OUTPUT": str(output)}
        process = subprocess.run([str(executable)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=90, check=True)
        rate, channels, count = map(int,process.stdout.split())
        actual_meta = {"sample_rate":rate,"channels":channels,"sample_count":count}
        actual = read_pcm(output,"f32le")
        comparison = compare(read_pcm(ROOT/f"target/reference/{name}-f32-raw.pcm","f32le"),actual,meta,actual_meta,**policy["f32"])
        assert comparison["passed"], (name,comparison)
        if "reference_pcm" in case:
            original = read_pcm(ROOT/case["reference_pcm"],"s16le")
            assert len(actual)-len(original) == policy["legacy_pcm_extra_interleaved_samples"].get(name,0)
            short_meta = {**meta,"sample_count":len(original)}
            s16 = compare(original,[to_s16(v)/32768 for v in actual[:len(original)]],short_meta,short_meta,**policy["s16"])
            assert s16["passed"], (name,s16)
        ff = read_pcm(ROOT/f"target/reference/{name}-ffmpeg-f32.pcm","f32le")
        probe = json.loads(subprocess.check_output(["ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=sample_rate,channels","-of","json",str(ROOT/case["path"])],text=True))["streams"][0]
        fm = {"sample_rate":int(probe["sample_rate"]),"channels":probe["channels"],"sample_count":len(ff)}
        independent = compare(ff,actual,fm,actual_meta,**policy["f32"])
        exception = policy["ffmpeg_exceptions"].get(name)
        if exception:
            assert not independent["passed"] and independent["reason"] == exception["reason"], (name,independent)
        else:
            assert independent["passed"], (name,independent)
        print(f"PASS full {name}: {rate} Hz/{channels} ch, {count} samples, RMSE={comparison['rmse']:.9g}, max={comparison['max_abs_error']:.9g}",flush=True)
        successes.append(name)
    assert set(successes) == {c["id"] for c in applicable} - {"l3-hecommon"}
    for name, reason in {"l3-hecommon":"InvalidHeader", "l3-compl":"TruncatedFrame", "l3-sin1k0db":"InsufficientHistory"}.items():
        env = {**os.environ,"MP3_VALIDATION_INPUT":str(ROOT/cases[name]["path"]),"MP3_VALIDATION_OUTPUT":str(OUT/"rejected.pcm")}
        result = subprocess.run([str(executable)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
        assert result.returncode == 2 and reason in result.stdout,(name,result.returncode,result.stdout)
        print(f"PASS strict {name}: {result.stdout.strip()}",flush=True)


def prepare_representatives(cases,policy):
    result = []
    names = (*GENERATED,"generated-gapless-tagged","l3-he_free","l3-si_block","l3-si_huff","l3-he_32khz","l3-hecommon","l3-test45","l3-test46","M2L3_compl24","M2L3_noise","M2L3_bitrate_16_all","M2L3_bitrate_22_all","M2L3_bitrate_24_all")
    for name in names:
        data = (ROOT/cases[name]["path"]).read_bytes()
        if name == "l3-hecommon":
            data = prefix(data,10)
        elif name.startswith(("l3-test","M2L3_")):
            data = prefix(data,32)
        elif name in ("l3-si_huff","l3-he_32khz"):
            data = prefix(data,16)
        result.append(c_decode(name+"-representative",data))
    assert {c["metadata"]["sample_rate"] for c in result} == RATES
    result.extend(extras(cases,policy))
    return result


def eight_khz_structural_checks():
    """Exercise the corrected 8-kHz mixed path without inventing a PCM oracle.

    Pinned minimp3 has an out-of-bounds mixed reorder. Pinned FFmpeg explicitly
    reports that its 8-kHz mixed switch point is unimplemented. Its PCM is not
    an expected output. These checks cover bounded API state and fragmentation;
    corrected-table C transform checks and band invariants are maintained in
    the production test suite.
    """
    lines = []
    for extension,shift,free in ((0,0,False),(2,0,False),(1,0,False),(1,1,False),
                                 (3,0,False),(3,1,False),(3,1,True)):
        name = f"8khz-mixed-joint-{extension}-shift-{shift}-free-{int(free)}"
        data = lsf_syntax(8000,extension,shift,free=free)
        (OUT/f"{name}.mp3").write_bytes(data)
        records = frame_records(data)
        offsets = "[" + ", ".join(f"{row[0]}L" for row in records) + "]"
        lines += ['///|',f'test "structural streaming only, no independent PCM oracle: {name}" {{',
                  '  let data = compatibility_bytes('+literal(data)+')',
                  '  let audio = decode_all(data)',
                  '  assert_eq(audio.sample_rate, 8000)', '  assert_eq(audio.channels, 2)',
                  f'  assert_eq(audio.samples.length(), {len(records)*576*2})',
                  '  let mut nonzero = 0',
                  '  for sample in audio.samples {',
                  '    let value = sample.to_double()',
                  '    assert_true(!value.is_nan() && !value.is_inf())',
                  '    if sample != 0.0 { nonzero += 1 }', '  }',
                  '  assert_true(nonzero > 100)',
                  f'  let offsets : Array[Int64] = {offsets}',
                  '  for mode = 0; mode < 4; mode = mode + 1 { compatibility_fragmented(data, audio, offsets, mode) }']
        if free:
            lines += ['  let indexed = compatibility_bytes('+literal(lsf_syntax(8000,extension,shift))+')',
                      '  assert_eq(audio.samples, decode_all(indexed).samples)']
        lines += ['}']
    return lines


def generate_suite(representatives,policy):
    workspace = snapshot_module(output_root=OUT)
    # Reuse the same source snapshot and byte format as MPEG-1 verification.
    lines = ['///|','fn compatibility_bytes(chunks : Array[Bytes]) -> Bytes {','  let values : Array[Byte] = []','  for chunk in chunks { for value in chunk { values.push(value) } }','  Bytes::from_array(values)','}',
             '///|','fn compatibility_float(bytes : Bytes, i : Int) -> Float {','  let p = i * 4','  Float::reinterpret_from_uint(bytes[p].to_uint() | (bytes[p+1].to_uint() << 8) | (bytes[p+2].to_uint() << 16) | (bytes[p+3].to_uint() << 24))','}', STREAM_CHECK]
    for case in representatives:
        name,meta = case["id"],case["metadata"]
        offsets = "[" + ", ".join(f"{row[0]}L" for row in frame_records(case["path"].read_bytes())) + "]"
        lines += ['///|',f'test "three-version full PCM and streaming {name}" {{','  let data = compatibility_bytes('+literal(case["path"].read_bytes())+')','  let expected = compatibility_bytes('+literal(case["pcm"].read_bytes())+')','  let audio = decode_all(data)',f'  assert_eq(audio.sample_rate, {meta["sample_rate"]})',f'  assert_eq(audio.channels, {meta["channels"]})',f'  assert_eq(audio.samples.length(), {meta["sample_count"]})','  let mut squared = 0.0','  let mut maximum = 0.0','  for i = 0; i < audio.samples.length(); i = i + 1 {','    let value = audio.samples[i].to_double()','    assert_true(!value.is_nan() && !value.is_inf())','    let error = (value - compatibility_float(expected, i).to_double()).abs()','    squared += error * error','    if error > maximum { maximum = error }','  }',f'  assert_true(maximum <= {policy["f32"]["max_abs_error"]})',f'  assert_true(squared / audio.samples.length().to_double() <= {policy["f32"]["max_rmse"]**2:.16e})',f'  assert_true(squared / audio.samples.length().to_double() <= {(32767/32768)**2*10**(-policy["f32"]["min_psnr_db"]/10):.16e})',f'  let offsets : Array[Int64] = {offsets}', '  for mode = 0; mode < 4; mode = mode + 1 { compatibility_fragmented(data, audio, offsets, mode) }','}']
    lines += eight_khz_structural_checks()
    (workspace/"integration_wbtest.mbt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    trace_exe = OUT/"layer3_trace.exe"
    run(["gcc","-std=c99","-O2","-ffp-contract=off","-Wall","-Wextra","-Werror","tools/layer3_trace.c","-lm","-o",trace_exe])
    traces = [(ROOT/"tools/trace_check.mbt.in").read_text(encoding="utf-8")]
    for case in representatives:
        name = case["id"]
        count = min(28 if "si_block" in name else 9 if name.startswith(("syntax-lsf", "syntax-free")) else 8,case["metadata"]["decoded_frames"])
        expected = OUT/f"{name}-trace.bin"
        run([trace_exe,case["path"],expected,count])
        data = prefix(case["path"].read_bytes(),count)
        traces += ['///|',f'test "three-version continuous checkpoints {name}" {{','  let data = trace_bytes('+literal(data)+')','  let expected = trace_bytes('+literal(expected.read_bytes())+')',f'  check_continuous_trace(data, expected, {count})','}']
    (workspace/"internal/layer3/continuous_trace_wbtest.mbt").write_text("\n".join(traces)+"\n",encoding="utf-8")
    return workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-foundation",action="store_true",help="Reuse a foundation run; all cached oracle PCM and corpus hashes are still verified")
    parser.add_argument("--prepare-only",action="store_true",help="Prepare independent C PCM/checkpoints without requiring the MoonBit API")
    parser.add_argument("--backends",nargs="+",choices=BACKENDS,default=BACKENDS)
    args = parser.parse_args()
    verify()
    OUT.mkdir(parents=True,exist_ok=True)
    for generator in ("side_info_vectors", "spectral_tables", "spectral_vectors",
                      "transform_tables", "transform_vectors", "synthesis_tables",
                      "synthesis_vectors", "decoder_state_vectors", "framing_vectors",
                      "low_version_vectors"):
        run([sys.executable, f"tools/generate_{generator}.py", "--check"])
    if not args.skip_foundation:
        run([sys.executable,"tools/validate_stage1.py"])
    policy = json.loads((ROOT/"tests/reference_policy.json").read_text())
    cases,applicable = verified_corpus(policy)
    representatives = prepare_representatives(cases,policy)
    workspace = generate_suite(representatives,policy)
    if args.prepare_only:
        print(f"Prepared {len(representatives)} all-version PCM/checkpoint cases; all C traces equal unmodified decoder PCM. Seven additional 8-kHz mixed cases check structural streaming only, without an independent PCM oracle.")
        return
    native_gate(build_native_adapter(api="decode_all",output_root=OUT),cases,applicable,policy)
    for backend in args.backends:
        run(["moon","test","--target",backend,"--release","--deny-warn"])
        run(["moon","-C",workspace,"test","--target",backend,"--release","--deny-warn"])
    for validator in ("validate_iso_layer3", "validate_robustness", "validate_matrix"):
        extra = ["--require-all"] if validator == "validate_iso_layer3" else []
        run([sys.executable, f"tools/{validator}.py", *extra, "--backends", *args.backends])
    print("All 24 complete compatible corpus files, reserved-header prefix, nine rates, free-format, 12/24-kHz LSF intensity/mixed and continuous C checkpoints passed. This suite checks 8-kHz mixed structurally; tools/verify_mixed_8000.py separately checks its documented subset against a narrowly patched independent decoder.")


if __name__ == "__main__":
    main()
