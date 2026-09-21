// Bit order and cursor model adapted from minimp3.h bs_init/get_bits.
// Upstream: https://github.com/lieff/minimp3
// Commit: ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0).
// Unlike the C helper, failures are explicit and never advance the cursor.

///|
/// A failed read or skip. Width validation precedes available-data validation.
pub(all) enum BitstreamError {
  InvalidWidth(Int)
  NegativeSkip(Int)
  UnexpectedEnd(requested~ : Int, remaining~ : Int64)
} derive(Eq, Show)

///|
/// A bounded MSB-first reader over immutable bytes.
/// Positions count bits from the first byte. Int64 prevents overflow when a
/// large byte length is converted to a bit length.
struct BitReader {
  bytes : Bytes
  mut bit_position : Int64
  bit_limit : Int64
}

///|
/// Start at the first (most significant) bit of `bytes`.
pub fn BitReader::new(bytes : Bytes) -> BitReader {
  { bytes, bit_position: 0L, bit_limit: bytes.length().to_int64() * 8L }
}

///|
/// Number of bits consumed by successful reads and skips.
pub fn BitReader::position(self : BitReader) -> Int64 {
  self.bit_position
}

///|
/// Number of bits that can still be consumed.
pub fn BitReader::remaining(self : BitReader) -> Int64 {
  self.bit_limit - self.bit_position
}

///|
/// Read 0 through 32 bits, MSB first, into the low bits of an unsigned word.
/// Reading zero bits returns zero, including on empty input or at EOF.
/// Invalid widths and truncated input leave the position unchanged.
pub fn BitReader::read_bits(
  self : BitReader,
  count : Int,
) -> Result[UInt, BitstreamError] {
  if count < 0 || count > 32 {
    return Err(InvalidWidth(count))
  }
  if count.to_int64() > self.remaining() {
    return Err(UnexpectedEnd(requested=count, remaining=self.remaining()))
  }
  let mut cursor = self.bit_position
  let mut needed = count
  let mut value = 0U
  while needed > 0 {
    let byte_index = (cursor / 8L).to_int()
    let bit_offset = (cursor % 8L).to_int()
    let available = 8 - bit_offset
    let take = if needed < available { needed } else { available }
    let shift = available - take
    let mask = (1U << take) - 1U
    let chunk = (self.bytes[byte_index].to_uint() >> shift) & mask
    value = (value << take) | chunk
    cursor += take.to_int64()
    needed -= take
  }
  self.bit_position = cursor
  Ok(value)
}

///|
/// Skip a nonnegative number of bits. Unlike `read_bits`, this is not limited
/// to 32 bits. A zero skip succeeds at EOF; every failure preserves position.
pub fn BitReader::skip_bits(
  self : BitReader,
  count : Int,
) -> Result[Unit, BitstreamError] {
  if count < 0 {
    return Err(NegativeSkip(count))
  }
  if count.to_int64() > self.remaining() {
    return Err(UnexpectedEnd(requested=count, remaining=self.remaining()))
  }
  self.bit_position += count.to_int64()
  Ok(())
}
