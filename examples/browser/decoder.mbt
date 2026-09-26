///|
extern "js" fn deliver_audio(
  sample_rate : Int,
  channels : Int,
  samples : FixedArray[Float],
) -> Unit = "(rate, channels, samples) => globalThis.mp3Demo.receiveAudio(rate, channels, samples)"

///|
extern "js" fn deliver_error(message : String) -> Unit = "(message) => globalThis.mp3Demo.receiveError(message)"

///|
extern "js" fn valid_output_limit(value : Int) -> Bool = "(value) => Number.isInteger(value) && value >= 1 && value <= 2147483647"

///|
#export_name("decode_mp3")
pub fn decode_mp3(data : Bytes, max_output_samples : Int) -> Unit {
  if !valid_output_limit(max_output_samples) {
    deliver_error(
      "InvalidLimits: max_output_samples must be an integer from 1 to 2147483647.",
    )
    return
  }
  let limits = { ..@mp3.Limits::default(), max_output_samples, }
  try {
    let audio = @mp3.decode_all(data, limits~)
    deliver_audio(
      audio.sample_rate,
      audio.channels,
      FixedArray::from_array(audio.samples),
    )
  } catch {
    error => deliver_error("\{error}")
  }
}
