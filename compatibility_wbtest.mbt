///|
test "compatible tail recovery waits for EOF and rejects unrelated corruption" {
  let frame = entry_frame(1)
  for remaining in [1, 2, 3, 4, 20, 416] {
    let events : Array[Recovery] = []
    let decoder = Decoder::new(mode=Compatible, on_recovery=event => {
      events.push(event)
    })
    let data = entry_join(frame, frame[:remaining].to_bytes())
    let _ = decoder.push(data)
    assert_true(decoder.next_frame() is Frame(_))
    assert_true(decoder.next_frame() is NeedMoreInput)
    assert_eq(events.length(), 0)
    decoder.finish_input()
    assert_true(decoder.next_frame() is EndOfInput)
    assert_eq(events, [TruncatedTail(offset=417L, discarded_bytes=remaining)])
    assert_true(decoder.next_frame() is EndOfInput)
    assert_eq(events.length(), 1)
    decoder.reset()
    let _ = decoder.push(frame)
    decoder.finish_input()
    assert_true(decoder.next_frame() is Frame(_))
    assert_true(decoder.next_frame() is EndOfInput)
    assert_eq(events.length(), 1)
    assert_true((try? decode_all(data)) is Err(_))
  }
  for tail in [b"garbage", b"\xff\xe0", b"\xff\xfb\xfc"] {
    let decoder = Decoder::new(mode=Compatible)
    let _ = decoder.push(entry_join(frame, tail))
    decoder.finish_input()
    assert_true(decoder.next_frame() is Frame(_))
    assert_eq(stream_next_error(decoder), Some(InvalidHeader(417L)))
    assert_eq(stream_next_error(decoder), Some(FailedDecoder))
  }
}

///|
test "compatible frames preserve mixed channels and enforce total sample limit" {
  let data = entry_join(
    entry_frame(1),
    entry_join(entry_frame(2), entry_frame(1)),
  )
  let result = decode_frames(data, mode=Compatible)
  assert_eq(result.frames.map(frame => frame.channels), [1, 2, 1])
  assert_eq(result.frames.map(frame => frame.samples.length()), [
    1152, 2304, 1152,
  ])
  assert_eq(result.recoveries, [
    ChannelChange(offset=417L, previous=1, current=2),
    ChannelChange(offset=834L, previous=2, current=1),
  ])
  assert_true((try? decode_frames(data)) is Err(FormatChange(417L)))
  assert_true((try? decode_all(data)) is Err(FormatChange(417L)))
  let limits = { ..Limits::default(), max_output_samples: 4607, }
  assert_true(
    (try? decode_frames(data, mode=Compatible, limits~)) is Err(OutputLimit),
  )
  for other in [entry_frame(1, rate=2), stream_free(0, 417, [0, 0, 0])] {
    assert_true(
      (try? decode_frames(entry_join(entry_frame(1), other), mode=Compatible))
      is Err(FormatChange(417L)),
    )
  }
}

///|
test "compatible initial history accumulates but a later history gap stays fatal" {
  let missing = entry_frame(1, history=511)
  let data = entry_join(missing, entry_join(missing, missing))
  let result = decode_frames(data, mode=Compatible)
  assert_eq(result.frames.length(), 1)
  assert_eq(result.frames[0].source_offset, 834L)
  assert_eq(result.recoveries, [
    MissingHistory(offset=0L, frame_bytes=417, required=511, available=0),
    MissingHistory(offset=417L, frame_bytes=417, required=511, available=396),
  ])
  assert_true((try? decode_frames(missing, mode=Compatible)) is Err(NoAudio))
  let decoder = Decoder::new(mode=Compatible)
  let _ = decoder.push(entry_join(entry_frame(1), missing))
  decoder.finish_input()
  assert_true(decoder.next_frame() is Frame(_))
  assert_eq(
    stream_next_error(decoder),
    Some(DecodeFailure(417L, @layer3.InsufficientHistory(511, 396))),
  )
  assert_eq(stream_next_error(decoder), Some(FailedDecoder))
  decoder.reset()
  let _ = decoder.push(data)
  decoder.finish_input()
  assert_true(decoder.next_frame() is Frame(_))
  assert_true(decoder.next_frame() is EndOfInput)
}

///|
test "reserved emphasis recovery retains other header and payload validation" {
  let original = entry_frame(1)
  let reserved = Bytes::makei(original.length(), i => {
    if i == 3 {
      194
    } else {
      original[i]
    }
  })
  let stream = decode_frames(entry_join(original, reserved), mode=Compatible)
  assert_eq(stream.frames.length(), 2)
  assert_eq(stream.recoveries, [ReservedEmphasis(offset=417L, value=2)])
  assert_true(
    (try? decode_all(entry_join(original, reserved)))
    is Err(InvalidHeader(417L)),
  )
  let bad = Bytes::makei(reserved.length(), i => {
    if i == 2 {
      252
    } else {
      reserved[i]
    }
  })
  assert_true(
    (try? decode_frames(entry_join(original, bad), mode=Compatible))
    is Err(InvalidHeader(417L)),
  )
  let free = stream_free(0, 417, [0, 1, 0])
  let changed = Bytes::makei(free.length(), i => {
    if i == 3 || i == 420 || i == 838 {
      (free[i].to_int() | 2).to_byte()
    } else {
      free[i]
    }
  })
  let result = decode_frames(changed, mode=Compatible)
  assert_eq(result.frames.length(), 3)
  assert_eq(result.recoveries.length(), 3)
}

///|
test "recovery callback reset cannot corrupt committed transport" {
  // Reentry is outside the callback contract, but it must not make buffered
  // input negative or prevent the caller from reusing the reset decoder.
  let original = entry_frame(1)
  let reserved = Bytes::makei(original.length(), i => {
    if i == 3 {
      (original[i].to_int() | 2).to_byte()
    } else {
      original[i]
    }
  })
  let holder : Array[Decoder] = []
  let decoder = Decoder::new(mode=Compatible, on_recovery=_ => holder[0].reset())
  holder.push(decoder)
  let _ = decoder.push(reserved)
  decoder.finish_input()
  match decoder.next_frame() {
    Frame(frame) => {
      assert_eq(frame.source_offset, 0L)
      assert_eq(frame.samples.length(), 1152)
    }
    _ => fail("the committed frame must survive callback reset")
  }
  assert_eq(decoder.buffered_bytes(), 0)
  assert_true(decoder.next_frame() is NeedMoreInput)
  let _ = decoder.push(original)
  decoder.finish_input()
  assert_true(decoder.next_frame() is Frame(_))
  assert_true(decoder.next_frame() is EndOfInput)
}
