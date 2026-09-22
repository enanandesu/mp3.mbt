///|
test "reservoir uses preceding tails across consecutive frames" {
  let reservoir = Reservoir::new()
  let first = reservoir.restore(b"abcdef", 0)
  assert_eq(first, b"abcdef")
  reservoir.save(first, 16)
  assert_eq(reservoir.history, b"cdef")
  let second = reservoir.restore(b"ghij", 3)
  assert_eq(second, b"defghij")
  reservoir.save(second, 17)
  assert_eq(reservoir.history, b"ghij")
  assert_eq(reservoir.restore(b"klm", 4), b"ghijklm")
  reservoir.reset()
  assert_eq(try? reservoir.restore(b"n", 1), Err(InsufficientHistory(1, 0)))
  assert_eq(reservoir.restore(b"n", 0), b"n")
}

///|
test "reservoir rounds consumed partial bytes and keeps at most 511 bytes" {
  let reservoir = Reservoir::new()
  let large = Bytes::makei(1200, fn(i) { (i % 251).to_byte() })
  for consumed in [0, 1, 7, 8, 9, 5512, 9599, 9600] {
    reservoir.save(large, consumed)
    let rounded = consumed / 8 + (if consumed % 8 == 0 { 0 } else { 1 })
    let remains = 1200 - rounded
    let count = if remains > 511 { 511 } else { remains }
    assert_eq(reservoir.history.length(), count)
    assert_eq(
      reservoir.restore(b"", count),
      Bytes::makei(count, fn(i) { large[1200 - count + i] }),
    )
  }
  reservoir.save(b"", 0)
  assert_eq(reservoir.history, b"")
}

///|
test "reservoir errors preserve history and restoring is transactional" {
  let reservoir = Reservoir::new()
  reservoir.save(b"retained", 0)
  assert_eq(try? reservoir.restore(b"new", 9), Err(InsufficientHistory(9, 8)))
  for begin in [-1, 512, 2147483647] {
    assert_eq(
      try? reservoir.restore(b"new", begin),
      Err(InvalidSideInfo("main_data_begin outside MPEG-1 range")),
    )
    assert_eq(reservoir.history, b"retained")
  }
  for consumed in [-1, 25, 2147483647] {
    assert_eq(
      try? reservoir.save(b"new", consumed),
      Err(BitBudget(0, consumed, 24)),
    )
    assert_eq(reservoir.history, b"retained")
  }
  assert_eq(reservoir.restore(b"new", 3), b"nednew")
  assert_eq(reservoir.history, b"retained")
}
