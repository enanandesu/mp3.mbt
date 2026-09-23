///|
/// Complete interleaved f32 audio. Encoder delay, padding and Xing frames remain.
pub struct Audio {
  sample_rate : Int
  channels : Int
  samples : Array[Float]
}

///|
pub(all) suberror Mp3Error {
  InvalidHeader(Int64)
  InvalidTag
  TruncatedFrame(Int64, Int)
  UnsupportedVersion
  UnsupportedFreeFormat
  OutputLimit
  NoAudio
  DecodeFailure(Int64, @layer3.DecodeError)
  FramingFailure(Int64, @framing.FrameError)
  FormatChange(Int64)
  InvalidLimits
  InvalidInputOffset(Int)
  InputFinished
  FailedDecoder
} derive(Eq, Show)

///|
/// Decode all supported Layer III versions using the incremental state machine.
/// max_output_samples counts interleaved samples and applies only to this helper.
pub fn decode_all(
  data : Bytes,
  limits? : Limits = Limits::default(),
) -> Audio raise Mp3Error {
  collect_audio(Decoder::new(limits~), data)
}

///|
/// Compatibility entry point restricted to MPEG-1 with coded bitrate.
pub fn decode_mpeg1(
  data : Bytes,
  max_output_samples? : Int = 64 * 1024 * 1024,
  max_initial_scan? : Int = 65536,
) -> Audio raise Mp3Error {
  if max_output_samples < 0 || max_initial_scan < 0 {
    raise OutputLimit
  }
  let limits = { ..Limits::default(), max_output_samples, max_initial_scan }
  let decoder = Decoder::new(limits~)
  decoder.mpeg1_only = true
  collect_audio(decoder, data)
}

///|
fn collect_audio(decoder : Decoder, data : Bytes) -> Audio raise Mp3Error {
  let output : Array[Float] = []
  let mut sample_rate = 0
  let mut channels = 0
  let mut position = 0
  while true {
    position += decoder.push(data, offset=position)
    if position == data.length() {
      decoder.finish_input()
    }
    while true {
      match decoder.next_frame() {
        NeedMoreInput => break
        EndOfInput => {
          if channels == 0 {
            raise NoAudio
          }
          return { sample_rate, channels, samples: output }
        }
        Frame(frame) => {
          if frame.samples.length() >
            decoder.limits.max_output_samples - output.length() {
            raise OutputLimit
          }
          sample_rate = frame.sample_rate
          channels = frame.channels
          for sample in frame.samples {
            output.push(sample)
          }
        }
      }
    }
  } else {
    raise NoAudio
  }
}
