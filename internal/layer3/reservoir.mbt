// Reservoir reconstruction adapted from minimp3.h L3_restore_reservoir and
// L3_save_reservoir, commit ea99364f61c14656440e8d77e9c233ccf3124633
// (CC0-1.0). Missing history and invalid bit budgets are explicit errors;
// failures leave history untouched instead of producing partial main data.

///|
pub struct Reservoir {
  mut history : Bytes
}

///|
pub fn Reservoir::new() -> Reservoir {
  { history: b"", }
}

///|
pub fn Reservoir::reset(self : Reservoir) -> Unit {
  self.history = b""
}

///|
/// Combine the requested tail of saved data with this frame's main payload.
/// Restoring does not change history; commit successful decoding with save.
pub fn Reservoir::restore(
  self : Reservoir,
  payload : Bytes,
  main_data_begin : Int,
) -> Bytes raise DecodeError {
  if main_data_begin < 0 || main_data_begin > 511 {
    raise InvalidSideInfo("main_data_begin outside MPEG-1 range")
  }
  if main_data_begin > self.history.length() {
    raise InsufficientHistory(main_data_begin, self.history.length())
  }
  let offset = self.history.length() - main_data_begin
  Bytes::makei(main_data_begin + payload.length(), fn(i) {
    if i < main_data_begin {
      self.history[offset + i]
    } else {
      payload[i - main_data_begin]
    }
  })
}

///|
/// Preserve at most the last 511 fully unconsumed bytes. A partially consumed
/// byte is discarded exactly as in the upstream ceil(bit_position / 8) rule.
pub fn Reservoir::save(
  self : Reservoir,
  main_data : Bytes,
  consumed_bits : Int,
) -> Unit raise DecodeError {
  if consumed_bits < 0 ||
    consumed_bits.to_int64() > main_data.length().to_int64() * 8L {
    raise BitBudget(0, consumed_bits, main_data.length() * 8)
  }
  let consumed_bytes = consumed_bits / 8 +
    (if consumed_bits % 8 == 0 { 0 } else { 1 })
  let unconsumed = main_data.length() - consumed_bytes
  let count = if unconsumed > 511 { 511 } else { unconsumed }
  let start = main_data.length() - count
  self.history = Bytes::makei(count, fn(i) { main_data[start + i] })
}
