///|
extern "js" fn deliver_audio(
  sample_rate : Int,
  channels : Int,
  samples : FixedArray[Float],
) -> Unit = "(rate, channels, samples) => globalThis.mp3Demo.receiveAudio(rate, channels, samples)"

///|
extern "js" fn deliver_error(message : String) -> Unit = "(message) => globalThis.mp3Demo.receiveError(message)"

///|
#export_name("decode_mp3")
pub fn decode_mp3(data : Bytes) -> Unit {
  let limits = { ..@mp3.Limits::default(), max_output_samples: 10000000, }
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
