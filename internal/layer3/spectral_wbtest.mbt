///|
fn spectral_test_gr() -> GranuleInfo {
  {
    sfbtab: [4, 6, 8, 6, 138, 138, 138, 138, 0],
    part_23_length: 0,
    big_values: 0,
    scalefac_compress: 0,
    global_gain: 210,
    block_type: 0,
    mixed_block_flag: 0,
    n_long_sfb: 22,
    n_short_sfb: 0,
    table_select: [0, 0, 0],
    region_count: [0, 1, 255],
    subblock_gain: [1, 3, 7],
    preflag: 0,
    scalefac_scale: 0,
    count1_table: 0,
    scfsi: 0,
  }
}

///|
test "288 scalar C scalefactor cases cover all MPEG1 compression and scfsi groups" {
  assert_eq(spectral_scalefactor_vectors.length(), 288)
  for row in spectral_scalefactor_vectors {
    let gr = {
      ..spectral_test_gr(),
      n_long_sfb: if row[1] == 0 {
        22
      } else if row[1] == 1 {
        0
      } else {
        8
      },
      n_short_sfb: if row[1] == 0 {
        0
      } else if row[1] == 1 {
        39
      } else {
        30
      },
      scalefac_compress: row[2],
      scfsi: row[3],
      global_gain: row[4],
      scalefac_scale: row[5],
      preflag: row[6],
    }
    let header = @header.parse(
      Bytes::from_array([255, 251, 144, if row[7] == 1 { 0x60 } else { 0 }]),
    ).unwrap()
    let data = Bytes::from_array(
      Array::makei(128, fn(i) { ((i * 73 + row[0] * 19 + 23) & 255).to_byte() }),
    )
    let bits = BitCursor::new(data)
    let ist = Array::makei(40, fn(i) { i % 7 })
    let scales = decode_scalefactors(header, ist, bits, gr, row[8])
    assert_eq(bits.pos, row[9])
    for i = 0; i < 40; i = i + 1 {
      assert_eq(ist[i], row[10 + i])
    }
    for i = 0; i < scales.length(); i = i + 1 {
      assert_eq(scales[i].reinterpret_as_int(), row[50 + i])
    }
  }
}

///|
test "129 C Huffman cases cover every legal tree leaf linbits count1 and band regions" {
  assert_eq(spectral_huffman_inputs.length(), 129)
  for case = 0; case < spectral_huffman_inputs.length(); case = case + 1 {
    let row = spectral_huffman_inputs[case]
    let expected = spectral_huffman_expected[case]
    let gr = {
      ..spectral_test_gr(),
      table_select: [row[0], row[0], row[0]],
      big_values: row[1],
      count1_table: row[2],
    }
    let data = Bytes::from_array(
      Array::makei(row.length() - 4, fn(i) { row[i + 4].to_byte() }),
    )
    let bits = BitCursor::new(data, limit=row[3])
    let output : Array[Float] = Array::make(576, 0.0)
    huffman(
      output,
      bits,
      gr,
      [0.03125, 0.75, 2.0, 5.0, 1.0, 1.0, 1.0, 1.0],
      row[3],
    )
    assert_eq(bits.pos, expected[0])
    for i = 0; i < 576; i = i + 1 {
      assert_eq(
        output[i].reinterpret_as_int(),
        if i + 1 < expected.length() {
          expected[i + 1]
        } else {
          0
        },
      )
    }
  }
}

///|
test "pow43 C oracle preserves Float arithmetic at approximation boundaries" {
  for row in spectral_power_vectors {
    let (value, expected) = row
    assert_eq(pow_43(value).reinterpret_as_int(), expected)
  }
}

///|
test "count1 discards incomplete codewords and signs without reading following granules" {
  let gr = { ..spectral_test_gr(), count1_table: 1 }
  // Table 33 code 0000 denotes four ones, requiring four following signs.
  for limit = 0; limit < 8; limit = limit + 1 {
    for suffix in [0x00, 0xff] {
      let bits = BitCursor::new(Bytes::from_array([0x00, suffix.to_byte()]))
      let output : Array[Float] = Array::make(576, 0.0)
      huffman(output, bits, gr, [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0], limit)
      assert_eq(bits.pos, limit)
      assert_true(output.iter().all(fn(x) { x == 0.0 }))
    }
  }
  let bits = BitCursor::new(b"\x05", limit=8)
  let output : Array[Float] = Array::make(576, 0.0)
  huffman(output, bits, gr, [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0], 8)
  assert_eq(output[0], 1.0)
  assert_eq(output[1], -1.0)
  assert_eq(output[2], 1.0)
  assert_eq(output[3], -1.0)
}

///|
test "Huffman rejects truncated big-value signs and granule limits beyond input" {
  let gr = { ..spectral_test_gr(), big_values: 1, table_select: [1, 1, 1] }
  let bits = BitCursor::new(b"\x00", limit=3)
  let output : Array[Float] = Array::make(576, 0.0)
  try huffman(output, bits, gr, [1.0], 3) catch {
    BitBudget(_, _, _) => ()
    _ => fail("unexpected decode error")
  } noraise {
    _ => fail("expected a bounded big-value decode failure")
  }
  let empty = BitCursor::new(b"")
  try huffman(output, empty, spectral_test_gr(), [1.0], 1) catch {
    BitBudget(_, _, _) => ()
    _ => fail("unexpected decode error")
  } noraise {
    _ => fail("expected invalid granule extent")
  }
}

///|
test "scalefactors reject missing bits in MPEG1 and MPEG2" {
  let gr = { ..spectral_test_gr(), scalefac_compress: 15 }
  let ist = Array::make(40, 0)
  let header = @header.parse(b"\xff\xfb\x90\x00").unwrap()
  try decode_scalefactors(header, ist, BitCursor::new(b""), gr, 0) catch {
    BitBudget(_, _, _) => ()
    _ => fail("unexpected decode error")
  } noraise {
    _ => fail("expected bounded scalefactor failure")
  }
  let header2 = @header.parse(b"\xff\xf3\x90\x00").unwrap()
  try decode_scalefactors(header2, ist, BitCursor::new(b""), gr, 0) catch {
    BitBudget(_, _, _) => ()
    _ => fail("unexpected decode error")
  } noraise {
    _ => fail("expected bounded MPEG2 scalefactor failure")
  }
}
