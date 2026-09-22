# Layer III implementation sources

All algorithmic code and extracted tables in this package derive from
`third_party/minimp3/minimp3.h`, commit
`ea99364f61c14656440e8d77e9c233ccf3124633` (CC0-1.0). The original source and
license remain in `third_party/minimp3`. The core executes only MoonBit code.

| MoonBit source | Original functions |
| --- | --- |
| `common.mbt`, `side_info.mbt` | `bs_init`, `get_bits`, `L3_read_side_info` |
| `reservoir.mbt` | `L3_restore_reservoir`, `L3_save_reservoir` |
| `scalefactors.mbt` | `L3_read_scalefactors`, `L3_decode_scalefactors`, `L3_ldexp_q2` |
| `huffman.mbt` | `L3_pow_43`, `L3_huffman` |
| `transform.mbt` | `L3_midside_stereo`, `L3_intensity_stereo` and helpers, `L3_reorder`, `L3_antialias`, `L3_imdct_gr` and helpers, `L3_change_sign` |
| `synthesis.mbt` | `mp3d_DCT_II`, `mp3d_synth_pair`, `mp3d_synth`, `mp3d_synth_granule` |
| `decoder.mbt` | `L3_decode`, Layer III scheduling in `mp3dec_decode_frame` |

The scalar Float expression order, fused Huffman/dequantization, stereo-before-
reorder ordering, compressed IMDCT overlap, synthesis history and raw PCM extent
are preserved. Generation scripts extract constants from the source only after
checking its frozen hash; `--check` regenerates and compares all table/fixture
bytes. Each oracle executes the original C functions with SIMD disabled.

The following intentional differences define the bounded MPEG-1 interface:

- Pointers become checked byte cursors and arrays. Actual reads obey the
  granule's bit budget; speculative Huffman lookahead is explicitly zero-padded.
  An incomplete count1 group is discarded without borrowing sign bits from the
  next granule. The upstream-valid final two samples at index 574 are retained.
- Side information rejects reserved codebooks, invalid regions and invalid
  window fields. Private header/side-info bits cannot accidentally enable
  first-granule scfsi reuse. Unused fields have deterministic zero values.
- Missing reservoir history, truncated frames and changing stream formats are
  explicit errors. Reservoir storage retains at most 511 bytes. A fatal frame
  locks the decoder until reset clears reservoir, overlap and synthesis history.
- Returned PCM belongs to its caller. Later frames cannot overwrite it.
  MPEG-2/2.5 and free-format are explicitly unsupported at this interface until
  their separate compatibility work is complete.

`tools/layer3_trace.c` observes real continuous streams at side information,
main-data bytes, bit positions, scalefactors, dequantization, stereo, IMDCT, PCM
and retained-state checkpoints. It compares its final PCM with an unmodified
`mp3dec_decode_frame` invocation before emitting any frame's test data. C scratch
is zero-initialized; undefined synthesis tail slots, which are overwritten
before use, are never read from the original decoder or persisted.

The integration validator additionally constructs two legal mode-extension
variants of the fixed ABR fixture to exercise intensity stereo through the
entire pipeline. Only mode header bits change; the source corpus is untouched.
Each variant must differ from its corresponding non-intensity C control and
must match its own unmodified C decoder output on all four backends.
