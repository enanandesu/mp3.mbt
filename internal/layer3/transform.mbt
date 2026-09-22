// Scalar stereo, reorder, antialias and IMDCT adapted from minimp3.h,
// ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0).
// Function correspondence: L3_midside_stereo, L3_intensity_stereo[_band],
// L3_stereo_top_band/process, L3_reorder/antialias, L3_dct3_9, L3_imdct36,
// L3_idct3, L3_imdct12/short/gr and L3_change_sign.
// Only MPEG-1 is enabled. Array offsets replace C pointer arithmetic; scalar
// Float operation order, the compressed 9-value overlap and scaling are kept.

///|
fn midside(samples : Array[Float], offset : Int, count : Int) -> Unit {
  for i = offset; i < offset + count; i = i + 1 {
    let a = samples[i]
    let b = samples[i + 576]
    samples[i] = a + b
    samples[i + 576] = a - b
  }
}

///|
fn stereo(
  samples : Array[Float],
  positions : Array[Int],
  gr : GranuleInfo,
  header : @header.Header,
) -> Unit {
  if !header.intensity_stereo() {
    if header.mid_side_stereo() {
      midside(samples, 0, 576)
    }
    return
  }
  let bands = gr.n_long_sfb + gr.n_short_sfb
  let max_band : Array[Int] = [-1, -1, -1]
  let mut offset = 576
  for i = 0; i < bands; i = i + 1 {
    for j = 0; j < gr.sfbtab[i]; j = j + 2 {
      if samples[offset + j] != 0.0 || samples[offset + j + 1] != 0.0 {
        max_band[i % 3] = i
        break
      }
    }
    offset += gr.sfbtab[i]
  }
  if gr.n_long_sfb != 0 {
    let first = if max_band[0] > max_band[1] {
      max_band[0]
    } else {
      max_band[1]
    }
    let largest = if first > max_band[2] { first } else { max_band[2] }
    for i = 0; i < 3; i = i + 1 {
      max_band[i] = largest
    }
  }
  let blocks = if gr.n_short_sfb != 0 { 3 } else { 1 }
  for i = 0; i < blocks; i = i + 1 {
    let top = bands - blocks + i
    let previous = top - blocks
    positions[top] = if max_band[i] >= previous {
      3
    } else {
      positions[previous]
    }
  }
  offset = 0
  for i = 0; i < bands; i = i + 1 {
    let position = positions[i]
    let count = gr.sfbtab[i]
    if i > max_band[i % 3] && position >= 0 && position < 7 {
      let scale : Float = if header.mid_side_stereo() {
        1.41421356
      } else {
        1.0
      }
      let kl = g_pan[2 * position] * scale
      let kr = g_pan[2 * position + 1] * scale
      for j = offset; j < offset + count; j = j + 1 {
        samples[j + 576] = samples[j] * kr
        samples[j] = samples[j] * kl
      }
    } else if header.mid_side_stereo() {
      midside(samples, offset, count)
    }
    offset += count
  }
}

///|
fn reorder(
  samples : Array[Float],
  base : Int,
  gr : GranuleInfo,
  long_bands : Int,
) -> Unit {
  let scratch : Array[Float] = Array::make(576, 0.0)
  let start = base + long_bands * 18
  let mut source = start
  let mut dest = 0
  for band = gr.n_long_sfb
      band < gr.n_long_sfb + gr.n_short_sfb
      band = band + 3 {
    let len = gr.sfbtab[band]
    for i = 0; i < len; i = i + 1 {
      for window = 0; window < 3; window = window + 1 {
        scratch[dest] = samples[source + i + window * len]
        dest += 1
      }
    }
    source += len * 3
  }
  for i = 0; i < dest; i = i + 1 {
    samples[start + i] = scratch[i]
  }
}

///|
fn antialias(samples : Array[Float], base : Int, bands : Int) -> Unit {
  for band = 0; band < bands; band = band + 1 {
    let offset = base + band * 18
    for i = 0; i < 8; i = i + 1 {
      let u = samples[offset + 18 + i]
      let d = samples[offset + 17 - i]
      samples[offset + 18 + i] = u * g_aa[i] - d * g_aa[8 + i]
      samples[offset + 17 - i] = u * g_aa[8 + i] + d * g_aa[i]
    }
  }
}

///|
fn dct3_9(y : Array[Float]) -> Unit {
  let mut s0 = y[0]
  let mut s2 = y[2]
  let mut s4 = y[4]
  let mut s6 = y[6]
  let mut s8 = y[8]
  let mut t0 = s0 + s6 * 0.5
  s0 -= s6
  let mut t4 = (s4 + s2) * 0.93969262
  let mut t2 = (s8 + s2) * 0.76604444
  s6 = (s4 - s8) * 0.17364818
  s4 += s8 - s2
  s2 = s0 - s4 * 0.5
  y[4] = s4 + s0
  s8 = t0 - t2 + s6
  s0 = t0 - t4 + t2
  s4 = t0 + t4 - s6
  let mut s1 = y[1]
  let mut s3 = y[3]
  let mut s5 = y[5]
  let mut s7 = y[7]
  s3 *= 0.86602540
  t0 = (s5 + s1) * 0.98480775
  t4 = (s5 - s7) * 0.34202014
  t2 = (s1 + s7) * 0.64278761
  s1 = (s1 - s5 - s7) * 0.86602540
  s5 = t0 - s3 - t2
  s7 = t4 - s3 - t0
  s3 = t4 + s3 - t2
  y[0] = s4 - s7
  y[1] = s2 + s1
  y[2] = s0 - s3
  y[3] = s8 + s5
  y[5] = s8 - s5
  y[6] = s0 + s3
  y[7] = s2 - s1
  y[8] = s4 + s7
}

///|
fn imdct36(
  samples : Array[Float],
  base : Int,
  overlap : Array[Float],
  ovbase : Int,
  window : Int,
  bands : Int,
) -> Unit {
  let co : Array[Float] = Array::make(9, 0.0)
  let si : Array[Float] = Array::make(9, 0.0)
  for band = 0; band < bands; band = band + 1 {
    let p = base + band * 18
    let o = ovbase + band * 9
    co[0] = -samples[p]
    si[0] = samples[p + 17]
    for i = 0; i < 4; i = i + 1 {
      si[8 - 2 * i] = samples[p + 4 * i + 1] - samples[p + 4 * i + 2]
      co[1 + 2 * i] = samples[p + 4 * i + 1] + samples[p + 4 * i + 2]
      si[7 - 2 * i] = samples[p + 4 * i + 4] - samples[p + 4 * i + 3]
      co[2 + 2 * i] = -(samples[p + 4 * i + 3] + samples[p + 4 * i + 4])
    }
    dct3_9(co)
    dct3_9(si)
    for i = 1; i < 8; i = i + 2 {
      si[i] = -si[i]
    }
    for i = 0; i < 9; i = i + 1 {
      let old = overlap[o + i]
      let sum = co[i] * g_twid9[9 + i] + si[i] * g_twid9[i]
      overlap[o + i] = co[i] * g_twid9[i] - si[i] * g_twid9[9 + i]
      samples[p + i] = old * g_mdct_window[window + i] -
        sum * g_mdct_window[window + 9 + i]
      samples[p + 17 - i] = old * g_mdct_window[window + 9 + i] +
        sum * g_mdct_window[window + i]
    }
  }
}

///|
fn idct3(x0 : Float, x1 : Float, x2 : Float) -> Array[Float] {
  let m1 = x1 * 0.86602540
  let a1 = x0 - x2 * 0.5
  [a1 + m1, x0 + x2, a1 - m1]
}

///|
fn imdct12(
  x : Array[Float],
  xbase : Int,
  dest : Array[Float],
  dbase : Int,
  overlap : Array[Float],
  obase : Int,
) -> Unit {
  let co = idct3(
    -x[xbase],
    x[xbase + 6] + x[xbase + 3],
    x[xbase + 12] + x[xbase + 9],
  )
  let si = idct3(
    x[xbase + 15],
    x[xbase + 12] - x[xbase + 9],
    x[xbase + 6] - x[xbase + 3],
  )
  si[1] = -si[1]
  for i = 0; i < 3; i = i + 1 {
    let old = overlap[obase + i]
    let sum = co[i] * g_twid3[3 + i] + si[i] * g_twid3[i]
    overlap[obase + i] = co[i] * g_twid3[i] - si[i] * g_twid3[3 + i]
    dest[dbase + i] = old * g_twid3[2 - i] - sum * g_twid3[5 - i]
    dest[dbase + 5 - i] = old * g_twid3[5 - i] + sum * g_twid3[2 - i]
  }
}

///|
fn hybrid(
  samples : Array[Float],
  base : Int,
  overlap : Array[Float],
  gr : GranuleInfo,
) -> Unit {
  let long_bands = if gr.mixed_block_flag != 0 { 2 } else { 0 }
  if gr.n_short_sfb != 0 {
    reorder(samples, base, gr, long_bands)
  }
  antialias(
    samples,
    base,
    if gr.n_short_sfb != 0 {
      long_bands - 1
    } else {
      31
    },
  )
  if long_bands > 0 {
    imdct36(samples, base, overlap, 0, 0, long_bands)
  }
  if gr.block_type == 2 {
    let temp : Array[Float] = Array::make(18, 0.0)
    for band = long_bands; band < 32; band = band + 1 {
      let p = base + band * 18
      let o = band * 9
      for i = 0; i < 18; i = i + 1 {
        temp[i] = samples[p + i]
      }
      for i = 0; i < 6; i = i + 1 {
        samples[p + i] = overlap[o + i]
      }
      imdct12(temp, 0, samples, p + 6, overlap, o + 6)
      imdct12(temp, 1, samples, p + 12, overlap, o + 6)
      imdct12(temp, 2, overlap, o, overlap, o + 6)
    }
  } else {
    imdct36(
      samples,
      base + long_bands * 18,
      overlap,
      long_bands * 9,
      if gr.block_type == 3 {
        18
      } else {
        0
      },
      32 - long_bands,
    )
  }
  for band = 1; band < 32; band = band + 2 {
    for i = 1; i < 18; i = i + 2 {
      let p = base + band * 18 + i
      samples[p] = -samples[p]
    }
  }
}
