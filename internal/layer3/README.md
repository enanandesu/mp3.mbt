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
bytes. Oracles execute scalar C functions with SIMD disabled; the 8 kHz mixed
block table correction described below is an explicit exception.

The package supports MPEG-1, MPEG-2 and MPEG-2.5 across all nine sample rates.
MPEG-1 reads two granules per frame and supports scfsi reuse. The low sample
rate versions read one granule, use all six LSF scalefactor partition groups,
derive preflag from scalefac_compress, and preserve the intensity-position
sentinel 255. LSF intensity attenuation uses the right channel's compression
parity. An 8 kHz mixed block uses four long transform subbands.

The following intentional differences define the bounded frame interface:

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
- Free-format decoding requires an explicit `free_format_size`: the unpadded
  total frame length, including header and side information. Its maximum is
  2304 bytes; a padded frame may total 2305 bytes. The padded total must cover
  the complete header, optional CRC and side information. This core interface
  validates the supplied extent; it does not discover frame boundaries.

The fixed upstream's 8 kHz mixed table is internally inconsistent: it has 39
bands although side information declares six long plus thirty short bands.
Its first six widths total 48 samples, but reorder and mixed IMDCT start after
four long subbands, at sample 72. Following the original table to its sentinel
would process 528 short samples and access up to sample 599 of a 576-sample
channel. Those accesses are not a usable numerical reference.

`generate_side_info_vectors.py` derives this single mixed row from the same
pinned CC0 tables as `long[1][:6] + short[1][9:]`. Six 12-sample long bands cover
72 samples; the remaining thirty short bands cover 504, yielding exactly 576
samples and one terminator. All other extracted rows remain unchanged.
`low_version_oracle.c` applies this same table correction only for 8 kHz mixed
cases before calling the original stereo/reorder/IMDCT helpers. These fixtures
are explicitly labeled as corrected-table C results, not unmodified-decoder
equivalence. The continuous trace tool excludes the original C's unsafe branch.
FFmpeg reports that the 8 kHz switch point is not implemented, so its PCM is not
an acceptance reference for this branch. Compatibility tests separately enforce
the 72-sample boundary, the 576-sample extent, and continuity of mixed-block
window transitions.

`generate_low_version_vectors.py` also extracts LSF partition/modulus tables
and reproduces 3072 scalefactor cases spanning every compression value, layout
and intensity branch, 180 side-info cases across nine rates and five block
layouts, and 360 stereo/hybrid cases including both LSF intensity scale values.
The fixtures compare bit positions and ordered hashes of every binary32 value
and intensity position, including signed zero. Existing MPEG-1 differential
fixtures continue to compare individual values without relaxed tolerances.

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
