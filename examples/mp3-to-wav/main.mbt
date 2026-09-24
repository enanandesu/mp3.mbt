///|
#borrow(path)
extern "C" fn open_input(path : Bytes, length : Int) -> Int = "wav_cli_open_input"

///|
extern "C" fn read_byte() -> Int = "wav_cli_read_byte"

///|
#borrow(path)
extern "C" fn open_output(
  path : Bytes,
  length : Int,
  sample_rate : Int,
  channels : Int,
) -> Int = "wav_cli_open_output"

///|
extern "C" fn write_sample(value : Int) -> Int = "wav_cli_write_sample"

///|
extern "C" fn finish_output() -> Int = "wav_cli_finish_output"

///|
extern "C" fn abort_output() -> Unit = "wav_cli_abort_output"

///|
extern "C" fn exit_with(code : Int) -> Unit = "wav_cli_exit"

///|
fn pcm_s16(value : Float) -> Int {
  // Scalar rule from minimp3.h:mp3dec_f32_to_s16 (pinned upstream commit).
  let scaled = value * 32768.0
  if scaled >= 32766.5 {
    32767
  } else if scaled <= -32767.5 {
    -32768
  } else {
    let rounded = (scaled + 0.5).to_int()
    if rounded < 0 {
      rounded - 1
    } else {
      rounded
    }
  }
}

///|
fn convert(output_path : Bytes) -> Unit raise {
  let decoder = @mp3.Decoder::new()
  let mut input = b""
  let mut offset = 0
  let mut eof = false
  let mut finished = false
  let mut opened = false
  let mut sample_rate = 0
  let mut channels = 0
  let mut sample_count : Int64 = 0
  while true {
    match decoder.next_frame() {
      @mp3.Frame(frame) => {
        if !opened {
          if open_output(
              output_path,
              output_path.length(),
              frame.sample_rate,
              frame.channels,
            ) !=
            0 {
            fail("could not create WAV output (file exists or path is invalid)")
          }
          sample_rate = frame.sample_rate
          channels = frame.channels
          opened = true
        }
        for sample in frame.samples {
          if write_sample(pcm_s16(sample)) != 0 {
            fail("WAV output failed or exceeded the RIFF size limit")
          }
        }
        sample_count += frame.samples.length().to_int64()
      }
      @mp3.NeedMoreInput =>
        if offset < input.length() {
          let accepted = decoder.push(input, offset~)
          if accepted == 0 {
            fail("decoder input stalled")
          }
          offset += accepted
        } else if !eof {
          let chunk : Array[Byte] = []
          for i = 0; i < 4096; i = i + 1 {
            let next = read_byte()
            if next == -2 {
              fail("MP3 input read failed")
            }
            if next == -1 {
              eof = true
              break
            }
            chunk.push(next.to_byte())
          }
          input = Bytes::from_array(chunk)
          offset = 0
        } else if !finished {
          decoder.finish_input()
          finished = true
        } else {
          fail("decoder did not finish after EOF")
        }
      @mp3.EndOfInput => {
        if !opened {
          fail("MP3 input contains no audio")
        }
        if finish_output() != 0 {
          fail("could not finalize WAV output")
        }
        println(
          "WAV: \{sample_rate} Hz, \{channels} channel(s), \{sample_count} samples",
        )
        return
      }
    }
  }
}

///|
fn main {
  let args = @env.args()
  if args.length() != 3 {
    println("Usage: mp3-to-wav INPUT.mp3 OUTPUT.wav")
    exit_with(2)
    return
  }
  let input_path = @utf8.encode(args[1])
  let output_path = @utf8.encode(args[2])
  if open_input(input_path, input_path.length()) != 0 {
    println("Could not open MP3 input")
    exit_with(2)
    return
  }
  convert(output_path) catch {
    error => {
      println("Conversion failed: \{error}")
      abort_output()
      exit_with(1)
    }
  }
}
