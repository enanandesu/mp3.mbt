///|
test "MSB first reads within and across bytes" {
  let reader = @bitstream.BitReader::new(b"\xB2\x69\xE1")
  assert_eq(reader.position(), 0L)
  assert_eq(reader.remaining(), 24L)
  assert_eq(reader.read_bits(3), Ok(5U))
  assert_eq(reader.read_bits(7), Ok(73U))
  assert_eq(reader.read_bits(6), Ok(41U))
  assert_eq(reader.read_bits(8), Ok(225U))
  assert_eq(reader.position(), 24L)
  assert_eq(reader.remaining(), 0L)
}

///|
test "zero bits is safe on empty input and at EOF" {
  let empty = @bitstream.BitReader::new(b"")
  assert_eq(empty.read_bits(0), Ok(0U))
  assert_eq(empty.skip_bits(0), Ok(()))
  assert_eq(empty.position(), 0L)
  assert_eq(
    empty.read_bits(1),
    Err(@bitstream.UnexpectedEnd(requested=1, remaining=0L)),
  )
  let reader = @bitstream.BitReader::new(b"\x80")
  assert_eq(reader.read_bits(8), Ok(128U))
  assert_eq(reader.read_bits(0), Ok(0U))
  assert_eq(reader.skip_bits(0), Ok(()))
  assert_eq(reader.position(), 8L)
}

///|
test "32 bit reads preserve unsigned high bits at all alignments" {
  let all_ones = @bitstream.BitReader::new(b"\xFF\xFF\xFF\xFF")
  assert_eq(all_ones.read_bits(32), Ok(0xFFFFFFFFU))
  let aligned = @bitstream.BitReader::new(b"\x89\xAB\xCD\xEF")
  assert_eq(aligned.read_bits(32), Ok(0x89ABCDEFU))
  let unaligned = @bitstream.BitReader::new(b"\xF1\x35\x79\xBD\xE0")
  assert_eq(unaligned.skip_bits(4), Ok(()))
  assert_eq(unaligned.read_bits(32), Ok(0x13579BDEU))
  assert_eq(unaligned.position(), 36L)
  assert_eq(unaligned.read_bits(4), Ok(0U))
}

///|
test "invalid widths and truncated reads are atomic" {
  let reader = @bitstream.BitReader::new(b"\xD6\x80")
  assert_eq(reader.read_bits(3), Ok(6U))
  for width in [-2147483648, -1, 33, 2147483647] {
    assert_eq(reader.read_bits(width), Err(@bitstream.InvalidWidth(width)))
    assert_eq(reader.position(), 3L)
    assert_eq(reader.remaining(), 13L)
  }
  assert_eq(
    reader.read_bits(14),
    Err(@bitstream.UnexpectedEnd(requested=14, remaining=13L)),
  )
  assert_eq(reader.position(), 3L)
  assert_eq(reader.read_bits(5), Ok(22U))
  assert_eq(reader.read_bits(8), Ok(128U))
  assert_eq(
    reader.read_bits(1),
    Err(@bitstream.UnexpectedEnd(requested=1, remaining=0L)),
  )
  assert_eq(reader.position(), 16L)
}

///|
test "skip permits more than 32 bits and rejects invalid or truncated input" {
  let reader = @bitstream.BitReader::new(b"\x00\x11\x22\x33\x44\xA5")
  assert_eq(reader.skip_bits(40), Ok(()))
  assert_eq(reader.position(), 40L)
  assert_eq(reader.remaining(), 8L)
  for count in [-2147483648, -1] {
    assert_eq(reader.skip_bits(count), Err(@bitstream.NegativeSkip(count)))
    assert_eq(reader.position(), 40L)
  }
  for count in [9, 2147483647] {
    assert_eq(
      reader.skip_bits(count),
      Err(@bitstream.UnexpectedEnd(requested=count, remaining=8L)),
    )
    assert_eq(reader.position(), 40L)
  }
  assert_eq(reader.read_bits(4), Ok(10U))
  assert_eq(reader.skip_bits(4), Ok(()))
  assert_eq(reader.position(), 48L)
  assert_eq(reader.remaining(), 0L)
  assert_eq(
    reader.skip_bits(1),
    Err(@bitstream.UnexpectedEnd(requested=1, remaining=0L)),
  )
}

///|
/// Independent bit-at-a-time oracle; production reads chunks of up to one byte.
fn reference_bits(bytes : Bytes, start : Int, count : Int) -> UInt {
  let mut value = 0U
  for bit in start..<(start + count) {
    let digit = (bytes[bit / 8].to_uint() >> (7 - bit % 8)) & 1U
    value = value * 2U + digit
  }
  value
}

///|
test "all widths and alignments match bit oracle on varied data" {
  for seed in 0..<32 {
    let bytes = Bytes::makei(9, i => (seed * 83 + i * 61).to_byte())
    for start in 0..<40 {
      for count in 0..<=32 {
        let reader = @bitstream.BitReader::new(bytes)
        assert_eq(reader.skip_bits(start), Ok(()))
        assert_eq(
          reader.read_bits(count),
          Ok(reference_bits(bytes, start, count)),
        )
        assert_eq(reader.position(), (start + count).to_int64())
        assert_eq(reader.remaining(), (72 - start - count).to_int64())
      }
    }
  }
}

///|
test "short inputs reject every overrun without losing unread bits" {
  for length in 0..<=4 {
    let bytes = Bytes::makei(length, i => (0xA7 + 37 * i).to_byte())
    for start in 0..<=(length * 8) {
      let remaining = length * 8 - start
      for count in 0..<=32 {
        let probe = @bitstream.BitReader::new(bytes)
        assert_eq(probe.skip_bits(start), Ok(()))
        if count > remaining {
          assert_eq(
            probe.read_bits(count),
            Err(
              @bitstream.UnexpectedEnd(
                requested=count,
                remaining=remaining.to_int64(),
              ),
            ),
          )
          assert_eq(probe.position(), start.to_int64())
          assert_eq(
            probe.read_bits(remaining),
            Ok(reference_bits(bytes, start, remaining)),
          )
        } else {
          assert_eq(
            probe.read_bits(count),
            Ok(reference_bits(bytes, start, count)),
          )
        }
      }
    }
  }
}
