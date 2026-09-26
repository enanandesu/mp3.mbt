///|
/// Strict is the default. Compatible recovers only the explicitly documented
/// EOF, reserved-emphasis, initial-history and channel-transition cases.
pub(all) enum DecodeMode {
  Strict
  Compatible
} derive(Eq, Show, Debug)

///|
/// Offsets refer to the original compressed input. A skipped history frame
/// contributes main data to the reservoir but produces no PCM.
pub(all) enum Recovery {
  TruncatedTail(offset~ : Int64, discarded_bytes~ : Int)
  ReservedEmphasis(offset~ : Int64, value~ : Int)
  MissingHistory(
    offset~ : Int64,
    frame_bytes~ : Int,
    required~ : Int,
    available~ : Int
  )
  ChannelChange(offset~ : Int64, previous~ : Int, current~ : Int)
} derive(Eq, Show, Debug)

///|
/// Whole-input result preserving each frame's format without channel conversion.
/// Samples and recovery records belong to the caller.
pub struct DecodedStream {
  frames : Array[PcmFrame]
  recoveries : Array[Recovery]
} derive(Show, Debug)

///|
/// Collect frames, including a mixed-channel stream in Compatible mode.
/// The output limit counts all interleaved samples across all frames.
pub fn decode_frames(
  data : Bytes,
  mode? : DecodeMode = Strict,
  limits? : Limits = Limits::default(),
) -> DecodedStream raise Mp3Error {
  let recoveries : Array[Recovery] = []
  let decoder = Decoder::new(mode~, limits~, on_recovery=event => {
    recoveries.push(event)
  })
  let frames : Array[PcmFrame] = []
  let mut position = 0
  let mut samples = 0
  while true {
    position += decoder.push(data, offset=position)
    if position == data.length() {
      decoder.finish_input()
    }
    while true {
      match decoder.next_frame() {
        NeedMoreInput => break
        EndOfInput => {
          if frames.is_empty() {
            raise NoAudio
          }
          return { frames, recoveries, }
        }
        Frame(frame) => {
          if frame.samples.length() > limits.max_output_samples - samples {
            raise OutputLimit
          }
          samples += frame.samples.length()
          frames.push(frame)
        }
      }
    }
  } nobreak {
    raise NoAudio
  }
}
