///|
fn framing_stream(
  version : Int,
  rate : Int,
  channels : Int,
  crc : Int,
  pad_mask : Int,
  base : Int,
  count? : Int = 4,
) -> Bytes {
  let bytes : Array[Byte] = []
  for frame = 0; frame < count; frame = frame + 1 {
    let pad = (pad_mask >> frame) & 1
    bytes.push(255)
    bytes.push(([251, 243, 227][version] - crc).to_byte())
    bytes.push(((rate << 2) | (pad << 1)).to_byte())
    bytes.push(if channels == 1 { 192 } else { 0 })
    for _i = 4; _i < base + pad; _i = _i + 1 {
      bytes.push(0)
    }
  }
  Bytes::from_array(bytes)
}

///|
fn framing_header(data : Bytes) -> @header.Header {
  @header.parse(data).unwrap()
}

///|
test "coded bitrate frames need only their own complete bytes" {
  let data = Bytes::makei(417, fn(i) {
    match i {
      0 => 255
      1 => 251
      2 => 144
      3 => 192
      _ => 0
    }
  })
  let header = framing_header(data)
  for n = 4; n < 417; n = n + 1 {
    let part = data[:n].to_bytes()
    assert_eq(probe(part, header, false, None), NeedMoreInput(417))
    assert_eq(probe(part, header, true, None), Invalid(Truncated(417, n)))
  }
  assert_eq(probe(data, header, false, None), Frame(417, None))
  assert_eq(probe(data, header, true, None), Frame(417, None))
}

///|
test "free discovery waits for three headers across every input prefix" {
  let full = framing_stream(0, 0, 2, 0, 0, 64)
  let header = framing_header(full)
  for n = 0; n < 132; n = n + 1 {
    let part = full[:n].to_bytes()
    match probe(part, header, false, None) {
      NeedMoreInput(required) => {
        assert_true(required > n)
        assert_true(required <= 4614)
      }
      other => fail("expected incomplete discovery, got \{other}")
    }
  }
  assert_eq(
    probe(full[:132].to_bytes(), header, false, None),
    Frame(64, Some(64)),
  )
  assert_eq(probe(full, header, true, None), Frame(64, Some(64)))
}

///|
test "unknown free supports exactly two complete EOF frames but never one" {
  for version in [0, 1, 2] {
    for mask in [0, 1, 2, 3] {
      let pair = framing_stream(version, 0, 1, 0, mask, 64, count=2)
      let header = framing_header(pair)
      assert_eq(
        probe(pair, header, true, None),
        Frame(64 + (mask & 1), Some(64)),
      )
      let one = pair[:64 + (mask & 1)].to_bytes()
      assert_eq(probe(one, header, true, None), Invalid(FreeFormatUnconfirmed))
      let partial_pair = pair[:pair.length() - 1].to_bytes()
      assert_eq(
        probe(partial_pair, header, true, None),
        Invalid(FreeFormatUnconfirmed),
      )
    }
  }
}

///|
test "known free handles padding EOF final frame and exact truncation" {
  for pad in [0, 1] {
    let frame = framing_stream(0, 0, 2, 1, pad, 64, count=1)
    let header = framing_header(frame)
    assert_eq(probe(frame, header, false, Some(64)), Frame(64 + pad, Some(64)))
    assert_eq(probe(frame, header, true, Some(64)), Frame(64 + pad, Some(64)))
    for n = 4; n < frame.length(); n = n + 1 {
      let part = frame[:n].to_bytes()
      assert_eq(probe(part, header, false, Some(64)), NeedMoreInput(64 + pad))
      assert_eq(
        probe(part, header, true, Some(64)),
        Invalid(Truncated(64 + pad, n)),
      )
    }
    // Boundary validity belongs to the caller; a supplied base is never
    // replaced by searching payload bytes for an alternative sync.
    assert_eq(
      probe(frame, header, true, Some(65)),
      Invalid(Truncated(65 + pad, 64 + pad)),
    )
  }
}

///|
test "false payload sync is skipped unless consecutive spacing confirms it" {
  let original = framing_stream(0, 0, 2, 0, 0, 100)
  let false_sync = Bytes::makei(original.length(), fn(i) {
    if i >= 46 && i < 50 {
      original[i - 46]
    } else {
      original[i]
    }
  })
  assert_eq(
    probe(false_sync, framing_header(original), false, None),
    Frame(100, Some(100)),
  )
  let different_channels = Bytes::makei(300, fn(i) {
    if i == 103 {
      192
    } else {
      original[i]
    }
  })
  assert_eq(
    probe(different_channels, framing_header(original), true, None),
    Invalid(FreeFormatUnconfirmed),
  )
}

///|
test "free base limit includes 2304 and permits its padding byte" {
  for mask in [0, 1, 2, 5, 7] {
    let maximum = framing_stream(0, 0, 2, 0, mask, 2304)
    let header = framing_header(maximum)
    assert_eq(
      probe(maximum[:4614].to_bytes(), header, false, None),
      Frame(2304 + (mask & 1), Some(2304)),
    )
  }
  let oversized = framing_stream(0, 0, 2, 0, 0, 2305)
  let header = framing_header(oversized)
  assert_eq(
    probe(oversized, header, false, None),
    Invalid(FreeFormatSearchLimit(2304)),
  )
  assert_eq(
    probe(oversized, header, true, Some(2305)),
    Invalid(InvalidFreeFormatSize(2305)),
  )
  let no_headers = Bytes::makei(4614, fn(i) {
    if i < 4 {
      oversized[i]
    } else {
      0
    }
  })
  assert_eq(
    probe(no_headers, header, false, None),
    Invalid(FreeFormatSearchLimit(2304)),
  )
}

///|
test "free candidates must fit each frame CRC and side information" {
  let too_small = framing_stream(0, 0, 2, 0, 0, 20)
  let header = framing_header(too_small)
  assert_eq(
    probe(too_small, header, true, Some(20)),
    Invalid(InvalidFreeFormatSize(20)),
  )
  let minimum = framing_stream(0, 0, 2, 1, 7, 37)
  assert_eq(
    probe(minimum, framing_header(minimum), false, None),
    Frame(38, Some(37)),
  )
  assert_eq(
    probe(minimum, framing_header(minimum), true, None, max_free_size=36),
    Invalid(InvalidFreeFormatSize(36)),
  )
}

///|
test "all invalid inputs return structured results without traps" {
  let full = framing_stream(0, 0, 1, 0, 0, 64)
  let header = framing_header(full)
  for length in [0, 1, 2, 3] {
    let short = full[:length].to_bytes()
    assert_eq(probe(short, header, false, None), NeedMoreInput(4))
    assert_eq(probe(short, header, true, None), Invalid(Truncated(4, length)))
  }
  assert_eq(probe(b"garbage", header, false, None), Invalid(InvalidHeader))
  assert_eq(
    probe(full, framing_header(framing_stream(1, 0, 1, 0, 0, 64)), false, None),
    Invalid(HeaderMismatch),
  )
  for size in [-2147483648, -1, 0, 20, 2305, 2147483647] {
    assert_eq(
      probe(full, header, false, Some(size)),
      Invalid(InvalidFreeFormatSize(size)),
    )
  }
  for limit in [-2147483648, -1, 0, 3, 1073741821, 2147483647] {
    assert_eq(
      probe(full, header, false, None, max_free_size=limit),
      Invalid(InvalidLimit(limit)),
    )
  }
  for seed = 0; seed < 128; seed = seed + 1 {
    let data = Bytes::makei(96, fn(i) { ((seed * 91 + i * 37) & 255).to_byte() })
    assert_eq(probe(data, header, seed % 2 == 0, None), Invalid(InvalidHeader))
  }
}
