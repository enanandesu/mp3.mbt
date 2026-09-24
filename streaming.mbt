// Incremental transport around mp3dec_decode_frame, L3_restore_reservoir and
// L3_save_reservoir, minimp3 ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0).
// Corruption after a valid header is fatal. Ring, staged tags and EOF policy
// replace the upstream pointer-based input handling and resynchronization.

///|
/// Byte limits include headers; free-format base excludes padding. The output
/// limit applies to decode_all only, never to incremental lifetime output.
pub(all) struct Limits {
  max_buffer_bytes : Int
  max_tag_bytes : Int
  max_initial_scan : Int
  max_free_format_bytes : Int
  max_output_samples : Int
} derive(Eq, Show, Debug)

///|
pub fn Limits::default() -> Limits {
  {
    max_buffer_bytes: 8192,
    max_tag_bytes: 16 * 1024 * 1024,
    max_initial_scan: 65536,
    max_free_format_bytes: 2304,
    max_output_samples: 64 * 1024 * 1024,
  }
}

///|
/// Caller-owned samples remain valid after subsequent calls and reset.
pub struct PcmFrame {
  sample_rate : Int
  channels : Int
  source_offset : Int64
  samples : Array[Float]
} derive(Show, Debug)

///|
pub(all) enum DecodeResult {
  Frame(PcmFrame)
  NeedMoreInput
  EndOfInput
} derive(Show, Debug)

///|
struct Decoder {
  limits : Limits
  ring : FixedArray[Byte]
  core : @layer3.FrameDecoder
  mut head : Int
  mut count : Int
  mut source_offset : Int64
  mut scanned : Int
  mut prefix : Bool
  mut tag_remaining : Int
  mut tag_footer : Bytes?
  mut format : @header.Header?
  mut free_size : Int?
  mut eof : Bool
  mut failed : Bool
  mut mpeg1_only : Bool
}

///|
/// Capacity is 2885..1048576 and must hold free-format lookahead:
/// 2 * (max_free_format_bytes + 1) + 4 + 355, including a possible ID3v1/TAG+
/// trailer after two free-format frames. Free-format base is limited to 2304.
pub fn Decoder::new(
  limits? : Limits = Limits::default(),
) -> Decoder raise Mp3Error {
  if limits.max_free_format_bytes < 4 ||
    limits.max_free_format_bytes > 2304 ||
    limits.max_buffer_bytes < 2885 ||
    limits.max_buffer_bytes > 1024 * 1024 ||
    limits.max_buffer_bytes < 2 * (limits.max_free_format_bytes + 1) + 4 + 355 ||
    limits.max_tag_bytes < 0 ||
    limits.max_initial_scan < 0 ||
    limits.max_output_samples < 0 {
    raise InvalidLimits
  }
  {
    limits,
    ring: FixedArray::make(limits.max_buffer_bytes, 0),
    core: @layer3.FrameDecoder::new(),
    head: 0,
    count: 0,
    source_offset: 0L,
    scanned: 0,
    prefix: true,
    tag_remaining: 0,
    tag_footer: None,
    format: None,
    free_size: None,
    eof: false,
    failed: false,
    mpeg1_only: false,
  }
}

///|
/// Copy input[offset:] into available capacity and return accepted byte count.
/// Zero is backpressure: drain next_frame, then retry. Input is not retained.
/// Argument misuse does not poison an otherwise valid stream.
pub fn Decoder::push(
  self : Decoder,
  input : Bytes,
  offset? : Int = 0,
) -> Int raise Mp3Error {
  if self.failed {
    raise FailedDecoder
  }
  if self.eof {
    raise InputFinished
  }
  if offset < 0 || offset > input.length() {
    raise InvalidInputOffset(offset)
  }
  let accepted = Int::min(
    input.length() - offset,
    self.ring.length() - self.count,
  )
  for i = 0; i < accepted; i = i + 1 {
    self.ring[(self.head + self.count + i) % self.ring.length()] = input[offset +
      i]
  }
  self.count += accepted
  accepted
}

///|
/// Confirm EOF after all input is accepted, then drain next_frame. Idempotent.
pub fn Decoder::finish_input(self : Decoder) -> Unit raise Mp3Error {
  if self.failed {
    raise FailedDecoder
  }
  self.eof = true
}

///|
pub fn Decoder::buffered_bytes(self : Decoder) -> Int {
  self.count
}

///|
/// Reset transport, failure/EOF, reservoir, overlap and synthesis. Limits stay.
pub fn Decoder::reset(self : Decoder) -> Unit {
  self.core.reset()
  self.head = 0
  self.count = 0
  self.source_offset = 0L
  self.scanned = 0
  self.prefix = true
  self.tag_remaining = 0
  self.tag_footer = None
  self.format = None
  self.free_size = None
  self.eof = false
  self.failed = false
}

///|
fn Decoder::snapshot(self : Decoder, length : Int) -> Bytes {
  Bytes::makei(length, fn(i) { self.ring[(self.head + i) % self.ring.length()] })
}

///|
fn Decoder::consume(self : Decoder, length : Int) -> Unit {
  self.head = (self.head + length) % self.ring.length()
  self.count -= length
  self.source_offset += length.to_int64()
}

///|
/// Partial input never mutates DSP state. Fatal errors lock input and decoding
/// until reset. A fresh caller-owned PCM array is returned for every frame.
pub fn Decoder::next_frame(self : Decoder) -> DecodeResult raise Mp3Error {
  if self.failed {
    raise FailedDecoder
  }
  self.next_frame_impl() catch {
    error => {
      self.failed = true
      raise error
    }
  }
}

///|
fn Decoder::next_frame_impl(self : Decoder) -> DecodeResult raise Mp3Error {
  while true {
    if self.tag_remaining > 0 {
      let count = Int::min(self.count, self.tag_remaining)
      self.consume(count)
      self.tag_remaining -= count
      if self.tag_remaining > 0 {
        if self.eof {
          raise InvalidTag
        }
        return NeedMoreInput
      }
    }
    if self.tag_footer is Some(expected) {
      if self.count < 10 {
        if self.eof {
          raise InvalidTag
        }
        return NeedMoreInput
      }
      let footer = self.snapshot(10)
      if footer[0] != b'3' || footer[1] != b'D' || footer[2] != b'I' {
        raise InvalidTag
      }
      for i = 3; i < 10; i = i + 1 {
        if footer[i] != expected[i] {
          raise InvalidTag
        }
      }
      self.consume(10)
      self.tag_footer = None
    }
    if self.prefix {
      let bytes = self.snapshot(Int::min(10, self.count))
      match
        @tags.inspect_id3v2(
          bytes[:],
          self.eof && self.count < 10,
          self.limits.max_tag_bytes,
        ) {
        NotATag => self.prefix = false
        Invalid(_) => raise InvalidTag
        NeedMoreInput(_) | Tag(_) => {
          if self.count < 10 {
            return NeedMoreInput
          }
          // These ten bytes have validated flags, synchsafe size and tag limit.
          let mut size = 0
          for i = 6; i < 10; i = i + 1 {
            size = (size << 7) | bytes[i].to_int()
          }
          self.tag_remaining = size
          if bytes[3] == 4 && (bytes[5].to_int() & 16) != 0 {
            self.tag_footer = Some(bytes)
          }
          self.consume(10)
          continue
        }
      }
    }
    if self.count == 0 {
      return if self.eof { EndOfInput } else { NeedMoreInput }
    }
    // Hold a possible ID3v1/TAG+ tail until EOF, but only at frame boundaries.
    // Never trim a TAG byte string embedded in a normally sized frame.
    let first = self.snapshot(Int::min(4, self.count))
    let tag_prefix = first[0] == b'T' &&
      (self.count < 2 || first[1] == b'A') &&
      (self.count < 3 || first[2] == b'G')
    if tag_prefix && self.count <= 355 {
      if !self.eof {
        return NeedMoreInput
      }
      let bytes = self.snapshot(self.count)
      if @tags.trim_id3v1(bytes[:]).audio_end == 0 {
        self.consume(self.count)
        return EndOfInput
      }
    }
    if self.count < 4 && !self.eof {
      return NeedMoreInput
    }
    let header = match @header.parse(first) {
      Ok(header) => header
      Err(_) => {
        if self.format is None && self.scanned < self.limits.max_initial_scan {
          self.consume(1)
          self.scanned += 1
          continue
        }
        raise InvalidHeader(self.source_offset)
      }
    }
    if self.mpeg1_only {
      if header.version != @header.Mpeg1 {
        raise UnsupportedVersion
      }
      if header.bitrate_kbps is None {
        raise UnsupportedFreeFormat
      }
    }
    if self.format is Some(previous) && !previous.stream_compatible(header) {
      raise FormatChange(self.source_offset)
    }
    let bytes = self.snapshot(self.count)
    let mut probed = @framing.probe(
      bytes,
      header,
      self.eof,
      self.free_size,
      max_free_size=self.limits.max_free_format_bytes,
    )
    // Prefer confirmed frame boundaries over a TAG string in main data. Retry
    // EOF tag removal only if the complete view cannot establish free spacing.
    if self.eof &&
      header.bitrate_kbps is None &&
      self.free_size is None &&
      probed is @framing.Invalid(_) {
      let end = @tags.trim_id3v1(bytes[:]).audio_end
      if end < bytes.length() {
        let without_tail = @framing.probe(
          bytes[:end].to_bytes(),
          header,
          true,
          None,
          max_free_size=self.limits.max_free_format_bytes,
        )
        if without_tail is @framing.Frame(_, _) {
          probed = without_tail
        }
      }
    }
    let (length, free_size) = match probed {
      NeedMoreInput(_) => return NeedMoreInput
      Invalid(@framing.Truncated(length, _)) =>
        raise TruncatedFrame(self.source_offset, length)
      Invalid(error) => {
        // Two free frames plus a trailer have no third header. Reserve bounded
        // tail space and wait for EOF instead of rejecting a valid split input.
        if !self.eof &&
          self.free_size is None &&
          header.bitrate_kbps is None &&
          pending_free_tail(bytes, header, self.limits.max_free_format_bytes) {
          return NeedMoreInput
        }
        raise FramingFailure(self.source_offset, error)
      }
      Frame(length, free_size) => (length, free_size)
    }
    let frame = bytes[:length].to_bytes()
    let samples = self.core.decode_frame(frame, free_format_size?=free_size) catch {
      error => raise DecodeFailure(self.source_offset, error)
    }
    let result = {
      sample_rate: header.sample_rate_hz,
      channels: header.channels(),
      source_offset: self.source_offset,
      samples,
    }
    self.format = Some(header)
    self.free_size = free_size
    self.consume(length)
    return Frame(result)
  } nobreak {
    NeedMoreInput
  }
}

///|
fn pending_free_tail(
  data : Bytes,
  header : @header.Header,
  maximum : Int,
) -> Bool {
  let pad = if header.padding { 1 } else { 0 }
  let end = Int::min(maximum + pad, data.length() - 4)
  for distance = header.main_data_offset()
      distance <= end
      distance = distance + 1 {
    let second = match @header.parse(data, offset=distance) {
      Ok(second) if header.stream_compatible(second) => second
      _ => continue
    }
    let size = distance - pad + (if second.padding { 1 } else { 0 })
    if size < second.main_data_offset() {
      continue
    }
    let tail = distance + size
    let remaining = data.length() - tail
    if remaining > 0 &&
      remaining <= 355 &&
      data[tail] == b'T' &&
      (remaining < 2 || data[tail + 1] == b'A') &&
      (remaining < 3 || data[tail + 2] == b'G') {
      return true
    }
  }
  false
}
