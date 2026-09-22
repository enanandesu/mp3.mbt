# ID3 boundary helpers

This internal package uses only MoonBit's standard library and performs no I/O.
It implements boundary skipping, not metadata parsing or a streaming decoder.

- `inspect_id3v2(view, eof, max_tag_bytes)` recognizes one leading ID3v2.2,
  v2.3, or v2.4 tag. `Tag` returns the full skip length; `NeedMoreInput` returns
  the required total buffer length. A confirmed EOF instead returns
  `Invalid(Truncated(required, available))`. No bytes are consumed or copied.
- `max_tag_bytes` counts header, encoded payload, and optional footer. All size
  bytes must be synchsafe; sizes up to the format's 28-bit maximum are decoded
  safely and rejected before waiting if the configured limit is exceeded.
- Version-specific reserved flag bits are rejected. Revisions 0 through 254 are
  accepted; revision 255 and unsupported major versions are rejected. For v2.4,
  the footer is ten additional bytes and must repeat header bytes 3 through 9
  after `3DI`. Payload internals, including extended headers, compression,
  unsynchronisation, padding and frames, remain opaque.
- `trim_id3v1(view)` is valid only for a complete buffer ending at known EOF.
  It removes a trailing 128-byte `TAG` and its optional adjacent 227-byte `TAG+`.
  Isolated `TAG+`, nonterminal `TAG`, and too-short buffers are unchanged.
  In a stream, the caller must retain the last 355 bytes until EOF before using
  this function. A truncated ID3v1 cannot be reliably identified from bytes alone.

The source is `mp3dec_skip_id3v1` / `mp3dec_skip_id3v2` in
[minimp3 ea99364f61c14656440e8d77e9c233ccf3124633](https://github.com/lieff/minimp3/blob/ea99364f61c14656440e8d77e9c233ccf3124633/minimp3_ex.h).
The original license is retained in `third_party/minimp3/LICENSE`.
Unlike its C wrapper, these helpers never clamp a declared tag length to EOF;
they report incomplete input, malformed boundaries and resource limits. The C
helper does not validate version-specific flags or matching footer bytes.
The APEv2 tail branch is intentionally excluded, and appended ID3v2 is not
detected. These unsupported tag families require later explicit policy, not
claims of general metadata support.

Boundary rules were checked against the primary informal specifications:
[v2.2 section 3.1](https://id3.org/id3v2-00?action=raw),
[v2.3 section 3.1](https://id3.org/id3v2.3.0?action=raw), and
[v2.4 sections 3.1/3.4](https://id3.org/id3v2.4.0-structure?action=raw).
Accepting zero-sized/opaque payloads is intentional for boundary skipping and
does not assert full tag conformance.

`python tools/generate_tags_vectors.py --check` recompiles the fixed upstream C
oracle and verifies 90 leading and 24 trailing cases against committed vectors.
The C build disables APEv2 to isolate the ID3v1/TAG+ contract. Handwritten tests
exercise all flag bytes, every split of a tag with/without a footer, invalid
synchsafe bytes, size limits, every footer field, and local slice offsets.
