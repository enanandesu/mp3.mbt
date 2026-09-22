// Deterministic continuous synthesis differential tests, CC0-1.0 reference.
// See tools/synthesis_oracle.c for the independent upstream execution.

///|
fn synth_test_random(seed : Ref[UInt]) -> Float {
  seed.val = seed.val * 1664525U + 1013904223U
  Float::from_int((seed.val >> 16).reinterpret_as_int() - 32768) *
  (1.0 / 32768.0)
}

///|
fn synth_check_words(
  actual : Array[Float],
  expected : Array[Bytes],
  offset : Int,
  count : Int,
) -> Unit raise {
  for i = 0; i < count; i = i + 1 {
    let byte = (offset + i) * 4
    let chunk = expected[byte / 256]
    let j = byte % 256
    let bits = chunk[j].to_uint() |
      (chunk[j + 1].to_uint() << 8) |
      (chunk[j + 2].to_uint() << 16) |
      (chunk[j + 3].to_uint() << 24)
    assert_eq(actual[i].reinterpret_as_uint(), bits)
  }
}

///|
test "scalar synthesis matches C for consecutive mono and stereo granules" {
  let mut vector = 0
  for initial_channels = 1
      initial_channels <= 2
      initial_channels = initial_channels + 1 {
    for mode = 0; mode < 3; mode = mode + 1 {
      let seed = Ref::new(
        0x735193abU + (mode * 32 + initial_channels).reinterpret_as_uint(),
      )
      let state = Array::make(960, 0.0F)
      for step = 0; step < 3; step = step + 1 {
        let nch = initial_channels
        let grbuf = Array::make(1152, 0.0F)
        if mode == 2 {
          for i = 0; i < nch * 576; i = i + 1 {
            grbuf[i] = synth_test_random(seed)
          }
        } else if mode == 1 && step == 0 {
          grbuf[0] = 1.0
          grbuf[18 * 31 + 17] = -0.75
          if nch == 2 {
            grbuf[576 + 16 * 18 + 9] = 0.5
            grbuf[576 + 17] = -1.0
          }
        }
        let pcm = synth_granule(state, grbuf, nch)
        let expected = synth_oracle_vectors[vector]
        synth_check_words(pcm, expected, 0, 576 * nch)
        synth_check_words(state, expected, 576 * nch, 960)
        synth_check_words(grbuf, expected, 576 * nch + 960, 576 * nch)
        vector += 1
      }
    }
  }
  assert_eq(vector, 18)
}

///|
test "synthesis preserves upstream state layout across channel changes" {
  let seed = Ref::new(0x735193abU + 98U)
  let state = Array::makei(960, fn(_) { synth_test_random(seed) })
  for step = 0; step < 4; step = step + 1 {
    let nch = 2 - step % 2
    let grbuf = Array::make(1152, 0.0F)
    for i = 0; i < nch * 576; i = i + 1 {
      grbuf[i] = synth_test_random(seed)
    }
    let pcm = synth_granule(state, grbuf, nch)
    let expected = synth_oracle_vectors[18 + step]
    synth_check_words(pcm, expected, 0, 576 * nch)
    synth_check_words(state, expected, 576 * nch, 960)
    synth_check_words(grbuf, expected, 576 * nch + 960, 576 * nch)
  }
}
