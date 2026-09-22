///|
/// Complete interleaved f32 audio at the original sample rate and channel count.
/// Encoder delay, padding and the Xing frame are retained; no gapless trimming.
pub struct Audio {
  sample_rate : Int
  channels : Int
  samples : Array[Float]
}

///|
pub(all) suberror Mp3Error {
  InvalidHeader(Int)
  InvalidTag
  TruncatedFrame(Int, Int)
  UnsupportedVersion
  UnsupportedFreeFormat
  OutputLimit
  NoAudio
  DecodeFailure(Int, @layer3.DecodeError)
} derive(Eq, Show)

///|
/// Decode complete MPEG-1 Layer III audio. This initial whole-buffer interface
/// does not yet provide incremental input or MPEG-2/2.5/free-format support.
/// Leading scan and output allocations have explicit limits. Corruption after
/// the first accepted frame is fatal, including missing reservoir history.
pub fn decode_mpeg1(
  data : Bytes,
  max_output_samples? : Int = 64 * 1024 * 1024,
  max_initial_scan? : Int = 65536,
) -> Audio raise Mp3Error {
  if max_output_samples < 0 || max_initial_scan < 0 {
    raise OutputLimit
  }
  let mut offset = 0
  while true {
    match @tags.inspect_id3v2(data[offset:], true, 16 * 1024 * 1024) {
      NotATag => break
      Tag(tag) => offset += tag.total_bytes
      _ => raise InvalidTag
    }
  }
  let end = @tags.trim_id3v1(data[:]).audio_end
  let scan_start = offset
  let decoder = @layer3.FrameDecoder::new()
  let output : Array[Float] = []
  let mut format : @header.Header? = None
  while offset < end {
    let header = match @header.parse(data, offset~) {
      Ok(header) => header
      Err(_) => {
        if format is None && offset - scan_start < max_initial_scan {
          offset += 1
          continue
        }
        raise InvalidHeader(offset)
      }
    }
    if header.version != @header.Mpeg1 {
      raise UnsupportedVersion
    }
    let length = match header.frame_bytes() {
      Ok(Some(length)) => length
      Ok(None) => raise UnsupportedFreeFormat
      Err(_) => raise InvalidHeader(offset)
    }
    if length > end - offset {
      raise TruncatedFrame(offset, length)
    }
    if header.samples_per_frame() * header.channels() >
      max_output_samples - output.length() {
      raise OutputLimit
    }
    let frame = data[offset:offset + length].to_bytes()
    let samples = decoder.decode_frame(frame) catch {
      error => raise DecodeFailure(offset, error)
    }
    for sample in samples {
      output.push(sample)
    }
    format = Some(header)
    offset += length
  }
  match format {
    Some(header) =>
      {
        sample_rate: header.sample_rate_hz,
        channels: header.channels(),
        samples: output,
      }
    None => raise NoAudio
  }
}
