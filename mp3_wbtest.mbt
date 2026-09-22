// Public whole-buffer MPEG-1 entry-point contracts. The frames have valid
// zero-spectrum side information; real nonzero DSP state is tested separately
// in internal/layer3/decoder_wbtest.mbt and continuous C-oracle fixtures.

///|
fn entry_frame(channels : Int, rate? : Int = 0, history? : Int = 0) -> Bytes {
  let length = 144000 * 128 / [44100, 48000, 32000][rate]
  Bytes::makei(length, fn(i) {
    match i {
      0 => 255
      1 => 251
      2 => (144 | (rate << 2)).to_byte()
      3 => if channels == 1 { 192 } else { 0 }
      4 => (history >> 1).to_byte()
      5 => ((history & 1) << 7).to_byte()
      _ => 0
    }
  })
}

///|
fn entry_join(left : Bytes, right : Bytes) -> Bytes {
  Bytes::makei(left.length() + right.length(), fn(i) {
    if i < left.length() {
      left[i]
    } else {
      right[i - left.length()]
    }
  })
}

///|
fn entry_error(
  data : Bytes,
  max_output_samples? : Int = 64 * 1024 * 1024,
  max_initial_scan? : Int = 65536,
) -> Mp3Error? {
  try {
    let _ = decode_mpeg1(data, max_output_samples~, max_initial_scan~)
    None
  } catch {
    error => Some(error)
  }
}

///|
test "complete MPEG1 frames expose sample rate channels and interleaved count" {
  for channels in [1, 2] {
    for rate in [0, 1, 2] {
      let frame = entry_frame(channels, rate~)
      let audio = decode_mpeg1(frame, max_initial_scan=0)
      assert_eq(audio.sample_rate, [44100, 48000, 32000][rate])
      assert_eq(audio.channels, channels)
      assert_eq(audio.samples, Array::make(1152 * channels, 0.0))
      let audio = decode_mpeg1(entry_join(frame, frame))
      assert_eq(audio.samples.length(), 2304 * channels)
    }
  }
}

///|
test "whole-buffer output limits count interleaved samples and reject negatives" {
  let mono = entry_frame(1)
  let stereo = entry_frame(2)
  assert_eq(decode_mpeg1(mono, max_output_samples=1152).samples.length(), 1152)
  assert_eq(entry_error(mono, max_output_samples=1151), Some(OutputLimit))
  assert_eq(
    decode_mpeg1(stereo, max_output_samples=2304).samples.length(),
    2304,
  )
  assert_eq(entry_error(stereo, max_output_samples=2303), Some(OutputLimit))
  assert_eq(
    entry_error(entry_join(mono, mono), max_output_samples=2303),
    Some(OutputLimit),
  )
  assert_eq(entry_error(mono, max_output_samples=0), Some(OutputLimit))
  assert_eq(entry_error(mono, max_output_samples=-1), Some(OutputLimit))
  assert_eq(entry_error(mono, max_initial_scan=-1), Some(OutputLimit))
}

///|
test "leading scan budget permits exactly the configured skipped bytes" {
  let frame = entry_frame(1)
  let prefixed = entry_join(b"xyz", frame)
  assert_eq(decode_mpeg1(prefixed, max_initial_scan=3).samples.length(), 1152)
  assert_eq(entry_error(prefixed, max_initial_scan=2), Some(InvalidHeader(2)))
  assert_eq(entry_error(prefixed, max_initial_scan=0), Some(InvalidHeader(0)))
  assert_eq(entry_error(b"xyz", max_initial_scan=3), Some(NoAudio))
  assert_eq(entry_error(b"xyz", max_initial_scan=2), Some(InvalidHeader(2)))
  // After accepting a frame, corruption is fatal regardless of unused scan budget.
  assert_eq(entry_error(entry_join(frame, b"xyz")), Some(InvalidHeader(417)))
}

///|
test "empty and truncated whole-buffer inputs have explicit errors" {
  let frame = entry_frame(1)
  assert_eq(entry_error(b""), Some(NoAudio))
  assert_eq(
    entry_error(b"", max_output_samples=0, max_initial_scan=0),
    Some(NoAudio),
  )
  let short = frame[:416].to_bytes()
  assert_eq(entry_error(short), Some(TruncatedFrame(0, 417)))
  assert_eq(
    entry_error(entry_join(b"xyz", short)),
    Some(TruncatedFrame(3, 417)),
  )
  assert_eq(
    entry_error(entry_join(frame, frame[:4].to_bytes())),
    Some(TruncatedFrame(417, 417)),
  )
  assert_eq(
    entry_error(entry_join(frame, frame[:3].to_bytes())),
    Some(InvalidHeader(417)),
  )
}

///|
test "ID3v2 prefix and ID3v1 suffix preserve audio and scan accounting" {
  let frame = entry_frame(1)
  let prefix = b"ID3\x04\x00\x00\x00\x00\x00\x03abc"
  let suffix = Bytes::makei(128, fn(i) {
    match i {
      0 => b'T'
      1 => b'A'
      2 => b'G'
      _ => 0
    }
  })
  let tagged = entry_join(entry_join(prefix, frame), suffix)
  let audio = decode_mpeg1(tagged, max_initial_scan=0)
  assert_eq(audio.channels, 1)
  assert_eq(audio.sample_rate, 44100)
  assert_eq(audio.samples, decode_mpeg1(frame).samples)
  let twice = entry_join(prefix, tagged)
  assert_eq(decode_mpeg1(twice, max_initial_scan=0).samples, audio.samples)
  let garbage = entry_join(prefix, entry_join(b"xyz", frame))
  assert_eq(decode_mpeg1(garbage, max_initial_scan=3).samples, audio.samples)
  assert_eq(entry_error(garbage, max_initial_scan=2), Some(InvalidHeader(15)))
  assert_eq(entry_error(prefix), Some(NoAudio))
  assert_eq(entry_error(suffix), Some(NoAudio))
  assert_eq(entry_error(entry_join(prefix, suffix)), Some(NoAudio))
}

///|
test "malformed oversized and truncated ID3 prefixes are rejected" {
  for
    prefix in [
      b"ID3", b"ID3\x04\x00\x00\x80\x00\x00\x00", b"ID3\x04\x00\x01\x00\x00\x00\x00",
      b"ID3\x04\x00\x00\x08\x00\x00\x00", b"ID3\x04\x00\x00\x00\x00\x00\x7f",
    ] {
    assert_eq(entry_error(prefix), Some(InvalidTag))
  }
}

///|
test "reservoir failure is wrapped with exact source offset" {
  let dependent = entry_frame(1, history=1)
  assert_eq(
    entry_error(entry_join(b"xyz", dependent)),
    Some(DecodeFailure(3, @layer3.InsufficientHistory(1, 0))),
  )
  let first = entry_frame(1)
  // A complete zero-spectrum mono frame retains its 396 payload bytes.
  assert_eq(
    entry_error(entry_join(first, entry_frame(1, history=511))),
    Some(DecodeFailure(417, @layer3.InsufficientHistory(511, 396))),
  )
}

///|
test "MPEG2 and free format are explicitly outside this whole-buffer API" {
  // Four valid header bytes suffice to identify the unsupported format before
  // complete-frame size checking; the decoder must not guess a frame boundary.
  assert_eq(entry_error(b"\xff\xf3\x90\xc0"), Some(UnsupportedVersion))
  assert_eq(entry_error(b"\xff\xfb\x00\xc0"), Some(UnsupportedFreeFormat))
}
