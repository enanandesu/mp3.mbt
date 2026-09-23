// Side information and scalefactor-band widths adapted from minimp3.h,
// commit ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0),
// L3_read_side_info. Unlike the C routine, malformed fields and truncated
// reads raise explicit errors, reserved codebooks/invalid regions are rejected,
// and private bits cannot accidentally enable granule-zero scfsi reuse.
// Unused table/region/subblock slots are deterministically initialized to zero.

///|
pub struct GranuleInfo {
  sfbtab : Array[Int]
  part_23_length : Int
  big_values : Int
  scalefac_compress : Int
  global_gain : Int
  block_type : Int
  mixed_block_flag : Int
  n_long_sfb : Int
  n_short_sfb : Int
  table_select : Array[Int]
  region_count : Array[Int]
  subblock_gain : Array[Int]
  preflag : Int
  scalefac_scale : Int
  count1_table : Int
  scfsi : Int
} derive(Eq, Show)

///|
pub struct SideInfo {
  main_data_begin : Int
  granules : Array[GranuleInfo]
} derive(Eq, Show)

// BEGIN GENERATED SCALEFACTOR BAND WIDTHS

///|
let side_scf_long : Array[Array[Int]] = [
  [
    6, 6, 6, 6, 6, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 38, 46, 52, 60, 68, 58,
    54, 0,
  ],
  [
    12, 12, 12, 12, 12, 12, 16, 20, 24, 28, 32, 40, 48, 56, 64, 76, 90, 2, 2, 2,
    2, 2, 0,
  ],
  [
    6, 6, 6, 6, 6, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 38, 46, 52, 60, 68, 58,
    54, 0,
  ],
  [
    6, 6, 6, 6, 6, 6, 8, 10, 12, 14, 16, 18, 22, 26, 32, 38, 46, 54, 62, 70, 76,
    36, 0,
  ],
  [
    6, 6, 6, 6, 6, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 38, 46, 52, 60, 68, 58,
    54, 0,
  ],
  [
    4, 4, 4, 4, 4, 4, 6, 6, 8, 8, 10, 12, 16, 20, 24, 28, 34, 42, 50, 54, 76, 158,
    0,
  ],
  [
    4, 4, 4, 4, 4, 4, 6, 6, 6, 8, 10, 12, 16, 18, 22, 28, 34, 40, 46, 54, 54, 192,
    0,
  ],
  [
    4, 4, 4, 4, 4, 4, 6, 6, 8, 10, 12, 16, 20, 24, 30, 38, 46, 56, 68, 84, 102, 26,
    0,
  ],
]

///|
let side_scf_short : Array[Array[Int]] = [
  [
    4, 4, 4, 4, 4, 4, 4, 4, 4, 6, 6, 6, 8, 8, 8, 10, 10, 10, 12, 12, 12, 14, 14,
    14, 18, 18, 18, 24, 24, 24, 30, 30, 30, 40, 40, 40, 18, 18, 18, 0,
  ],
  [
    8, 8, 8, 8, 8, 8, 8, 8, 8, 12, 12, 12, 16, 16, 16, 20, 20, 20, 24, 24, 24, 28,
    28, 28, 36, 36, 36, 2, 2, 2, 2, 2, 2, 2, 2, 2, 26, 26, 26, 0,
  ],
  [
    4, 4, 4, 4, 4, 4, 4, 4, 4, 6, 6, 6, 6, 6, 6, 8, 8, 8, 10, 10, 10, 14, 14, 14,
    18, 18, 18, 26, 26, 26, 32, 32, 32, 42, 42, 42, 18, 18, 18, 0,
  ],
  [
    4, 4, 4, 4, 4, 4, 4, 4, 4, 6, 6, 6, 8, 8, 8, 10, 10, 10, 12, 12, 12, 14, 14,
    14, 18, 18, 18, 24, 24, 24, 32, 32, 32, 44, 44, 44, 12, 12, 12, 0,
  ],
  [
    4, 4, 4, 4, 4, 4, 4, 4, 4, 6, 6, 6, 8, 8, 8, 10, 10, 10, 12, 12, 12, 14, 14,
    14, 18, 18, 18, 24, 24, 24, 30, 30, 30, 40, 40, 40, 18, 18, 18, 0,
  ],
  [
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 6, 6, 6, 8, 8, 8, 10, 10, 10, 12, 12, 12,
    14, 14, 14, 18, 18, 18, 22, 22, 22, 30, 30, 30, 56, 56, 56, 0,
  ],
  [
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 6, 6, 6, 6, 6, 6, 10, 10, 10, 12, 12, 12,
    14, 14, 14, 16, 16, 16, 20, 20, 20, 26, 26, 26, 66, 66, 66, 0,
  ],
  [
    4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 6, 6, 6, 8, 8, 8, 12, 12, 12, 16, 16, 16,
    20, 20, 20, 26, 26, 26, 34, 34, 34, 42, 42, 42, 12, 12, 12, 0,
  ],
]

// 8 kHz mixed row is derived from pinned long[:6] + short[9:].
// This fixes upstream's 48/72 start mismatch and 39/36 band mismatch.

///|
let side_scf_mixed : Array[Array[Int]] = [
  [
    6, 6, 6, 6, 6, 6, 6, 6, 6, 8, 8, 8, 10, 10, 10, 12, 12, 12, 14, 14, 14, 18, 18,
    18, 24, 24, 24, 30, 30, 30, 40, 40, 40, 18, 18, 18, 0,
  ],
  [
    12, 12, 12, 12, 12, 12, 12, 12, 12, 16, 16, 16, 20, 20, 20, 24, 24, 24, 28, 28,
    28, 36, 36, 36, 2, 2, 2, 2, 2, 2, 2, 2, 2, 26, 26, 26, 0,
  ],
  [
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 8, 8, 8, 10, 10, 10, 14, 14, 14, 18, 18,
    18, 26, 26, 26, 32, 32, 32, 42, 42, 42, 18, 18, 18, 0,
  ],
  [
    6, 6, 6, 6, 6, 6, 6, 6, 6, 8, 8, 8, 10, 10, 10, 12, 12, 12, 14, 14, 14, 18, 18,
    18, 24, 24, 24, 32, 32, 32, 44, 44, 44, 12, 12, 12, 0,
  ],
  [
    6, 6, 6, 6, 6, 6, 6, 6, 6, 8, 8, 8, 10, 10, 10, 12, 12, 12, 14, 14, 14, 18, 18,
    18, 24, 24, 24, 30, 30, 30, 40, 40, 40, 18, 18, 18, 0,
  ],
  [
    4, 4, 4, 4, 4, 4, 6, 6, 4, 4, 4, 6, 6, 6, 8, 8, 8, 10, 10, 10, 12, 12, 12, 14,
    14, 14, 18, 18, 18, 22, 22, 22, 30, 30, 30, 56, 56, 56, 0,
  ],
  [
    4, 4, 4, 4, 4, 4, 6, 6, 4, 4, 4, 6, 6, 6, 6, 6, 6, 10, 10, 10, 12, 12, 12, 14,
    14, 14, 16, 16, 16, 20, 20, 20, 26, 26, 26, 66, 66, 66, 0,
  ],
  [
    4, 4, 4, 4, 4, 4, 6, 6, 4, 4, 4, 6, 6, 6, 8, 8, 8, 12, 12, 12, 16, 16, 16, 20,
    20, 20, 26, 26, 26, 34, 34, 34, 42, 42, 42, 12, 12, 12, 0,
  ],
]
// END GENERATED SCALEFACTOR BAND WIDTHS

///|
/// Read a complete MPEG-1/2/2.5 Layer III frame. The two CRC bytes, when present,
/// are skipped; CRC checksum verification is not implemented here.
pub fn read_side_info(
  frame : Bytes,
  header : @header.Header,
  free_format_size? : Int,
) -> SideInfo raise DecodeError {
  let mpeg1 = header.version == @header.Mpeg1
  match @header.parse(frame) {
    Ok(parsed) if parsed == header => ()
    _ => raise InvalidFrame("frame header differs from parsed header")
  }
  match header.frame_bytes(free_format_size?) {
    Ok(Some(size)) =>
      if frame.length() != size {
        raise InvalidFrame("frame length differs from header")
      }
    Ok(None) => ()
    Err(_) => raise InvalidFrame("invalid frame length")
  }
  let data_offset = header.main_data_offset()
  if frame.length() < data_offset {
    raise InvalidFrame("truncated side information")
  }
  let bits = BitCursor::new(frame, limit=data_offset * 8)
  bits.skip((4 + header.crc_bytes()) * 8)
  let main_data_begin = bits.read(if mpeg1 { 9 } else { 8 })
  let channels = header.channels()
  bits.skip(if mpeg1 { if channels == 1 { 5 } else { 3 } } else { channels })
  let reuse = Array::make(channels, 0)
  if mpeg1 {
    for ch = 0; ch < channels; ch = ch + 1 {
      reuse[ch] = bits.read(4)
    }
  }
  let rate = match header.sample_rate_hz {
    11025 | 12000 => 0
    8000 => 1
    22050 => 2
    24000 => 3
    16000 => 4
    44100 => 5
    48000 => 6
    32000 => 7
    _ =>
      raise InvalidSideInfo(
        if mpeg1 {
          "unsupported MPEG-1 sample rate"
        } else {
          "unsupported sample rate"
        },
      )
  }
  let granules : Array[GranuleInfo] = []
  let mut total_bits = 0
  let granule_count = if mpeg1 { 2 } else { 1 }
  for index = 0; index < channels * granule_count; index = index + 1 {
    let ch = index % channels
    let part_23_length = bits.read(12)
    total_bits += part_23_length
    let big_values = bits.read(9)
    if big_values > 288 {
      raise InvalidSideInfo("big_values exceeds 288")
    }
    let global_gain = bits.read(8)
    let scalefac_compress = bits.read(if mpeg1 { 4 } else { 9 })
    let mut sfbtab = side_scf_long[rate]
    let mut n_long_sfb = 22
    let mut n_short_sfb = 0
    let mut block_type = 0
    let mut mixed_block_flag = 0
    let table_select = [0, 0, 0]
    let region_count = [0, 0, 0]
    let subblock_gain = [0, 0, 0]
    if bits.read(1) != 0 {
      block_type = bits.read(2)
      if block_type == 0 {
        raise InvalidSideInfo("switched block_type is zero")
      }
      mixed_block_flag = bits.read(1)
      region_count[0] = 7
      region_count[1] = 255
      if block_type == 2 {
        reuse[ch] = 0
        if mixed_block_flag == 0 {
          region_count[0] = 8
          sfbtab = side_scf_short[rate]
          n_long_sfb = 0
          n_short_sfb = 39
        } else {
          sfbtab = side_scf_mixed[rate]
          n_long_sfb = if mpeg1 { 8 } else { 6 }
          n_short_sfb = 30
        }
      }
      table_select[0] = bits.read(5)
      table_select[1] = bits.read(5)
      for win = 0; win < 3; win = win + 1 {
        subblock_gain[win] = bits.read(3)
      }
    } else {
      for region = 0; region < 3; region = region + 1 {
        table_select[region] = bits.read(5)
      }
      region_count[0] = bits.read(4)
      region_count[1] = bits.read(3)
      region_count[2] = 255
      if region_count[0] + region_count[1] > 20 {
        raise InvalidSideInfo("long block regions exceed 22 bands")
      }
    }
    for table in table_select {
      if table == 4 || table == 14 {
        raise InvalidSideInfo("reserved Huffman codebook")
      }
    }
    let preflag = if mpeg1 {
      bits.read(1)
    } else if scalefac_compress >= 500 {
      1
    } else {
      0
    }
    let scalefac_scale = bits.read(1)
    let count1_table = bits.read(1)
    granules.push({
      sfbtab,
      part_23_length,
      big_values,
      scalefac_compress,
      global_gain,
      block_type,
      mixed_block_flag,
      n_long_sfb,
      n_short_sfb,
      table_select,
      region_count,
      subblock_gain,
      preflag,
      scalefac_scale,
      count1_table,
      scfsi: if index < channels {
        0
      } else {
        reuse[ch]
      },
    })
  }
  let available = (frame.length() - data_offset).to_int64() * 8L +
    main_data_begin.to_int64() * 8L
  if total_bits.to_int64() > available {
    raise BitBudget(data_offset * 8, total_bits, available.to_int())
  }
  { main_data_begin, granules }
}
