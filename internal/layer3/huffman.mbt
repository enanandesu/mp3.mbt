// Scalar port of minimp3.h L3_pow_43 and L3_huffman, fixed upstream
// ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0).
// Lookup peeks are zero padded; every consumed bit is checked. An incomplete
// count1 quadruple is discarded atomically, including incomplete sign bits.

///|
fn pow_43(value : Int) -> Float {
  if value < 129 {
    return pow43_table[16 + value]
  }
  let mut x = value
  let mult : Float = if x < 1024 {
    x = x << 3
    16.0
  } else {
    256.0
  }
  let sign = (2 * x) & 64
  let frac = Float::from_int((x & 63) - sign) /
    Float::from_int((x & -64) + sign)
  pow43_table[16 + ((x + sign) >> 6)] *
  (1.0 + frac * (4.0 / 3.0 + frac * (2.0 / 9.0))) *
  mult
}

///|
fn spectral_consume(
  bits : BitCursor,
  n : Int,
  limit : Int,
) -> Int raise DecodeError {
  if n > limit - bits.pos {
    raise BitBudget(bits.pos, n, limit)
  }
  bits.read(n)
}

///|
fn spectral_leaf(
  bits : BitCursor,
  table : Int,
  limit : Int,
) -> Int raise DecodeError {
  let base = huffman_index[table]
  let mut width = 5
  let mut leaf = huffman_tabs[base + bits.peek_padded(width)]
  while leaf < 0 {
    let _ = spectral_consume(bits, width, limit)
    width = leaf & 7
    leaf = huffman_tabs[base + bits.peek_padded(width) - (leaf >> 3)]
  }
  let _ = spectral_consume(bits, leaf >> 8, limit)
  leaf
}

///|
fn huffman(
  dst : Array[Float],
  bits : BitCursor,
  gr : GranuleInfo,
  scf : Array[Float],
  granule_limit : Int,
) -> Unit raise DecodeError {
  if dst.length() != 576 ||
    gr.big_values < 0 ||
    gr.big_values > 288 ||
    gr.table_select.length() != 3 ||
    gr.region_count.length() != 3 ||
    gr.table_select.iter().any(fn(x) { x < 0 || x > 31 || x == 4 || x == 14 }) ||
    gr.region_count.iter().any(fn(x) { x < 0 }) ||
    gr.count1_table < 0 ||
    gr.count1_table > 1 {
    raise InvalidSideInfo("invalid Huffman fields")
  }
  if granule_limit < bits.pos ||
    granule_limit > bits.limit ||
    granule_limit > bits.bytes.length() * 8 {
    raise BitBudget(bits.pos, granule_limit - bits.pos, bits.limit)
  }
  let mut band = 0
  let mut region = 0
  let mut remaining = gr.big_values
  let mut out = 0
  let mut one : Float = 0.0
  while remaining > 0 {
    if region >= 3 {
      raise InvalidSideInfo("Huffman regions exhausted")
    }
    let table = gr.table_select[region]
    let linbits = huffman_linbits[table]
    let mut band_count = gr.region_count[region]
    region += 1
    while true {
      if band >= gr.sfbtab.length() ||
        band >= scf.length() ||
        gr.sfbtab[band] <= 0 ||
        (gr.sfbtab[band] & 1) != 0 {
        raise InvalidSideInfo("Huffman scalefactor bands exhausted")
      }
      let np = gr.sfbtab[band] / 2
      let pairs = if remaining < np { remaining } else { np }
      one = scf[band]
      band += 1
      for _pair = 0; _pair < pairs; _pair = _pair + 1 {
        let mut leaf = spectral_leaf(bits, table, granule_limit)
        for _value = 0; _value < 2; _value = _value + 1 {
          let mut magnitude = leaf & 15
          if magnitude == 15 && linbits != 0 {
            magnitude += spectral_consume(bits, linbits, granule_limit)
            let sign = spectral_consume(bits, 1, granule_limit)
            dst[out] = one *
              pow_43(magnitude) *
              (if sign != 0 { -1.0 } else { 1.0 })
          } else {
            let sign = if magnitude != 0 {
              spectral_consume(bits, 1, granule_limit)
            } else {
              bits.peek_padded(1)
            }
            dst[out] = pow43_table[16 + magnitude - 16 * sign] * one
          }
          out += 1
          leaf = leaf >> 4
        }
      }
      remaining -= np
      band_count -= 1
      if remaining <= 0 || band_count < 0 {
        break
      }
    }
  }
  let mut np = 1 - remaining
  let count_table = if gr.count1_table != 0 {
    huffman_count33
  } else {
    huffman_count32
  }
  while out < 576 && bits.pos < granule_limit {
    let mut leaf = count_table[bits.peek_padded(4)]
    if (leaf & 8) == 0 {
      leaf = count_table[(leaf >> 3) +
        (bits.peek_padded(4 + (leaf & 3)) & ((1 << (leaf & 3)) - 1))]
    }
    let code_bits = leaf & 7
    let mut signs = 0
    // The final band may leave only one pair; upstream stops at its sentinel
    // before reading the other pair's signs. Preserve those last two samples.
    let values = if out == 574 { 2 } else { 4 }
    for i = 0; i < values; i = i + 1 {
      if (leaf & (128 >> i)) != 0 {
        signs += 1
      }
    }
    if code_bits + signs > granule_limit - bits.pos {
      break
    }
    let _ = spectral_consume(bits, code_bits, granule_limit)
    for pair = 0; pair < values / 2; pair = pair + 1 {
      np -= 1
      if np == 0 {
        if band >= gr.sfbtab.length() || gr.sfbtab[band] == 0 {
          bits.pos = granule_limit
          return
        }
        if band >= scf.length() {
          raise InvalidSideInfo("count1 scalefactor bands exhausted")
        }
        np = gr.sfbtab[band] / 2
        one = scf[band]
        band += 1
      }
      for j = 0; j < 2; j = j + 1 {
        let i = 2 * pair + j
        if (leaf & (128 >> i)) != 0 {
          dst[out + i] = if spectral_consume(bits, 1, granule_limit) != 0 {
            -one
          } else {
            one
          }
        }
      }
    }
    out += values
  }
  bits.pos = granule_limit
}
