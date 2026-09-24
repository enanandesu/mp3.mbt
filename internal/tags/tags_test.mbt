///|
fn leading(
  version : Int,
  flags : Int,
  payload : Int,
  revision? : Int = 0,
  body? : Bool = true,
) -> Bytes {
  let data : Array[Byte] = [
    b'I',
    b'D',
    b'3',
    version.to_byte(),
    revision.to_byte(),
    flags.to_byte(),
    ((payload >> 21) & 127).to_byte(),
    ((payload >> 14) & 127).to_byte(),
    ((payload >> 7) & 127).to_byte(),
    (payload & 127).to_byte(),
  ]
  if body {
    for _ in 0..<payload {
      data.push(b'x')
    }
    if version == 4 && (flags & 16) != 0 {
      data.push(b'3')
      data.push(b'D')
      data.push(b'I')
      for index in 3..<10 {
        data.push(data[index])
      }
    }
  }
  Bytes::from_array(data)
}

///|
test "partial signatures distinguish EOF from temporary shortage" {
  assert_eq(inspect_id3v2(b""[:], false, 1024), NeedMoreInput(3))
  assert_eq(inspect_id3v2(b""[:], true, 1024), NotATag)
  assert_eq(inspect_id3v2(b"I"[:], false, 1024), NeedMoreInput(3))
  assert_eq(inspect_id3v2(b"ID"[:], true, 1024), Invalid(Truncated(3, 2)))
  assert_eq(inspect_id3v2(b"ID3"[:], false, 1024), NeedMoreInput(10))
  assert_eq(inspect_id3v2(b"ID3"[:], true, 1024), Invalid(Truncated(10, 3)))
  for bytes in [b"X", b"IX", b"IDx", b"xxxID3"] {
    assert_eq(inspect_id3v2(bytes[:], false, 1024), NotATag)
  }
}

///|
test "all split points preserve the complete tag and footer boundary" {
  for flags in [0, 16] {
    let bytes = leading(4, flags, 13)
    let total = bytes.length()
    for length in 1..<total {
      let expected = if length < 3 {
        3
      } else if length < 10 {
        10
      } else {
        total
      }
      assert_eq(
        inspect_id3v2(bytes[:length], false, 4096),
        NeedMoreInput(expected),
      )
      assert_eq(
        inspect_id3v2(bytes[:length], true, 4096),
        Invalid(Truncated(expected, length)),
      )
    }
    assert_eq(
      inspect_id3v2(bytes[:], false, total),
      Tag({
        version: 4,
        revision: 0,
        flags,
        payload_bytes: 13,
        total_bytes: total,
      }),
    )
    assert_eq(
      inspect_id3v2(bytes[:], true, total),
      inspect_id3v2(bytes[:], false, total),
    )
  }
}

///|
test "size uses all four synchsafe groups and rejects every high bit" {
  for payload in [0, 1, 127, 128, 16383, 16384, 2097151, 2097152, 268435455] {
    let bytes = leading(3, 0, payload, body=false)
    if payload == 0 {
      assert_eq(
        inspect_id3v2(bytes[:], false, 268435475),
        Tag({
          version: 3,
          revision: 0,
          flags: 0,
          payload_bytes: 0,
          total_bytes: 10,
        }),
      )
    } else {
      assert_eq(
        inspect_id3v2(bytes[:], false, 268435475),
        NeedMoreInput(payload + 10),
      )
    }
  }
  for index in 6..<10 {
    let data = leading(3, 0, 0).to_array()
    data[index] = 128
    assert_eq(
      inspect_id3v2(Bytes::from_array(data)[:], false, 4096),
      Invalid(InvalidSynchsafeSize),
    )
  }
}

///|
test "version flags and compatible revisions are explicit" {
  for version in [0, 1, 5, 255] {
    assert_eq(
      inspect_id3v2(leading(version, 0, 0)[:], true, 4096),
      Invalid(UnsupportedVersion(version)),
    )
  }
  for version in [2, 3, 4] {
    assert_eq(
      inspect_id3v2(leading(version, 0, 0, revision=255)[:], true, 4096),
      Invalid(InvalidRevision(255)),
    )
    for flags in 0..<256 {
      let reserved = if version == 2 {
        63
      } else if version == 3 {
        31
      } else {
        15
      }
      let result = inspect_id3v2(
        leading(version, flags, 0, revision=254)[:],
        true,
        4096,
      )
      if (flags & reserved) != 0 {
        assert_eq(result, Invalid(InvalidFlags(flags)))
      } else {
        let total = if version == 4 && (flags & 16) != 0 { 20 } else { 10 }
        assert_eq(
          result,
          Tag({
            version,
            revision: 254,
            flags,
            payload_bytes: 0,
            total_bytes: total,
          }),
        )
      }
    }
  }
}

///|
test "limits count header footer and reject before waiting or allocating" {
  assert_eq(inspect_id3v2(b""[:], false, -1), Invalid(InvalidLimit))
  assert_eq(inspect_id3v2(b"audio"[:], true, 0), NotATag)
  assert_eq(inspect_id3v2(leading(3, 0, 0)[:], false, 0), Invalid(TooLarge(10)))
  assert_eq(
    inspect_id3v2(leading(4, 16, 0)[:], true, 19),
    Invalid(TooLarge(20)),
  )
  assert_eq(
    inspect_id3v2(leading(4, 16, 268435455, body=false)[:], false, 1048576),
    Invalid(TooLarge(268435475)),
  )
  assert_eq(
    inspect_id3v2(leading(4, 16, 268435455, body=false)[:], false, 268435475),
    NeedMoreInput(268435475),
  )
}

///|
test "footer copies all header fields and magic without consuming audio" {
  let original = leading(4, 16, 5)
  for index in 15..<25 {
    let data = original.to_array()
    data[index] = (data[index].to_int() ^ 1).to_byte()
    assert_eq(
      inspect_id3v2(Bytes::from_array(data)[:], true, 4096),
      Invalid(InvalidFooter),
    )
  }
  let data = original.to_array()
  data.push(255)
  data.push(251)
  assert_eq(
    inspect_id3v2(Bytes::from_array(data)[:], true, 25),
    Tag({
      version: 4,
      revision: 0,
      flags: 16,
      payload_bytes: 5,
      total_bytes: 25,
    }),
  )
}

///|
fn tail(audio : Int, enhanced : Bool, standard : Bool) -> Bytes {
  let data : Array[Byte] = Array::make(audio, b'x')
  if enhanced {
    data.push(b'T')
    data.push(b'A')
    data.push(b'G')
    data.push(b'+')
    for _ in 0..<223 {
      data.push(0)
    }
  }
  if standard {
    data.push(b'T')
    data.push(b'A')
    data.push(b'G')
    for _ in 0..<125 {
      data.push(0)
    }
  }
  Bytes::from_array(data)
}

///|
test "ID3v1 exact trailing boundary and optional TAG plus" {
  for audio in [0, 1, 127, 128, 227, 1024] {
    assert_eq(trim_id3v1(tail(audio, false, false)[:]), {
      audio_end: audio,
      tag_bytes: 0,
      enhanced: false,
    })
    assert_eq(trim_id3v1(tail(audio, false, true)[:]), {
      audio_end: audio,
      tag_bytes: 128,
      enhanced: false,
    })
    assert_eq(trim_id3v1(tail(audio, true, true)[:]), {
      audio_end: audio,
      tag_bytes: 355,
      enhanced: true,
    })
    assert_eq(trim_id3v1(tail(audio, true, false)[:]), {
      audio_end: audio + 227,
      tag_bytes: 0,
      enhanced: false,
    })
  }
  let bytes = tail(0, false, true)
  for length in 0..<128 {
    assert_eq(trim_id3v1(bytes[:length]), {
      audio_end: length,
      tag_bytes: 0,
      enhanced: false,
    })
  }
  let data = bytes.to_array()
  data.push(0)
  assert_eq(trim_id3v1(Bytes::from_array(data)[:]), {
    audio_end: 129,
    tag_bytes: 0,
    enhanced: false,
  })
}

///|
test "offset views keep all indexes local" {
  let bytes = b"noiseID3\x03\x00\x00\x00\x00\x00\x00audio"
  assert_eq(
    inspect_id3v2(bytes[5:], true, 10),
    Tag({
      version: 3,
      revision: 0,
      flags: 0,
      payload_bytes: 0,
      total_bytes: 10,
    }),
  )
  assert_eq(trim_id3v1(tail(10, true, true)[7:]), {
    audio_end: 3,
    tag_bytes: 355,
    enhanced: true,
  })
}
