// Layer III scheduling follows minimp3.h L3_decode/mp3dec_decode_frame,
// ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0).
// Complete frames are explicit here. A malformed frame is fatal until reset;
// history insufficiency is an error, never a silent zero-sample concealment.

///|
pub struct FrameDecoder {
  reservoir : Reservoir
  overlap : Array[Array[Float]]
  qmf : Array[Float]
  mut previous : @header.Header?
  mut failed : Bool
}

///|
pub fn FrameDecoder::new() -> FrameDecoder {
  {
    reservoir: Reservoir::new(),
    overlap: [Array::make(288, 0.0), Array::make(288, 0.0)],
    qmf: Array::make(960, 0.0),
    previous: None,
    failed: false,
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
}

///|
pub fn FrameDecoder::decode_frame(
  self : FrameDecoder,
  frame : Bytes,
) -> Array[Float] raise DecodeError {
  if self.failed {
    raise InvalidFrame("decoder is failed; reset is required")
  }
  self.decode_frame_impl(frame) catch {
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
) -> Array[Float] raise DecodeError {
  let header = match @header.parse(frame) {
    Ok(header) => header
    Err(_) => raise InvalidFrame("invalid or incomplete header")
  }
  if header.version != @header.Mpeg1 {
    raise UnsupportedVersion
  }
  if header.bitrate_kbps is None {
    raise InvalidFrame("free-format requires bounded frame discovery")
  }
  if self.previous is Some(previous) && !previous.stream_compatible(header) {
    raise InvalidFrame("stream version, sample rate or channel count changed")
  }
  let side = read_side_info(frame, header)
  let offset = header.main_data_offset()
  let payload = frame[offset:].to_bytes()
  let main_data = self.reservoir.restore(payload, side.main_data_begin)
  let channels = header.channels()
  let positions : Array[Array[Int]] = [Array::make(39, 0), Array::make(39, 0)]
  let pcm : Array[Float] = []
  let mut consumed = 0
  for granule = 0; granule < 2; granule = granule + 1 {
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
      stereo(samples, positions[1], side.granules[granule * channels], header)
    }
    for channel = 0; channel < channels; channel = channel + 1 {
      hybrid(
        samples,
        channel * 576,
        self.overlap[channel],
        side.granules[granule * channels + channel],
      )
    }
    for value in synth_granule(self.qmf, samples, channels) {
      pcm.push(value)
    }
  }
  self.reservoir.save(main_data, consumed)
  self.previous = Some(header)
  pcm
}
