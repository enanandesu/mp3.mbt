// Layer III scheduling follows minimp3.h L3_decode/mp3dec_decode_frame,
// ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0).
// Complete frames are explicit here. A malformed frame is fatal until reset;
// strict history insufficiency is fatal. Explicit compatibility warmup retains
// reservoir data without PCM, and reports the skipped initial frame.

///|
pub struct FrameDecoder {
  reservoir : Reservoir
  overlap : Array[Array[Float]]
  qmf : Array[Float]
  mut previous : @header.Header?
  mut failed : Bool
  mut has_output : Bool
}

///|
pub fn FrameDecoder::new() -> FrameDecoder {
  {
    reservoir: Reservoir::new(),
    overlap: [Array::make(288, 0.0), Array::make(288, 0.0)],
    qmf: Array::make(960, 0.0),
    previous: None,
    failed: false,
    has_output: false,
  }
}

///|
pub fn FrameDecoder::reset(self : FrameDecoder) -> Unit {
  self.reservoir.reset()
  for channel in self.overlap {
    for i = 0; i < channel.length(); i = i + 1 {
      channel[i] = 0.0
    }
  }
  for i = 0; i < self.qmf.length(); i = i + 1 {
    self.qmf[i] = 0.0
  }
  self.previous = None
  self.failed = false
  self.has_output = false
}

///|
pub fn FrameDecoder::decode_frame(
  self : FrameDecoder,
  frame : Bytes,
  free_format_size? : Int,
  compatible? : Bool = false,
  on_history_gap? : (Int, Int) -> Unit = (_, _) => (),
) -> Array[Float] raise DecodeError {
  if self.failed {
    raise InvalidFrame("decoder is failed; reset is required")
  }
  self.decode_frame_impl(frame, free_format_size?, compatible~, on_history_gap~) catch {
    error => {
      self.failed = true
      raise error
    }
  }
}

///|
fn FrameDecoder::decode_frame_impl(
  self : FrameDecoder,
  frame : Bytes,
  free_format_size? : Int,
  compatible~ : Bool,
  on_history_gap~ : (Int, Int) -> Unit,
) -> Array[Float] raise DecodeError {
  let header = match @header.parse(frame, allow_reserved_emphasis=compatible) {
    Ok(header) => header
    Err(_) => raise InvalidFrame("invalid or incomplete header")
  }
  if header.bitrate_kbps is None {
    match free_format_size {
      None => raise InvalidFrame("free-format requires bounded frame discovery")
      Some(size) =>
        if size <
          header.main_data_offset() - (if header.padding { 1 } else { 0 }) ||
          size > 2304 {
          raise InvalidFrame("invalid bounded free-format frame size")
        }
    }
  }
  if self.previous is Some(previous) &&
    !(previous.stream_compatible(header) ||
    (compatible && previous.sync_compatible(header))) {
    raise InvalidFrame("stream version, sample rate or channel count changed")
  }
  let side = read_side_info(frame, header, free_format_size?)
  let offset = header.main_data_offset()
  let payload = frame[offset:].to_bytes()
  let main_data = self.reservoir.restore(payload, side.main_data_begin) catch {
    InsufficientHistory(required, available) if compatible && !self.has_output => {
      // Match L3_restore_reservoir followed by L3_save_reservoir with bs.pos=0:
      // preserve available history and this payload even though no PCM exists.
      let partial = self.reservoir.restore(payload, available)
      self.reservoir.save(partial, 0)
      self.previous = Some(header)
      on_history_gap(required, available)
      return []
    }
    error => raise error
  }
  let channels = header.channels()
  let positions : Array[Array[Int]] = [Array::make(39, 0), Array::make(39, 0)]
  let pcm : Array[Float] = []
  let mut consumed = 0
  let granule_count = if header.version == @header.Mpeg1 { 2 } else { 1 }
  for granule = 0; granule < granule_count; granule = granule + 1 {
    let samples : Array[Float] = Array::make(1152, 0.0)
    for channel = 0; channel < channels; channel = channel + 1 {
      let gr = side.granules[granule * channels + channel]
      let end = consumed + gr.part_23_length
      let cursor = BitCursor::new(main_data, limit=end)
      cursor.pos = consumed
      let scf = decode_scalefactors(
        header,
        positions[channel],
        cursor,
        gr,
        channel,
      )
      let spectrum : Array[Float] = Array::make(576, 0.0)
      huffman(spectrum, cursor, gr, scf, end)
      for i = 0; i < 576; i = i + 1 {
        samples[channel * 576 + i] = spectrum[i]
      }
      consumed = end
    }
    if channels == 2 {
      stereo(
        samples,
        positions[1],
        side.granules[granule * channels],
        header,
        right_compress=side.granules[granule * channels + 1].scalefac_compress,
      )
    }
    for channel = 0; channel < channels; channel = channel + 1 {
      hybrid(
        samples,
        channel * 576,
        self.overlap[channel],
        side.granules[granule * channels + channel],
        sample_rate_hz=header.sample_rate_hz,
      )
    }
    for value in synth_granule(self.qmf, samples, channels) {
      pcm.push(value)
    }
  }
  self.reservoir.save(main_data, consumed)
  self.previous = Some(header)
  self.has_output = true
  pcm
}
