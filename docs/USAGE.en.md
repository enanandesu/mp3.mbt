# Practical example: prepare a local MP3 for editing and analysis

[中文](USAGE.md) · [Back to README examples](../README.en.md#examples)

Suppose you have an MP3 recording or podcast and want to check its contents, then pass the PCM to an editor or your own analysis program. This walkthrough uses the short bundled chime. Replace its path with your own recording once the example works.

The [sample audio](../examples/browser/sample.mp3) is an original, mathematically synthesized three-second, three-tone chime: 44.1 kHz stereo, 128 kbps CBR, and 48483 bytes. It is provided under the project's Apache-2.0 license and contains no external recording. A [generator script](../tools/generate_demo_audio.py) is included for regeneration.

Both the MP3-to-WAV command and the browser page decode with this library. Neither uploads your files. Follow the two steps below to convert and preview the sample.

## 1. Convert the MP3 to WAV

Run from the repository root. You need MoonBit plus the C compiler and `ar` used by its native backend; see [CI setup](CI.md) for the pinned toolchain. Conversion itself does not require FFmpeg.

On Windows with this repository's MinGW toolchain, first set these variables in the same PowerShell window:

```powershell
$env:MOON_CC = (Resolve-Path tools/moon-cc-mingw.cmd).Path
$env:MOON_AR = (Get-Command ar).Source
```

Create an output directory and convert the bundled sample:

```sh
python -c "from pathlib import Path; Path('target/usage-demo').mkdir(parents=True, exist_ok=True)"
moon run examples/mp3-to-wav --target native --release -- examples/browser/sample.mp3 target/usage-demo/sample.wav
```

The actual output for this bundled file is:

```text
WAV: 44100 Hz, 2 channel(s), 267264 samples
```

The WAV is 534572 bytes, with 133632 samples per channel and a decoded duration of approximately 3.03 seconds.

Import `target/usage-demo/sample.wav` into an editor that supports PCM WAV. It retains the source sample rate and channel count and stores 16-bit little-endian PCM. The printed `samples` count includes interleaved samples across all channels; it is not a per-channel count.

For your own file, replace the two paths. Quote paths containing spaces:

```sh
moon run examples/mp3-to-wav --target native --release -- "recording.mp3" "target/usage-demo/recording.wav"
```

The command reads, decodes, and writes one frame at a time without accumulating the entire PCM output, making it useful for longer recordings. It writes standard RIFF WAV with a limit of approximately 4 GiB. It refuses to overwrite an existing output, so use a new filename when repeating the example. Invalid input or an output failure produces a nonzero exit status and removes the incomplete WAV created by that run.

The command uses strict mode and does not automatically repair damaged MP3s. It also retains encoder delay and trailing padding. For precise editing, check the waveform boundaries instead of assuming that decoded duration exactly matches the original recording.

## 2. Listen and inspect the waveform in a browser

Still from the repository root:

```sh
moon build examples/browser --target js --release
python -m http.server 9010 --bind 127.0.0.1
```

Open [the local demo](http://127.0.0.1:9010/examples/browser/) and click **Load demo audio**. Once the waveform, sample rate, channels, and duration appear, click **Play**, drag the seek slider, then pause. You can also select or drop your own MP3. Stop the HTTP server with `Ctrl+C` when finished.

The MoonBit JS backend decodes the entire input before Web Audio plays the PCM. The page does not use the browser's native MP3 decoder. It accepts MP3 input; the WAV from step 1 is intended for your editor or analysis tools.

Adjust both settings before loading a longer file:

- **File size limit (MiB)** caps compressed input and defaults to 16 MiB. The page suggests 512 MiB as a desktop ceiling and permits higher values.
- **Decoded PCM limit (samples)** caps total interleaved output samples across all channels. It defaults to 10 million and sets `Limits.max_output_samples`. Duration is approximately `samples / channels / sample_rate`: five minutes at 44.1 kHz stereo needs about 26.46 million samples, plus room for MP3 frame boundaries and encoder padding.

A small compressed file can still produce a large decoded output. The page estimates f32 PCM size and duration; copies and playback buffers need additional memory. The largest accepted integer is not a guarantee that the browser can hold that output. Use the browser to preview audio; prefer the incremental command above when converting long recordings to WAV.

## 3. Use the PCM in your own MoonBit program

Follow [the README's import instructions](../README.en.md#use-the-library), then pass `Bytes` from your file, network, or other input layer to the root package. For example, calculate duration and sample peak:

```moonbit
fn summarize_mp3(mp3_bytes : Bytes) -> Unit raise @mp3.Mp3Error {
  let defaults = @mp3.Limits::default()
  let limits = { ..defaults, max_output_samples: 30000000 }
  let audio = @mp3.decode_all(mp3_bytes, limits~)
  let seconds = audio.samples.length().to_double() /
    audio.channels.to_double() /
    audio.sample_rate.to_double()
  let mut peak : Float = 0.0
  for sample in audio.samples {
    let magnitude = if sample < 0.0 { -sample } else { sample }
    if magnitude > peak {
      peak = magnitude
    }
  }
  println("duration: \{seconds} s, peak: \{peak}")
}
```

Passing the bundled `sample.mp3` bytes to this function produces:

```text
duration: 3.030204081632653 s, peak: 0.3119922876358032
```

The 30-million-sample limit allows about 114.4 MiB of f32 PCM for this call. It is a cap, not a preallocation size; runtime and decoding overhead are additional. The function propagates `Mp3Error`, including `OutputLimit` when the cap is exceeded. The caller handles input I/O, errors, and further analysis.

For long recordings or analysis as data arrives, follow the [WAV example source](../examples/mp3-to-wav/main.mbt) and use the incremental `Decoder`. Process and release each `PcmFrame` instead of retaining them all. See the [API reference](API.en.md#incremental-decoding) for backpressure, EOF, and limit semantics.
