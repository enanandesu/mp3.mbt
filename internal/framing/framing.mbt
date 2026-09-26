// Bounded free-format frame discovery derived from mp3d_find_frame and
// mp3d_match_frame in minimp3.h, commit
// ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0).
// Only the already-selected candidate at offset zero is examined. The caller
// owns initial synchronization, stream-format enforcement, tags and buffering.
// Unlike C, incomplete input and limits are explicit; an isolated free frame
// at EOF never supplies its own guessed length. Two complete equal-base free
// frames at EOF are sufficient, whereas the ordinary path needs three headers.

///|
pub(all) enum FrameError {
  InvalidLimit(Int)
  InvalidHeader
  HeaderMismatch
  Truncated(Int, Int)
  InvalidFreeFormatSize(Int)
  FreeFormatUnconfirmed
  FreeFormatSearchLimit(Int)
  AmbiguousFreeFormat
} derive(Eq, Show, Debug)

///|
pub(all) enum Probe {
  NeedMoreInput(Int)
  Frame(Int, Int?)
  Invalid(FrameError)
} derive(Eq, Show, Debug)

///|
fn padding(header : @header.Header) -> Int {
  if header.padding {
    1
  } else {
    0
  }
}

///|
fn finish(data : Bytes, size : Int, free_size : Int?, eof : Bool) -> Probe {
  if data.length() >= size {
    Frame(size, free_size)
  } else if eof {
    Invalid(Truncated(size, data.length()))
  } else {
    NeedMoreInput(size)
  }
}

///|
/// Probe an offset-zero candidate. NeedMoreInput counts total buffered bytes,
/// not additional bytes. Frame counts its four-byte header and optional padding;
/// its second field is the unpadded free-format size, or None for coded bitrate.
/// A known frame size needs no following header; the caller enforces subsequent
/// boundaries when it consumes the next frame. Unknown free discovery requires
/// no more than 2 * (max_free_size + 1) + 4 buffered bytes (4614 by default).
pub fn probe(
  data : Bytes,
  header : @header.Header,
  eof : Bool,
  known_free_size : Int?,
  max_free_size? : Int = 2304,
  compatible? : Bool = false,
) -> Probe {
  // The upper bound ensures every lookahead/minimum-input count fits Int.
  if max_free_size < 4 || max_free_size > 1073741820 {
    return Invalid(InvalidLimit(max_free_size))
  }
  if data.length() < 4 {
    return if eof {
      Invalid(Truncated(4, data.length()))
    } else {
      NeedMoreInput(4)
    }
  }
  match @header.parse(data, allow_reserved_emphasis=compatible) {
    Ok(actual) => if actual != header { return Invalid(HeaderMismatch) }
    Err(_) => return Invalid(InvalidHeader)
  }
  if header.bitrate_kbps is Some(_) {
    return match header.frame_bytes() {
      Ok(Some(size)) => finish(data, size, None, eof)
      _ => Invalid(InvalidHeader)
    }
  }
  let pad = padding(header)
  match known_free_size {
    Some(base) => {
      if base > max_free_size || base < header.main_data_offset() - pad {
        return Invalid(InvalidFreeFormatSize(base))
      }
      return finish(data, base + pad, Some(base), eof)
    }
    None => ()
  }
  let minimum = header.main_data_offset()
  let maximum = max_free_size + pad
  if minimum > maximum {
    return Invalid(InvalidFreeFormatSize(max_free_size))
  }
  let search_end = if data.length() - 4 < maximum {
    data.length() - 4
  } else {
    maximum
  }
  let mut pending = 0
  let mut eof_candidate : Int? = None
  for distance = minimum; distance <= search_end; distance = distance + 1 {
    let second = match
      @header.parse(data, offset=distance, allow_reserved_emphasis=compatible) {
      Ok(second) if header.stream_compatible(second) ||
        (compatible && header.sync_compatible(second)) => second
      _ => continue
    }
    let base = distance - pad
    let second_size = base + padding(second)
    if second_size < second.main_data_offset() {
      continue
    }
    let third_offset = distance + second_size
    if third_offset + 4 <= data.length() {
      match
        @header.parse(
          data,
          offset=third_offset,
          allow_reserved_emphasis=compatible,
        ) {
        Ok(third) if header.stream_compatible(third) ||
          (compatible && header.sync_compatible(third)) =>
          if base + padding(third) >= third.main_data_offset() {
            // Earliest confirmed three-header spacing follows upstream. A
            // multiple of a valid spacing is not a second stream hypothesis.
            return Frame(distance, Some(base))
          }
        _ => ()
      }
    } else if eof {
      if third_offset == data.length() {
        match eof_candidate {
          Some(previous) if previous != base =>
            return Invalid(AmbiguousFreeFormat)
          _ => eof_candidate = Some(base)
        }
      }
    } else if pending == 0 || third_offset + 4 < pending {
      pending = third_offset + 4
    }
  }
  if eof {
    return match eof_candidate {
      Some(base) => Frame(base + pad, Some(base))
      None =>
        if data.length() >= maximum + 4 && pending == 0 {
          Invalid(FreeFormatSearchLimit(max_free_size))
        } else {
          Invalid(FreeFormatUnconfirmed)
        }
    }
  }
  if search_end < maximum {
    // More bytes could finish a previously unseen candidate header. Asking
    // for one additional byte never overlooks an earlier valid frame length.
    return NeedMoreInput(data.length() + 1)
  }
  if pending != 0 {
    NeedMoreInput(pending)
  } else {
    Invalid(FreeFormatSearchLimit(max_free_size))
  }
}
