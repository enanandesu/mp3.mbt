///|
fn raw(b1 : Int, b2 : Int, b3 : Int) -> Bytes {
  Bytes::from_array([255, b1.to_byte(), b2.to_byte(), b3.to_byte()])
}

///|
test "MPEG1 joint stereo header and offsets" {
  let h = parse(b"\xff\xfb\x90\x64").unwrap()
  assert_eq(h.version, Mpeg1)
  assert_eq(h.bitrate_kbps, Some(128))
  assert_eq(h.sample_rate_hz, 44100)
  assert_eq(h.channel_mode, JointStereo)
  assert_eq(h.mode_extension, 2)
  assert_eq(h.original, true)
  assert_eq(h.copyright, false)
  assert_eq(h.private_bit, false)
  assert_eq(h.emphasis, NoEmphasis)
  assert_eq(h.channels(), 2)
  assert_eq(h.samples_per_frame(), 1152)
  assert_eq(h.side_info_bytes(), 32)
  assert_eq(h.main_data_offset(), 36)
  assert_eq(h.crc_bytes(), 0)
  assert_eq(h.frame_bytes(), Ok(Some(417)))
  assert_eq(h.mid_side_stereo(), true)
  assert_eq(h.intensity_stereo(), false)
  assert_eq(parse(b"garbage\xff\xfb\x90\x64tail", offset=7), Ok(h))
}

///|
test "all header truncation lengths and offset boundaries" {
  assert_eq(parse(b""), Err(Truncated(available=0)))
  assert_eq(parse(b"\xff"), Err(Truncated(available=1)))
  assert_eq(parse(b"\xff\xfb"), Err(Truncated(available=2)))
  assert_eq(parse(b"\xff\xfb\x90"), Err(Truncated(available=3)))
  assert_eq(parse(b"\xff\xfb\x90\x00", offset=4), Err(Truncated(available=0)))
  assert_eq(parse(b"\xff\xfb\x90\x00", offset=2), Err(Truncated(available=2)))
  assert_eq(parse(b"", offset=-1), Err(InvalidOffset(-1)))
  assert_eq(parse(b"", offset=2147483647), Err(InvalidOffset(2147483647)))
  assert_eq(parse(b"", offset=-2147483648), Err(InvalidOffset(-2147483648)))
  // CRC belongs to the payload. Four bytes suffice to parse a protected header.
  assert_eq(parse(raw(0xfa, 0x90, 0)).unwrap().crc_bytes(), 2)
}

///|
test "reserved fields and unsupported layers have explicit errors" {
  assert_eq(parse(b"\xfe\xfb\x90\x00"), Err(InvalidSync))
  assert_eq(parse(raw(0xdb, 0x90, 0)), Err(InvalidSync))
  assert_eq(parse(raw(0xeb, 0x90, 0)), Err(ReservedVersion))
  assert_eq(parse(raw(0xf9, 0x90, 0)), Err(ReservedLayer))
  assert_eq(parse(raw(0xfd, 0x90, 0)), Err(UnsupportedLayer(2)))
  assert_eq(parse(raw(0xff, 0x90, 0)), Err(UnsupportedLayer(1)))
  assert_eq(parse(raw(0xfb, 0xf0, 0)), Err(InvalidBitrateIndex))
  assert_eq(parse(raw(0xfb, 0x9c, 0)), Err(InvalidSampleRateIndex))
  assert_eq(parse(raw(0xfb, 0x90, 2)), Err(ReservedEmphasis))
  assert_eq(parse(raw(0xfb, 0x90, 1)).unwrap().emphasis, FiftyFifteen)
  assert_eq(parse(raw(0xfb, 0x90, 3)).unwrap().emphasis, CcitJ17)
}

///|
test "free format remains unknown without caller supplied unpadded frame size" {
  let h = parse(raw(0xfa, 0x02, 0)).unwrap()
  assert_eq(h.bitrate_kbps, None)
  assert_eq(h.frame_bytes(), Ok(None))
  assert_eq(h.main_data_offset(), 38)
  assert_eq(h.frame_bytes(free_format_size=1000), Ok(Some(1001)))
  assert_eq(h.frame_bytes(free_format_size=38), Ok(Some(39)))
  assert_eq(h.frame_bytes(free_format_size=37), Ok(Some(38)))
  for size in [-2147483648, -1, 0, 4, 36, 2147483647] {
    assert_eq(
      h.frame_bytes(free_format_size=size),
      Err(InvalidFreeFormatSize(size)),
    )
  }
  assert_eq(h.frame_bytes(free_format_size=2147483646), Ok(Some(2147483647)))
  let unpadded = parse(raw(0xfb, 0, 0)).unwrap()
  assert_eq(
    unpadded.frame_bytes(free_format_size=2147483647),
    Ok(Some(2147483647)),
  )
  // Context applies only to free-format headers, as in hdr_frame_bytes.
  let fixed = parse(raw(0xfb, 0x90, 0)).unwrap()
  assert_eq(fixed.frame_bytes(free_format_size=-1), Ok(Some(417)))
}

///|
test "mode extension is meaningful only for joint stereo" {
  for mode in 0..<4 {
    for extension in 0..<4 {
      let h = parse(raw(0xf3, 0x81, (mode << 6) | (extension << 4) | 12)).unwrap()
      assert_eq(h.mode_extension, extension)
      assert_eq(h.mid_side_stereo(), mode == 1 && (extension & 2) != 0)
      assert_eq(h.intensity_stereo(), mode == 1 && (extension & 1) != 0)
      assert_eq(h.channels(), if mode == 3 { 1 } else { 2 })
      assert_eq(h.private_bit, true)
      assert_eq(h.copyright, true)
      assert_eq(h.original, true)
    }
  }
}

///|
test "sync and stream compatibility permit VBR and forbid format changes" {
  let h = parse(raw(0xfb, 0x90, 0)).unwrap()
  for
    other in [
      raw(0xfa, 0xa2, 0x70),
      raw(0xfb, 0x10, 0x80),
      raw(0xfb, 0xe1, 0x0d),
    ] {
    let h2 = parse(other).unwrap()
    assert_eq(h.sync_compatible(h2), true)
    assert_eq(h.stream_compatible(h2), true)
    assert_eq(h2.stream_compatible(h), true)
  }
  let mono = parse(raw(0xfb, 0x90, 0xc0)).unwrap()
  assert_eq(h.sync_compatible(mono), true)
  assert_eq(h.stream_compatible(mono), false)
  for
    other in [
      raw(0xf3, 0x90, 0),
      raw(0xe3, 0x90, 0),
      raw(0xfb, 0x94, 0),
      raw(0xfb, 0, 0),
    ] {
    let h2 = parse(other).unwrap()
    assert_eq(h.sync_compatible(h2), false)
    assert_eq(h.stream_compatible(h2), false)
  }
  let free = parse(raw(0xfb, 0, 0)).unwrap()
  assert_eq(free.sync_compatible(parse(raw(0xfa, 2, 0x40)).unwrap()), true)
}

///|
test "all 65536 second and third byte combinations are bounded and classified" {
  let mut accepted = 0
  for b1 in 0..<256 {
    for b2 in 0..<256 {
      let expect_ok = [0xe2, 0xe3, 0xf2, 0xf3, 0xfa, 0xfb].contains(b1) &&
        b2 < 240 &&
        (b2 & 12) != 12
      match parse(raw(b1, b2, 0)) {
        Ok(h) => {
          assert_eq(expect_ok, true)
          assert_eq(h.main_data_offset() >= 13, true)
          accepted += 1
        }
        Err(_) => assert_eq(expect_ok, false)
      }
    }
  }
  assert_eq(accepted, 1080)
}

///|
test "frame length includes padding and CRC is not added twice" {
  let plain = parse(raw(0xfb, 0x90, 0)).unwrap()
  let crc = parse(raw(0xfa, 0x90, 0)).unwrap()
  let padded = parse(raw(0xfa, 0x92, 0)).unwrap()
  assert_eq(plain.frame_bytes(), Ok(Some(417)))
  assert_eq(crc.frame_bytes(), Ok(Some(417)))
  assert_eq(padded.frame_bytes(), Ok(Some(418)))
  assert_eq(crc.main_data_offset() - plain.main_data_offset(), 2)
}
