// Scalar port of minimp3.h L3_read_scalefactors, L3_ldexp_q2 and
// L3_decode_scalefactors at ea99364f61c14656440e8d77e9c233ccf3124633
// (CC0-1.0). Float is deliberately f32 and expression order is preserved.

///|
fn ldexp_q2(y : Float, exp_q2 : Int) -> Float {
  let fractions : Array[Float] = [
    9.31322575e-10, 7.83145814e-10, 6.58544508e-10, 5.53767716e-10,
  ]
  let mut value = y
  let mut exponent = exp_q2
  while true {
    let e = if exponent < 120 { exponent } else { 120 }
    value = value * (fractions[e & 3] * Float::from_int(1 << 30 >> (e >> 2)))
    exponent -= e
    if exponent <= 0 {
      break
    }
  }
  value
}

// BEGIN GENERATED SCALEFACTOR PARTITIONS

// Generated from pinned L3_decode_scalefactors; do not edit.

///|
let scf_partitions : Array[Array[Int]] = [
  [
    6, 5, 5, 5, 6, 5, 5, 5, 6, 5, 7, 3, 11, 10, 0, 0, 7, 7, 7, 0, 6, 6, 6, 3, 8,
    8, 5, 0,
  ],
  [
    8, 9, 6, 12, 6, 9, 9, 9, 6, 9, 12, 6, 15, 18, 0, 0, 6, 15, 12, 0, 6, 12, 9, 6,
    6, 18, 9, 0,
  ],
  [
    9, 9, 6, 12, 9, 9, 9, 9, 9, 9, 12, 6, 18, 18, 0, 0, 12, 12, 12, 0, 12, 9, 9,
    6, 15, 12, 9, 0,
  ],
]

///|
let scf_moduli : Array[Int] = [
  5, 5, 4, 4, 5, 5, 4, 1, 4, 3, 1, 1, 5, 6, 6, 1, 4, 4, 4, 1, 4, 3, 1, 1,
]
// END GENERATED SCALEFACTOR PARTITIONS

///|
fn decode_scalefactors(
  header : @header.Header,
  ist_pos : Array[Int],
  bits : BitCursor,
  gr : GranuleInfo,
  channel : Int,
) -> Array[Float] raise DecodeError {
  let mpeg1 = header.version == @header.Mpeg1
  if channel < 0 ||
    channel >= header.channels() ||
    ist_pos.length() < 39 ||
    gr.scalefac_compress < 0 ||
    gr.scalefac_compress > (if mpeg1 { 15 } else { 511 }) ||
    gr.scalefac_scale < 0 ||
    gr.scalefac_scale > 1 ||
    gr.global_gain < 0 ||
    gr.global_gain > 255 ||
    gr.scfsi < 0 ||
    gr.scfsi > 15 {
    raise InvalidSideInfo("invalid scalefactor fields")
  }
  let layout = if gr.n_short_sfb == 0 && gr.n_long_sfb == 22 {
    0
  } else if gr.n_short_sfb == 39 && gr.n_long_sfb == 0 {
    2
  } else if gr.n_short_sfb == 30 && gr.n_long_sfb == (if mpeg1 { 8 } else { 6 }) {
    1
  } else {
    raise InvalidSideInfo("invalid scalefactor layout")
  }
  if gr.subblock_gain.length() != 3 ||
    gr.subblock_gain.iter().any(fn(x) { x < 0 || x > 7 }) {
    raise InvalidSideInfo("invalid subblock gain")
  }
  let sizes = Array::make(4, 0)
  let mut partition_offset = 0
  let mut scfsi = gr.scfsi
  if mpeg1 {
    let decoded = [0, 1, 2, 3, 12, 5, 6, 7, 9, 10, 11, 13, 14, 15, 18, 19][gr.scalefac_compress]
    sizes[0] = decoded >> 2
    sizes[1] = decoded >> 2
    sizes[2] = decoded & 3
    sizes[3] = decoded & 3
  } else {
    let intensity = if header.intensity_stereo() && channel != 0 {
      1
    } else {
      0
    }
    let mut sfc = gr.scalefac_compress >> intensity
    let mut k = intensity * 12
    while sfc >= 0 {
      let mut product = 1
      for i = 3; i >= 0; i = i - 1 {
        sizes[i] = sfc / product % scf_moduli[k + i]
        product *= scf_moduli[k + i]
      }
      sfc -= product
      k += 4
    }
    partition_offset = k
    scfsi = -16
  }
  let iscf = Array::make(40, 0)
  let mut offset = 0
  for part = 0; part < 4; part = part + 1 {
    let count = scf_partitions[layout][partition_offset + part]
    if count == 0 {
      break
    }
    for k = 0; k < count; k = k + 1 {
      if (scfsi & 8) != 0 {
        iscf[offset + k] = ist_pos[offset + k]
      } else {
        let value = bits.read(sizes[part])
        iscf[offset + k] = value
        // uint8_t -1 in upstream is the sentinel 255. A zero-width group
        // explicitly writes zero and must never become the sentinel.
        ist_pos[offset + k] = if scfsi < 0 &&
          sizes[part] != 0 &&
          value == (1 << sizes[part]) - 1 {
          255
        } else {
          value
        }
      }
    }
    offset += count
    scfsi *= 2
  }
  let scf_shift = gr.scalefac_scale + 1
  if gr.n_short_sfb != 0 {
    let shift = 3 - scf_shift
    for i = 0; i < gr.n_short_sfb; i = i + 3 {
      for win = 0; win < 3; win = win + 1 {
        iscf[gr.n_long_sfb + i + win] += gr.subblock_gain[win] << shift
      }
    }
  } else if gr.preflag != 0 {
    let preamp = [1, 1, 1, 1, 2, 2, 3, 3, 3, 2]
    for i = 0; i < 10; i = i + 1 {
      iscf[11 + i] += preamp[i]
    }
  }
  let gain_exp = gr.global_gain -
    4 -
    210 -
    (if header.mid_side_stereo() { 2 } else { 0 })
  let gain = ldexp_q2(2048.0, 44 - gain_exp)
  Array::makei(gr.n_long_sfb + gr.n_short_sfb, fn(i) {
    ldexp_q2(gain, iscf[i] << scf_shift)
  })
}
