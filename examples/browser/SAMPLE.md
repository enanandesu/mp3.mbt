# Bundled demo audio

[`sample.mp3`](sample.mp3) is an original three-tone chime synthesized for this
project. It contains no external recording or sampled music. The audio and its
generator are covered by the project's [Apache-2.0 license](../../LICENSE).

- Source: three seconds of sine waves with an attack/decay envelope and stereo panning.
- Encoding: MPEG-1 Layer III, 44.1 kHz stereo, 128 kbps CBR; 48483 bytes.
- SHA-256: `38b3bc0fe061cb41a08226749d8fbfc81c68e56840922f8b03e72545decd2d56`.
- Decoder output: 267264 interleaved samples, about 3.03 seconds. Encoder delay
  and frame padding are retained by this library.

To regenerate from a full repository checkout, run:

```sh
python tools/generate_demo_audio.py
```

Regeneration requires Python and FFmpeg with `libmp3lame`. The checked-in asset
was encoded with the FFmpeg build recorded in
[`tools/toolchain.lock.json`](../../tools/toolchain.lock.json); other encoder
versions can produce different bytes. The intermediate WAV stays under ignored
`target/demo-audio/`. Playing or converting the bundled MP3 does not require FFmpeg.

See the [practical walkthrough](../../docs/USAGE.en.md) for conversion and playback.
