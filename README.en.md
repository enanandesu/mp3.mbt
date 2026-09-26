# mp3.mbt

[中文](README.md) | [API reference](docs/API.en.md) | [Validation results (Chinese)](docs/TEST_RESULTS.md)

A pure MoonBit decoder for MPEG-1, MPEG-2, and MPEG-2.5 Layer III. It accepts compressed `Bytes` and returns interleaved f32 PCM at the source sample rate. The decoding core has no third-party runtime dependency and supports the `native`, `wasm`, `wasm-gc`, and `js` backends.

The library offers whole-input and synchronous incremental decoding. A native MP3-to-WAV command and a browser playback demo are included. On the fixed local benchmark, native and wasm release builds exceeded the 10x and 1x realtime targets. Strict decoding and explicit compatibility recovery are available; see the declared acceptance scope and [measured results](docs/TEST_RESULTS.md).

## Supported input and boundaries

- Nine sampling rates across MPEG-1/2/2.5 Layer III; mono, stereo, and joint stereo (Mid/Side and intensity).
- Long, short, and mixed blocks; CBR, VBR, ABR, bounded free-format, and bit reservoir.
- Original sample rate and channel count are preserved. Stereo samples are interleaved left, right, left, right.
- Xing frames, encoder delay, and padding are not removed. CRC fields are skipped but not checked.
- Strict mode rejects missing reservoir history, truncated input, and format changes. Compatible mode recovers only the four documented cases below. Corruption, history gaps after output, and sample-rate/version changes remain fatal.
- The 8 kHz mixed-block path uses a bounded corrected frequency-band layout; its reference evidence is narrower than the regular corpus. See the [Layer III notes](internal/layer3/README.md).

## Use the library

For local development, place the consumer and this repository in a shared MoonBit workspace, for example:

```text
members = ["myapp", "mp3.mbt"]
```

Declare `enanandesu/mp3@0.1.0` in the consumer's `moon.mod`, then import `enanandesu/mp3` in its `moon.pkg`. If the module is published later, `moon add enanandesu/mp3` can fetch it.

Whole-input decoding:

```moonbit
let audio = @mp3.decode_all(mp3_bytes)
let rate = audio.sample_rate
let channels = audio.channels
let pcm = audio.samples
```

`decode_all` raises `Mp3Error` for invalid input or a resource limit. The `samples` field is an interleaved `Array[Float]`. The legacy `decode_mpeg1` entry point only accepts coded-bitrate MPEG-1 Layer III; it is not compatibility mode.

For streaming, create `@mp3.Decoder::new()`, pass bytes to `push(input, offset?)`, and call `next_frame()` until it returns `NeedMoreInput`. Keep bytes that `push` did not accept; a return value of zero means the decoder needs to consume a frame first. After all input has been accepted, call `finish_input()` and continue until `EndOfInput`. `Frame(PcmFrame)` contains caller-owned PCM, sample rate, channels, and source byte offset. Fatal decoding errors lock the decoder until `reset()`. The [API reference](docs/API.en.md) describes limits and every error constructor.

## Examples

### Native MP3 to WAV

Run from the repository root:

```sh
moon run examples/mp3-to-wav --target native --release -- input.mp3 output.wav
```

The command streams input through the MoonBit decoder and writes 16-bit little-endian PCM in a standard RIFF WAV file. It retains the original rate and channels, refuses to overwrite an existing output, and removes a partial output after failure. The RIFF size limit is about 4 GiB. On Windows with the pinned MinGW toolchain, set these PowerShell variables first:

```powershell
$env:MOON_CC = (Resolve-Path tools/moon-cc-mingw.cmd).Path
$env:MOON_AR = (Get-Command ar).Source
```

### Browser playback

```sh
moon build examples/browser --target js --release
python -m http.server 9010
```

Open [the local demo](http://127.0.0.1:9010/examples/browser/). Select or drop an MP3 to play, pause, seek, adjust volume, and view its waveform. The MoonBit JS build produces PCM; Web Audio only plays that PCM. Files stay in the browser. This minimal demo accepts files up to 16 MiB and at most 10 million interleaved decoded samples. Serve it over HTTP rather than opening `index.html` directly.

## Validation

These validation commands require a full repository checkout. The local package archive omits reference corpus binaries and validation scripts.

```sh
moon check
moon test
moon fmt --check
python tools/validate_compatibility.py
python tools/test_mp3_to_wav.py
node tools/test_browser_decode.mjs
```

The cross-backend suite requires Python 3.11+, GCC/MinGW with `ar`, FFmpeg/FFprobe, and Node. Exact pinned versions are recorded in [`tools/toolchain.lock.json`](tools/toolchain.lock.json). To run the optional Edge/Playwright UI smoke test, install `playwright-core` into ignored `target/browser-test`, serve the repository over HTTP, then run `node tools/test_browser_ui.mjs`. Set `EDGE_PATH` to a Chromium executable on other systems.

`moon package --list` previews the local archive; `.moonignore` omits repository-only corpora and validation tools. This packaging check does not upload or publish the module.

## Strict and compatibility modes

`decode_all`, `decode_mpeg1`, and the default `Decoder`/`decode_frames` use strict mode. Select compatibility explicitly:

```moonbit
let stream = @mp3.decode_frames(mp3_bytes, mode=Compatible)
let frames = stream.frames
let recoveries = stream.recoveries
```

`DecodedStream` preserves each frame's format and original offset without channel conversion. Incremental callers use `Decoder::new(mode=Compatible, on_recovery=event => println(event))`; the synchronous callback consumes events without accumulating them in the decoder. Fragmentation does not change PCM, offsets, or recovery records.

| Vector | Compatibility behavior |
| --- | --- |
| `compl.bit` | Discard an incomplete tail only after confirmed EOF; record its offset and discarded byte count. |
| `hecommon.bit` | Accept reserved emphasis value 2 while validating other header fields; record the frame. No de-emphasis processing is applied. |
| `sin1k0db.bit` | Initial frames lacking reservoir history emit no PCM but retain available history and main data; record required/available bytes and frame offsets. History gaps after the first output remain fatal. Apply the EOF rule to the tail. |
| `he_mode.bit` | Preserve each `PcmFrame.channels` and record transitions. `decode_frames` returns a frame array; `decode_all` continues to reject channel changes. |

Strict PCM success, strict expected rejection, and compatible complete PCM success are separate acceptance results. Complete PCM must meet the frozen scalar minimp3 f32 and supplied s16 reference rules. The 11 vectors are the pinned minimp3 README's ISO subset, not the complete official ISO test package or certification.

## Maintenance and future work

Run four-backend regression, malformed-input tests, the differential matrix, and compatible-mode acceptance for decoder changes. See [CI](docs/CI.md) for automation and platform locks, and [performance measurements](docs/PERFORMANCE.md) for browser and other-OS methods. Generated inputs, reproducible failures, and machine-readable results stay under ignored `target/`.

Future demand may justify gapless trimming, CRC validation, seeking/indexing, fuller ID3 reading, or asynchronous adapters. MP3 encoding, Layer I/II, SIMD, and fixed-point implementations are separate work. Review support boundaries, licenses, package contents, and consumer imports before release.

## License

Project code is [Apache-2.0](LICENSE). The decoder is adapted from a pinned minimp3 revision, whose original code is CC0-1.0; its license is kept in [`third_party/minimp3/LICENSE`](third_party/minimp3/LICENSE). Mirrored upstream test vectors come from that revision's `vectors/` directory; [`tests/corpus/manifest.json`](tests/corpus/manifest.json) records their individual origins and SHA-256 hashes. They are not original project code.
