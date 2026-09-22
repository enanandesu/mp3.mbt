// Scalar synthesis adapted from minimp3.h, CC0-1.0.
// https://github.com/lieff/minimp3
// Commit ea99364f61c14656440e8d77e9c233ccf3124633:
// mp3d_DCT_II, mp3d_synth_pair, mp3d_synth, mp3d_synth_granule.
// Expressions retain upstream Float (IEEE binary32) evaluation order.

///|
fn synth_dct_ii(grbuf : Array[Float], base : Int, t : Array[Float]) -> Unit {
  for k = 0; k < 18; k = k + 1 {
    for i = 0; i < 8; i = i + 1 {
      let x0 = grbuf[base + k + i * 18]
      let x1 = grbuf[base + k + (15 - i) * 18]
      let x2 = grbuf[base + k + (16 + i) * 18]
      let x3 = grbuf[base + k + (31 - i) * 18]
      let t0 = x0 + x3
      let t1 = x1 + x2
      let t2 = (x1 - x2) * synth_sec[3 * i]
      let t3 = (x0 - x3) * synth_sec[3 * i + 1]
      t[i] = t0 + t1
      t[i + 8] = (t0 - t1) * synth_sec[3 * i + 2]
      t[i + 16] = t3 + t2
      t[i + 24] = (t3 - t2) * synth_sec[3 * i + 2]
    }
    for i = 0; i < 4; i = i + 1 {
      let p = i * 8
      let mut x0 = t[p]
      let mut x1 = t[p + 1]
      let mut x2 = t[p + 2]
      let mut x3 = t[p + 3]
      let mut x4 = t[p + 4]
      let mut x5 = t[p + 5]
      let mut x6 = t[p + 6]
      let mut x7 = t[p + 7]
      let mut xt = x0 - x7
      x0 += x7
      x7 = x1 - x6
      x1 += x6
      x6 = x2 - x5
      x2 += x5
      x5 = x3 - x4
      x3 += x4
      x4 = x0 - x3
      x0 += x3
      x3 = x1 - x2
      x1 += x2
      t[p] = x0 + x1
      t[p + 4] = (x0 - x1) * 0.70710677
      x5 = x5 + x6
      x6 = (x6 + x7) * 0.70710677
      x7 = x7 + xt
      x3 = (x3 + x4) * 0.70710677
      x5 -= x7 * 0.198912367
      x7 += x5 * 0.382683432
      x5 -= x7 * 0.198912367
      x0 = xt - x6
      xt += x6
      t[p + 1] = (xt + x7) * 0.50979561
      t[p + 2] = (x4 + x3) * 0.54119611
      t[p + 3] = (x0 - x5) * 0.60134488
      t[p + 5] = (x0 + x5) * 0.89997619
      t[p + 6] = (x4 - x3) * 1.30656302
      t[p + 7] = (xt - x7) * 2.56291556
    }
    for i = 0; i < 7; i = i + 1 {
      let y = base + k + i * 4 * 18
      grbuf[y] = t[i]
      grbuf[y + 18] = t[16 + i] + t[24 + i] + t[25 + i]
      grbuf[y + 36] = t[8 + i] + t[9 + i]
      grbuf[y + 54] = t[17 + i] + t[24 + i] + t[25 + i]
    }
    let y = base + k + 28 * 18
    grbuf[y] = t[7]
    grbuf[y + 18] = t[23] + t[31]
    grbuf[y + 36] = t[15]
    grbuf[y + 54] = t[31]
  }
}

///|
fn synth_pair(
  pcm : Array[Float],
  dst : Int,
  nch : Int,
  lins : Array[Float],
  z : Int,
) -> Unit {
  let mut a = (lins[z + 14 * 64] - lins[z]) * 29.0
  a += (lins[z + 64] + lins[z + 13 * 64]) * 213.0
  a += (lins[z + 12 * 64] - lins[z + 2 * 64]) * 459.0
  a += (lins[z + 3 * 64] + lins[z + 11 * 64]) * 2037.0
  a += (lins[z + 10 * 64] - lins[z + 4 * 64]) * 5153.0
  a += (lins[z + 5 * 64] + lins[z + 9 * 64]) * 6574.0
  a += (lins[z + 8 * 64] - lins[z + 6 * 64]) * 37489.0
  a += lins[z + 7 * 64] * 75038.0
  pcm[dst] = a * (1.0 / 32768.0)
  let z = z + 2
  a = lins[z + 14 * 64] * 104.0
  a += lins[z + 12 * 64] * 1567.0
  a += lins[z + 10 * 64] * 9727.0
  a += lins[z + 8 * 64] * 64019.0
  a += lins[z + 6 * 64] * -9975.0
  a += lins[z + 4 * 64] * -45.0
  a += lins[z + 2 * 64] * 146.0
  a += lins[z] * -5.0
  pcm[dst + 16 * nch] = a * (1.0 / 32768.0)
}

///|
fn synth_block(
  grbuf : Array[Float],
  xl : Int,
  pcm : Array[Float],
  dstl : Int,
  nch : Int,
  lins : Array[Float],
  lin : Int,
  a : Array[Float],
  b : Array[Float],
) -> Unit {
  let xr = xl + 576 * (nch - 1)
  let dstr = dstl + nch - 1
  let zlin = lin + 15 * 64
  lins[zlin + 60] = grbuf[xl + 18 * 16]
  lins[zlin + 61] = grbuf[xr + 18 * 16]
  lins[zlin + 62] = grbuf[xl]
  lins[zlin + 63] = grbuf[xr]
  lins[zlin + 124] = grbuf[xl + 1 + 18 * 16]
  lins[zlin + 125] = grbuf[xr + 1 + 18 * 16]
  lins[zlin + 126] = grbuf[xl + 1]
  lins[zlin + 127] = grbuf[xr + 1]
  synth_pair(pcm, dstr, nch, lins, lin + 61)
  synth_pair(pcm, dstr + 32 * nch, nch, lins, lin + 125)
  synth_pair(pcm, dstl, nch, lins, lin + 60)
  synth_pair(pcm, dstl + 32 * nch, nch, lins, lin + 124)
  for i = 14; i >= 0; i = i - 1 {
    let z = zlin + 4 * i
    lins[z] = grbuf[xl + 18 * (31 - i)]
    lins[z + 1] = grbuf[xr + 18 * (31 - i)]
    lins[z + 2] = grbuf[xl + 1 + 18 * (31 - i)]
    lins[z + 3] = grbuf[xr + 1 + 18 * (31 - i)]
    lins[z + 64] = grbuf[xl + 1 + 18 * (1 + i)]
    lins[z + 65] = grbuf[xr + 1 + 18 * (1 + i)]
    lins[z - 62] = grbuf[xl + 18 * (1 + i)]
    lins[z - 61] = grbuf[xr + 18 * (1 + i)]
    let wi = (14 - i) * 16
    for k = 0; k < 8; k = k + 1 {
      let w0 = synth_win[wi + 2 * k]
      let w1 = synth_win[wi + 2 * k + 1]
      for j = 0; j < 4; j = j + 1 {
        let vz = lins[z - k * 64 + j]
        let vy = lins[z - (15 - k) * 64 + j]
        if k == 0 {
          b[j] = vz * w1 + vy * w0
          a[j] = vz * w0 - vy * w1
        } else {
          b[j] += vz * w1 + vy * w0
          if k % 2 == 0 {
            a[j] += vz * w0 - vy * w1
          } else {
            a[j] += vy * w1 - vz * w0
          }
        }
      }
    }
    pcm[dstr + (15 - i) * nch] = a[1] * (1.0 / 32768.0)
    pcm[dstr + (17 + i) * nch] = b[1] * (1.0 / 32768.0)
    pcm[dstl + (15 - i) * nch] = a[0] * (1.0 / 32768.0)
    pcm[dstl + (17 + i) * nch] = b[0] * (1.0 / 32768.0)
    pcm[dstr + (47 - i) * nch] = a[3] * (1.0 / 32768.0)
    pcm[dstr + (49 + i) * nch] = b[3] * (1.0 / 32768.0)
    pcm[dstl + (47 - i) * nch] = a[2] * (1.0 / 32768.0)
    pcm[dstl + (49 + i) * nch] = b[2] * (1.0 / 32768.0)
  }
}

///|
/// Synthesize one Layer III granule, updating its frequency buffer and state.
/// Internal preconditions: state has 960 values, grbuf has 1152, nch is 1 or 2.
/// Mono updates only even state cells, matching the upstream state layout.
fn synth_granule(
  qmf_state : Array[Float],
  grbuf : Array[Float],
  nch : Int,
) -> Array[Float] {
  let scratch = Array::make(32, 0.0F)
  for ch = 0; ch < nch; ch = ch + 1 {
    synth_dct_ii(grbuf, 576 * ch, scratch)
  }
  let lins = Array::make(33 * 64, 0.0F)
  for i = 0; i < 960; i = i + 1 {
    lins[i] = qmf_state[i]
  }
  let pcm = Array::make(576 * nch, 0.0F)
  let a = Array::make(4, 0.0F)
  let b = Array::make(4, 0.0F)
  for i = 0; i < 18; i = i + 2 {
    synth_block(grbuf, i, pcm, 32 * nch * i, nch, lins, i * 64, a, b)
  }
  let stride = if nch == 1 { 2 } else { 1 }
  for i = 0; i < 960; i = i + stride {
    qmf_state[i] = lins[18 * 64 + i]
  }
  pcm
}
