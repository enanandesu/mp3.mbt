///|
fn side_flatten(g : GranuleInfo) -> Array[Int] {
  let values = [
    g.part_23_length,
    g.big_values,
    g.scalefac_compress,
    g.global_gain,
    g.block_type,
    g.mixed_block_flag,
    g.n_long_sfb,
    g.n_short_sfb,
    g.preflag,
    g.scalefac_scale,
    g.count1_table,
    g.scfsi,
  ]
  for value in g.table_select {
    values.push(value)
  }
  for value in g.region_count {
    values.push(value)
  }
  for value in g.subblock_gain {
    values.push(value)
  }
  for i = 0; i <= g.n_long_sfb + g.n_short_sfb; i = i + 1 {
    values.push(g.sfbtab[i])
  }
  values
}

///|
fn side_frame(channels : Int, crc? : Bool = false, rate? : Int = 0) -> Bytes {
  let size = 144000 * 128 / [44100, 48000, 32000][rate]
  Bytes::makei(size, fn(i) {
    match i {
      0 => 255
      1 => if crc { 250 } else { 251 }
      2 => (144 | (rate << 2)).to_byte()
      3 => if channels == 1 { 192 } else { 0 }
      _ => 0
    }
  })
}

///|
fn side_patch(frame : Bytes, position : Int, width : Int, value : Int) -> Bytes {
  Bytes::makei(frame.length(), fn(i) {
    let mut byte = frame[i].to_int()
    for bit = 0; bit < width; bit = bit + 1 {
      let pos = position + bit
      if pos / 8 == i {
        let mask = 1 << (7 - pos % 8)
        byte = (byte & (255 ^ mask)) |
          (((value >> (width - 1 - bit)) & 1) << (7 - pos % 8))
      }
    }
    byte.to_byte()
  })
}

///|
fn side_parse(frame : Bytes) -> SideInfo raise DecodeError {
  read_side_info(frame, @header.parse(frame).unwrap())
}

///|
test "side-info MPEG1 rates channels CRC and band tables" {
  for channels in [1, 2] {
    for crc in [false, true] {
      for rate in [0, 1, 2] {
        let frame = side_frame(channels, crc~, rate~)
        let side = side_parse(frame)
        assert_eq(side.main_data_begin, 0)
        assert_eq(side.granules.length(), channels * 2)
        assert_eq(side.granules[0].n_long_sfb, 22)
        let start = (4 + (if crc { 2 } else { 0 })) * 8 +
          (if channels == 1 { 18 } else { 20 })
        for mixed in [0, 1] {
          let short_frame = side_patch(
            side_patch(side_patch(frame, start + 33, 1, 1), start + 34, 2, 2),
            start + 36,
            1,
            mixed,
          )
          let g = side_parse(short_frame).granules[0]
          assert_eq(g.block_type, 2)
          assert_eq(g.n_long_sfb, if mixed == 0 { 0 } else { 8 })
          assert_eq(g.n_short_sfb, if mixed == 0 { 39 } else { 30 })
          let mut sum = 0
          for width in g.sfbtab {
            sum += width
          }
          assert_eq(sum, 576)
          assert_eq(g.sfbtab[g.n_long_sfb + g.n_short_sfb], 0)
        }
      }
    }
  }
}

///|
test "scfsi belongs to second granule and short blocks clear channel reuse" {
  let frame = side_patch(
    side_patch(side_patch(side_frame(2), 41, 3, 7), 44, 4, 15),
    48,
    4,
    9,
  )
  let side = side_parse(frame)
  assert_eq(side.granules[0].scfsi, 0)
  assert_eq(side.granules[1].scfsi, 0)
  assert_eq(side.granules[2].scfsi, 15)
  assert_eq(side.granules[3].scfsi, 9)
  // A first-granule short block invalidates the stored factors for its channel.
  let short = side_patch(side_patch(frame, 52 + 33, 1, 1), 52 + 34, 2, 2)
  let side = side_parse(short)
  assert_eq(side.granules[2].scfsi, 0)
  assert_eq(side.granules[3].scfsi, 9)
  // A second-granule short block also ignores all reuse flags for itself.
  let short = side_patch(
    side_patch(frame, 52 + 59 * 3 + 33, 1, 1),
    52 + 59 * 3 + 34,
    2,
    2,
  )
  assert_eq(side_parse(short).granules[3].scfsi, 0)
  let mono = side_patch(side_patch(side_frame(1), 41, 5, 31), 46, 4, 10)
  assert_eq(side_parse(mono).granules[0].scfsi, 0)
  assert_eq(side_parse(mono).granules[1].scfsi, 10)
}

///|
test "side-info invalid fields and total main-data budget are explicit errors" {
  let frame = side_frame(2)
  for value in [289, 511] {
    assert_eq(
      try? side_parse(side_patch(frame, 52 + 12, 9, value)),
      Err(InvalidSideInfo("big_values exceeds 288")),
    )
  }
  assert_eq(
    try? side_parse(side_patch(frame, 52 + 33, 1, 1)),
    Err(InvalidSideInfo("switched block_type is zero")),
  )
  for table in [4, 14] {
    assert_eq(
      try? side_parse(side_patch(frame, 52 + 34, 5, table)),
      Err(InvalidSideInfo("reserved Huffman codebook")),
    )
  }
  let regions = side_patch(side_patch(frame, 52 + 49, 4, 15), 52 + 53, 3, 7)
  assert_eq(
    try? side_parse(regions),
    Err(InvalidSideInfo("long block regions exceed 22 bands")),
  )
  let exhausted = side_patch(frame, 52, 12, 4095)
  assert_eq(try? side_parse(exhausted), Err(BitBudget(288, 4095, 3048)))
  // The same bit length is legal once enough preceding bytes are declared;
  // reservoir availability is checked separately by Reservoir::restore.
  assert_eq(side_parse(side_patch(exhausted, 32, 9, 511)).main_data_begin, 511)
  let boundary = side_patch(frame, 52, 12, 3048)
  assert_eq(side_parse(boundary).granules[0].part_23_length, 3048)
  assert_eq(
    try? side_parse(side_patch(boundary, 52 + 59, 12, 1)),
    Err(BitBudget(288, 3049, 3048)),
  )
}

///|
test "complete frame header agreement and version-length mismatch" {
  let frame = side_frame(2)
  let header = @header.parse(frame).unwrap()
  for length in [0, 3, 4, 35, 416] {
    let truncated = Bytes::makei(length, fn(i) { frame[i] })
    assert_true((try? read_side_info(truncated, header)) is Err(_))
  }
  assert_eq(
    try? read_side_info(frame, @header.parse(side_frame(1)).unwrap()),
    Err(InvalidFrame("frame header differs from parsed header")),
  )
  let mpeg2 = side_patch(frame, 8, 8, 243)
  assert_eq(
    try? side_parse(mpeg2),
    Err(InvalidFrame("frame length differs from header")),
  )
}
