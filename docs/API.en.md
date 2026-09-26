# mp3.mbt API

[中文](API.md) | [README](../README.en.md)

The `enanandesu/mp3` root package decodes MPEG-1, MPEG-2, and MPEG-2.5 Layer III bytes into interleaved f32 PCM. File I/O, playback, and WAV output belong to callers or the included examples. The exact exported signatures are also recorded in [`pkg.generated.mbti`](../pkg.generated.mbti).

## Output

| Type | Field | Meaning |
| --- | --- | --- |
| `Audio` | `sample_rate: Int` | Sample rate in Hz |
| | `channels: Int` | 1 or 2 |
| | `samples: Array[Float]` | Interleaved f32 PCM for the entire input |
| `PcmFrame` | `sample_rate: Int` | Frame sample rate in Hz |
| | `channels: Int` | 1 or 2 |
| | `source_offset: Int64` | Byte offset of this frame header in the original input, including skipped prefix bytes |
| | `samples: Array[Float]` | Caller-owned interleaved PCM for this frame |

Stereo ordering is left, right, left, right. Each MPEG-1 frame yields 1152 samples per channel; MPEG-2/2.5 yields 576. Xing frames, encoder delay, and tail padding remain in the output.

## Whole-input decoding

| Function | Behavior |
| --- | --- |
| `decode_all(data: Bytes, limits?: Limits) -> Audio raise Mp3Error` | Decode all supported Layer III versions through the incremental state machine. |
| `decode_mpeg1(data: Bytes, max_output_samples?: Int, max_initial_scan?: Int) -> Audio raise Mp3Error` | Legacy entry point for coded-bitrate MPEG-1 Layer III only; free-format is rejected. This is not compatibility mode. |

`data` contains complete MP3 bytes, supplied by the caller. Both helpers accumulate all samples and raise `NoAudio` if no frame is decoded. `max_output_samples` counts interleaved samples; a 1152-sample stereo frame consumes 2304 positions. `decode_mpeg1` defaults to 67108864 output samples and a 65536-byte initial scan, while other limits retain their defaults.

```moonbit
let audio = @mp3.decode_all(mp3_bytes)
let rate = audio.sample_rate
let channels = audio.channels
let pcm = audio.samples
```

## Compatibility and frame-preserving whole-input output

`decode_frames(data: Bytes, mode?: DecodeMode, limits?: Limits) -> DecodedStream raise Mp3Error` returns `frames: Array[PcmFrame]` and `recoveries: Array[Recovery]`. The default mode is `Strict`; use `mode=Compatible` to recover the cases below. Per-frame metadata represents mono/stereo transitions without a misleading stream-wide channel count. No channel conversion is performed; returned samples and records belong to the caller.

`max_output_samples` counts all interleaved samples across frames. Producing no decoded frame raises `NoAudio`, including input containing only initial history gaps. Use the incremental API to retain PCM and diagnostics preceding a fatal error.

| `Recovery` | Meaning |
| --- | --- |
| `TruncatedTail(offset~, discarded_bytes~)` | Confirmed EOF discards an incomplete frame or valid partial frame header. |
| `ReservedEmphasis(offset~, value~)` | Accept value 2; still validate other header fields. No de-emphasis is applied. |
| `MissingHistory(offset~, frame_bytes~, required~, available~)` | Initial frame emits no PCM but retains main data and available history. Counts are bytes. |
| `ChannelChange(offset~, previous~, current~)` | Subsequent frame metadata uses the new channel count. |

Offsets are original compressed-input byte offsets. Records follow processing order; events on the same frame are emphasis, channel change, then missing history. Corruption, history gaps after the first PCM output, and version/sample-rate changes remain fatal. Compatibility does not resynchronize across damaged midstream frames.

Use `Decoder::new(mode=Compatible, on_recovery=event => println(event))` for incremental recovery. The callback runs synchronously inside `next_frame()` and must not reenter the same decoder. The decoder retains no event history; an omitted callback discards events, keeping incremental internal memory bounded. `reset()` clears decoding history and preserves mode/callback.

## Incremental decoding

`Decoder` owns independent input buffering, bit reservoir, IMDCT overlap, and synthesis history.

| Method | Behavior |
| --- | --- |
| `Decoder::new(limits?: Limits, mode?: DecodeMode, on_recovery?: (Recovery) -> Unit) -> Decoder raise Mp3Error` | Create a decoder; invalid limits raise `InvalidLimits`. |
| `push(input: Bytes, offset?: Int) -> Int raise Mp3Error` | Copy as many bytes as fit from `input[offset:]`; return the accepted byte count. Default offset is 0. |
| `next_frame() -> DecodeResult raise Mp3Error` | Return a decoded frame, request more bytes, or signal the end. |
| `finish_input() -> Unit raise Mp3Error` | Confirm EOF after every byte has been accepted; repeated calls are harmless. |
| `buffered_bytes() -> Int` | Compressed input bytes still buffered, excluding returned PCM. |
| `reset() -> Unit` | Clear input, EOF, failure state, and decoding history while preserving configured limits, mode, and recovery callback. |

`DecodeResult` is `Frame(PcmFrame)`, `NeedMoreInput`, or `EndOfInput`. Retain bytes that `push` did not accept. If it returns zero, consume output with `next_frame()` and retry at the same offset. Call `finish_input()` only after all input is accepted, then read until `EndOfInput`. An empty incremental stream may end normally, unlike `decode_all`, which raises `NoAudio`.

`push` copies its input. A returned frame's `samples` array belongs to the caller and is not overwritten by subsequent decoding or `reset()`. An incomplete frame returns `NeedMoreInput` without committing partial DSP state. A fatal parsing or decoding error locks `push`, `next_frame`, and `finish_input` into `FailedDecoder` until `reset()`.

## Resource limits

Use `Limits::default()` and override fields as needed:

```moonbit
let limits = { ..@mp3.Limits::default(), max_output_samples: 1048576 }
let audio = @mp3.decode_all(mp3_bytes, limits~)
```

| `Limits` field | Default | Constraints and effect |
| --- | ---: | --- |
| `max_buffer_bytes` | 8192 | Compressed input ring buffer, range 2885..1048576; also obeys the lookahead formula below. |
| `max_tag_bytes` | 16777216 | Maximum total bytes in one leading ID3v2 tag, including header and optional footer; nonnegative. |
| `max_initial_scan` | 65536 | Maximum non-tag bytes skipped before the first frame; nonnegative. |
| `max_free_format_bytes` | 2304 | Maximum unpadded free-format frame length, range 4..2304. |
| `max_output_samples` | 67108864 | Total interleaved samples for whole-input helpers only; nonnegative. |

The buffer must also satisfy `max_buffer_bytes >= 2 * (max_free_format_bytes + 1) + 4 + 355`; with the default free-format limit this requires at least 4969 bytes. Incremental decoding does not accumulate returned PCM and does not use `max_output_samples` as a stream-wide limit.

## Errors

All public errors are constructors of `Mp3Error`:

| Constructor | Meaning |
| --- | --- |
| `InvalidHeader(offset)` | No valid header at this original byte offset, or a bad header after decoding started. |
| `InvalidTag` | Invalid, oversized, or incomplete leading ID3v2 tag. |
| `TruncatedFrame(offset, length)` | At EOF, this frame lacks bytes for its expected `length`. |
| `UnsupportedVersion` | `decode_mpeg1` encountered a non-MPEG-1 frame. |
| `UnsupportedFreeFormat` | `decode_mpeg1` encountered free-format. |
| `OutputLimit` | Whole-input output exceeded its sample cap; also used for negative `decode_mpeg1` limits. |
| `NoAudio` | Whole-input decoding ended without an audio frame. |
| `DecodeFailure(offset, cause)` | Layer III decoding failed; `cause` retains the lower-level error. |
| `FramingFailure(offset, cause)` | Frame length or free-format boundary detection failed. |
| `FormatChange(offset)` | Version, sample rate, channel count, or coded/free-format mode changed within the stream. |
| `InvalidLimits` | Invalid `Decoder::new` configuration. |
| `InvalidInputOffset(offset)` | `push` offset is outside `0..input.length()`. |
| `InputFinished` | `push` was called after `finish_input`. |
| `FailedDecoder` | Fatal error occurred and the decoder has not been reset. |

Offsets are relative to the original input bytes. `InvalidInputOffset` and `InputFinished` are usage errors and do not by themselves lock an otherwise healthy decoder. Bitrate changes are allowed. Strict mode rejects version, sample-rate, channel-count, and coded/free-format changes; Compatible additionally allows channel-count changes.

Leading ID3v2 tags and a bounded amount of leading non-tag data can be skipped. ID3v1/TAG+ trailers are accepted at frame boundaries; CRC fields are skipped without validation. Free-format discovery generally needs three compatible headers with the same unpadded frame size (physical spacing may differ by one padding byte), or exactly two complete frames at confirmed EOF. The 8 kHz mixed-block path has a documented difference from unmodified minimp3; see the [Layer III notes](../internal/layer3/README.md).
