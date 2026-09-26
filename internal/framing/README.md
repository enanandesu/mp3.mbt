# Bounded frame-length probing

`probe` examines one already-selected header at offset zero. It never scans
past garbage, owns no buffer/state and never silently resynchronizes. The
incremental decoder handles initial synchronization, tags and format changes.

The arithmetic and compatible-header search derive from `mp3d_find_frame` and
`mp3d_match_frame` in minimp3 commit
`ea99364f61c14656440e8d77e9c233ccf3124633` (CC0-1.0).

- Coded bitrate and known free-format sizes require only the current frame.
- Unknown free-format sizes require three compatible headers, with each
  frame's padding removed before comparing the base length. Earliest confirmed
  spacing wins, as in upstream; integer multiples are not alternative streams.
- At EOF, exactly two complete frames with the same base may establish it.
  A lone frame cannot infer its own size from the end of input. EOF fallback
  candidates must agree; incomplete or unconfirmed discovery is an error.
- Every proposed frame must fit its header, optional CRC and side information.
  Default probing also preserves channel count. Explicit `compatible=true`
  allows channel-count changes and reserved emphasis, while preserving MPEG
  version, sample rate and coded/free-format mode.
- The default maximum unpadded size is inclusive at 2304 bytes. Padding may
  make the total 2305, so unknown discovery needs at most 4614 buffered bytes.
  Upstream's exclusive candidate-distance bound does not include that boundary.

`NeedMoreInput(n)` means a total of `n` bytes from the current candidate start.
`Frame(total, base)` reports a total size plus an optional unpadded free size.
Malformed headers, short EOF data, unconfirmed lengths and resource limits
have distinct `FrameError` variants. The caller must remove recognized trailing
tags before an EOF probe and enforce later frame boundaries itself.

`tools/generate_framing_vectors.py --check` reproduces 1440 normal C helper
vectors across nine sample rates, channels, CRC and padding, plus an unchanged
prefix of `l3-he_free.bit`. Boundary tests cover intentional differences from C.
