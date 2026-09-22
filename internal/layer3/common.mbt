// Bounded Layer III cursor, following minimp3 bs_t/get_bits, CC0-1.0.
// Source commit: ea99364f61c14656440e8d77e9c233ccf3124633.
// Unlike C, lookahead is explicitly zero-padded and actual reads never cross
// the caller's bit budget. No read relies on allocation padding.

///|
pub(all) suberror DecodeError {
  InvalidSideInfo(String)
  BitBudget(Int, Int, Int)
  InsufficientHistory(Int, Int)
  UnsupportedVersion
  InvalidFrame(String)
} derive(Eq, Show)

///|
priv struct BitCursor {
  bytes : Bytes
  mut pos : Int
  limit : Int
}

///|
fn BitCursor::new(bytes : Bytes, limit? : Int) -> BitCursor {
  { bytes, pos: 0, limit: limit.unwrap_or(bytes.length() * 8) }
}

///|
fn BitCursor::peek_padded(self : BitCursor, count : Int) -> Int {
  let mut value = 0
  for i = 0; i < count; i = i + 1 {
    let bit = self.pos + i
    value = value << 1
    if bit < self.limit && bit / 8 < self.bytes.length() {
      value = value | ((self.bytes[bit / 8].to_int() >> (7 - bit % 8)) & 1)
    }
  }
  value
}

///|
fn BitCursor::read(self : BitCursor, count : Int) -> Int raise DecodeError {
  if count < 0 ||
    count > 24 ||
    count > self.limit - self.pos ||
    self.pos + count > self.bytes.length() * 8 {
    raise BitBudget(self.pos, count, self.limit)
  }
  let value = self.peek_padded(count)
  self.pos += count
  value
}

///|
fn BitCursor::skip(self : BitCursor, count : Int) -> Unit raise DecodeError {
  if count < 0 ||
    count > self.limit - self.pos ||
    self.pos + count > self.bytes.length() * 8 {
    raise BitBudget(self.pos, count, self.limit)
  }
  self.pos += count
}
