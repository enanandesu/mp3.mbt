// Independent upstream differential coverage for transform.mbt.
// Oracle invokes original minimp3 helpers (CC0-1.0); this file generates inputs
// only. Expectations include signed zero and every binary32 result.

///|
fn transform_random(seed : Ref[UInt]) -> Float {
  seed.val = seed.val * 1664525U + 1013904223U
  Float::from_int((seed.val >> 16).reinterpret_as_int() - 32768) *
  (1.0 / 32768.0)
}

///|
fn transform_frame(meta : FixedArray[Int]) -> Bytes {
  let rate = meta[1]
  let size = 144000 * 128 / [44100, 48000, 32000][rate]
  Bytes::makei(size, fn(i) {
    if i < 4 {
      return [255, 251, 144 | (rate << 2), [0, 0x60, 0x50, 0x70][meta[2]]][i].to_byte()
    }
    let mut value = 0
    for gr = 0; gr < 4; gr = gr + 1 {
      let block = meta[if gr % 2 == 0 { 5 } else { 7 }]
      let mixed = meta[if gr % 2 == 0 { 6 } else { 8 }]
      if block != 0 {
        // window_switching_flag, block_type and mixed_block_flag.
        let fields = [1, (block >> 1) & 1, block & 1, mixed]
        for j = 0; j < 4; j = j + 1 {
          let bit = 32 + 20 + gr * 59 + 33 + j
          if bit / 8 == i {
            value = value | (fields[j] << (7 - bit % 8))
          }
        }
      }
    }
    value.to_byte()
  })
}

///|
fn transform_expected_word(expected : Array[Bytes], index : Int) -> UInt {
  let byte = index * 4
  let chunk = expected[byte / 256]
  let j = byte % 256
  chunk[j].to_uint() |
  (chunk[j + 1].to_uint() << 8) |
  (chunk[j + 2].to_uint() << 16) |
  (chunk[j + 3].to_uint() << 24)
}

///|
fn transform_check(
  actual : Array[Float],
  expected : Array[Bytes],
  offset : Int,
  context : String,
) -> Unit raise {
  for i = 0; i < actual.length(); i = i + 1 {
    let got = actual[i].reinterpret_as_uint()
    let want = transform_expected_word(expected, offset + i)
    assert_eq(
      got,
      want,
      msg="\{context}, index=\{i}, actual bits=\{got}, expected bits=\{want}",
    )
  }
}

///|
test "stereo and hybrid match C over all MPEG1 rates and continuous block transitions" {
  let seed = Ref::new(0U)
  let overlap : Array[Array[Float]] = [
    Array::make(288, 0.0),
    Array::make(288, 0.0),
  ]
  let mut previous_group = -1
  for vector = 0
      vector < transform_oracle_metadata.length()
      vector = vector + 1 {
    let meta = transform_oracle_metadata[vector]
    let group = meta[0]
    let input = meta[3]
    let step = meta[4]
    if group != previous_group {
      seed.val = meta[9].reinterpret_as_uint()
      for ch = 0; ch < 2; ch = ch + 1 {
        for i = 0; i < 288; i = i + 1 {
          overlap[ch][i] = if input == 0 { transform_random(seed) } else { 0.0 }
        }
      }
      previous_group = group
    }
    let frame = transform_frame(meta)
    let header = @header.parse(frame).unwrap()
    let side = read_side_info(frame, header)
    let gr = side.granules[0]
    let positions = Array::makei(39, fn(i) { (i + group + step) % 8 })
    let samples : Array[Float] = Array::make(1152, 0.0)
    if input == 0 {
      for i = 0; i < 1152; i = i + 1 {
        samples[i] = transform_random(seed)
      }
      let profile = (group / 3 + group % 3 + step) % 3
      let mut offset = 576
      for band = 0; band < gr.n_long_sfb + gr.n_short_sfb; band = band + 1 {
        let active = profile == 2 || (profile == 1 && band <= 4 * (band % 3))
        if !active {
          for i = 0; i < gr.sfbtab[band]; i = i + 1 {
            samples[offset + i] = 0.0
          }
        }
        offset += gr.sfbtab[band]
      }
    } else if step < 3 {
      samples[step * 113 % 576] = 1.0
      samples[575 - step * 19] = -0.75
      samples[576 + (step * 181 + 17) % 576] = 0.5
    }
    let expected = transform_oracle_vectors[vector]
    stereo(samples, positions, gr, header)
    transform_check(samples, expected, 0, "stereo group=\{group}, step=\{step}")
    for i = 0; i < 39; i = i + 1 {
      assert_eq(
        positions[i].reinterpret_as_uint(),
        transform_expected_word(expected, 2880 + i),
        msg="intensity position group=\{group}, step=\{step}, index=\{i}",
      )
    }
    for ch = 0; ch < 2; ch = ch + 1 {
      hybrid(samples, ch * 576, overlap[ch], side.granules[ch])
    }
    transform_check(
      samples,
      expected,
      1152,
      "hybrid group=\{group}, step=\{step}",
    )
    for ch = 0; ch < 2; ch = ch + 1 {
      transform_check(
        overlap[ch],
        expected,
        2304 + ch * 288,
        "overlap group=\{group}, step=\{step}, channel=\{ch}",
      )
    }
  }
  assert_eq(transform_oracle_metadata.length(), 66)
}
