// Reproducible inputs for low_version_oracle.c. Expected values come from the
// unmodified scalar C functions, including all LSF compression partitions.

///|
fn version_put(
  bytes : Array[Byte],
  position : Ref[Int],
  width : Int,
  value : Int,
) -> Unit {
  for i = width - 1; i >= 0; i = i - 1 {
    let at = position.val
    bytes[at / 8] = (bytes[at / 8].to_int() |
    (((value >> i) & 1) << (7 - (at & 7)))).to_byte()
    position.val += 1
  }
}

///|
fn version_frame(
  rate : Int,
  layout : Int,
  channels : Int,
  crc : Int,
  mode : Int,
) -> Bytes {
  let header_bytes : Array[Byte] = [
    255,
    ([227, 243, 251][rate / 3] - crc).to_byte(),
    (0x90 | (rate % 3 * 4)).to_byte(),
    (if channels == 1 { 0xc0 } else { 0x40 | (mode * 16) }).to_byte(),
  ]
  let header = @header.parse(Bytes::from_array(header_bytes)).unwrap()
  let size = header.frame_bytes().unwrap().unwrap()
  let bytes : Array[Byte] = Array::makei(size, fn(i) {
    if i < 4 {
      header_bytes[i]
    } else {
      0
    }
  })
  let mpeg1 = rate >= 6
  let position = Ref::new(32 + crc * 16)
  version_put(bytes, position, if mpeg1 { 9 } else { 8 }, 0)
  version_put(
    bytes,
    position,
    if mpeg1 {
      if channels == 1 {
        5
      } else {
        3
      }
    } else {
      channels
    },
    0,
  )
  if mpeg1 {
    for _ch = 0; _ch < channels; _ch = _ch + 1 {
      version_put(bytes, position, 4, 0)
    }
  }
  for g = 0; g < channels * (if mpeg1 { 2 } else { 1 }); g = g + 1 {
    let block = if layout == 4 { 2 } else { layout }
    version_put(bytes, position, 12, 0)
    version_put(bytes, position, 9, 0)
    version_put(bytes, position, 8, 180 + g)
    version_put(
      bytes,
      position,
      if mpeg1 {
        4
      } else {
        9
      },
      if mpeg1 {
        15
      } else {
        500 + g
      },
    )
    version_put(bytes, position, 1, if block != 0 { 1 } else { 0 })
    if block != 0 {
      version_put(bytes, position, 2, block)
      version_put(bytes, position, 1, if layout == 4 { 1 } else { 0 })
      version_put(bytes, position, 5, 1)
      version_put(bytes, position, 5, 31)
      for value in [1, 3, 7] {
        version_put(bytes, position, 3, value)
      }
    } else {
      for value in [1, 16, 31] {
        version_put(bytes, position, 5, value)
      }
      version_put(bytes, position, 4, 5)
      version_put(bytes, position, 3, 6)
    }
    if mpeg1 {
      version_put(bytes, position, 1, 1)
    }
    version_put(bytes, position, 1, g & 1)
    version_put(bytes, position, 1, 1)
  }
  Bytes::from_array(bytes)
}

///|
fn version_float_hash(values : Array[Float]) -> UInt {
  let mut hash = 2166136261U
  for value in values {
    hash = (hash ^ value.reinterpret_as_uint()) * 16777619U
  }
  hash
}

///|
fn version_position_hash(values : Array[Int]) -> UInt {
  let mut hash = 2166136261U
  for value in values {
    hash = (hash ^ value.reinterpret_as_uint()) * 16777619U
  }
  hash
}

///|
test "3072 C LSF scalefactor cases exhaust all compressions partitions and intensity sentinels" {
  assert_eq(lsf_scalefactor_vectors.length(), 3072)
  for row in lsf_scalefactor_vectors {
    let id = row[0].reinterpret_as_int()
    let layout = row[1].reinterpret_as_int()
    let intensity = row[2].reinterpret_as_int()
    let compress = row[3].reinterpret_as_int()
    let gr = {
      ..spectral_test_gr(),
      n_long_sfb: if layout == 0 {
        22
      } else if layout == 1 {
        0
      } else {
        6
      },
      n_short_sfb: if layout == 0 {
        0
      } else if layout == 1 {
        39
      } else {
        30
      },
      scalefac_compress: compress,
      global_gain: id * 29 % 256,
      scalefac_scale: id & 1,
      preflag: if compress >= 500 {
        1
      } else {
        0
      },
    }
    let header = @header.parse(
      Bytes::from_array([
        255,
        row[4].to_byte(),
        144,
        if intensity != 0 {
          0x70
        } else {
          0
        },
      ]),
    ).unwrap()
    let data = Bytes::makei(128, fn(i) {
      ((i * 73 + id * 19 + 23) & 255).to_byte()
    })
    let bits = BitCursor::new(data)
    let positions = Array::makei(40, fn(i) { i % 7 })
    let scales = decode_scalefactors(header, positions, bits, gr, intensity)
    assert_eq(
      bits.pos.reinterpret_as_uint(),
      row[5],
      msg="LSF bit count case \{id}",
    )
    assert_eq(
      version_position_hash(positions),
      row[6],
      msg="LSF positions case \{id}",
    )
    assert_eq(version_float_hash(scales), row[7], msg="LSF f32 case \{id}")
  }
}

///|
test "180 C side-info cases cover nine rates five block layouts mono stereo and CRC" {
  assert_eq(version_side_vectors.length(), 180)
  for row in version_side_vectors {
    let frame = version_frame(
      row[0].reinterpret_as_int(),
      row[1].reinterpret_as_int(),
      row[2].reinterpret_as_int(),
      row[3].reinterpret_as_int(),
      0,
    )
    assert_eq(frame.length().reinterpret_as_uint(), row[4])
    let side = read_side_info(frame, @header.parse(frame).unwrap())
    let expected_count = row[2].reinterpret_as_int() *
      (if row[0] >= 6U { 2 } else { 1 })
    assert_eq(side.granules.length(), expected_count)
    let mut offset = 5
    for gr in side.granules {
      for value in side_flatten(gr) {
        assert_eq(value.reinterpret_as_uint(), row[offset])
        offset += 1
      }
    }
    assert_eq(offset, row.length())
  }
}

///|
test "360 C DSP cases cover LSF intensity both compress parities and 8000Hz mixed blocks" {
  assert_eq(version_transform_vectors.length(), 360)
  for row in version_transform_vectors {
    let id = row[0].reinterpret_as_int()
    let rate = row[1].reinterpret_as_int()
    let frame = version_frame(
      rate,
      row[2].reinterpret_as_int(),
      2,
      0,
      row[3].reinterpret_as_int(),
    )
    let header = @header.parse(frame).unwrap()
    let side = read_side_info(frame, header)
    let samples : Array[Float] = Array::makei(1152, fn(i) {
      Float::from_int((i * 29 + id * 13) % 257 - 128) / 1024.0
    })
    for i = 128 + id % 200; i < 576; i = i + 1 {
      samples[576 + i] = 0.0
    }
    let positions = Array::makei(39, fn(i) {
      if i % 11 == 0 {
        255
      } else {
        (i * 3 + id) % (if rate >= 6 { 9 } else { 64 })
      }
    })
    let overlap : Array[Array[Float]] = Array::makei(2, fn(ch) {
      Array::makei(288, fn(i) { Float::from_int((i + ch) % 17 - 8) / 8192.0 })
    })
    stereo(
      samples,
      positions,
      side.granules[0],
      header,
      right_compress=row[4].reinterpret_as_int(),
    )
    assert_eq(version_float_hash(samples), row[5], msg="stereo case \{id}")
    assert_eq(
      version_position_hash(positions),
      row[6],
      msg="stereo positions case \{id}",
    )
    for ch = 0; ch < 2; ch = ch + 1 {
      hybrid(
        samples,
        ch * 576,
        overlap[ch],
        side.granules[ch],
        sample_rate_hz=header.sample_rate_hz,
      )
    }
    assert_eq(version_float_hash(samples), row[7], msg="hybrid case \{id}")
    let combined = overlap[0].copy()
    for value in overlap[1] {
      combined.push(value)
    }
    assert_eq(version_float_hash(combined), row[8], msg="overlap case \{id}")
  }
}

///|
test "all versions decode correct granule counts and support explicit bounded free-format sizes" {
  for rate = 0; rate < 9; rate = rate + 1 {
    for channels in [1, 2] {
      let source = version_frame(rate, 0, channels, 0, 0)
      let silent = Bytes::makei(source.length(), fn(i) {
        if i < 4 {
          source[i]
        } else {
          0
        }
      })
      let expected_length = (if rate >= 6 { 1152 } else { 576 }) * channels
      let decoder = FrameDecoder::new()
      for _frame = 0; _frame < 3; _frame = _frame + 1 {
        let pcm = decoder.decode_frame(silent)
        assert_eq(pcm.length(), expected_length)
        assert_true(pcm.iter().all(fn(x) { x == 0.0 }))
      }
      let free = Bytes::makei(silent.length(), fn(i) {
        if i == 2 {
          (silent[i].to_int() & 15).to_byte()
        } else {
          silent[i]
        }
      })
      let output = FrameDecoder::new().decode_frame(
        free,
        free_format_size=free.length(),
      )
      assert_eq(output.length(), expected_length)
      assert_true(output.iter().all(fn(x) { x == 0.0 }))
      for size in [0, 2305, free.length() + 1] {
        assert_true(
          (try? FrameDecoder::new().decode_frame(free, free_format_size=size))
          is Err(_),
        )
      }
    }
  }
}

///|
test "explicit free-format accepts padded minimum overhead and maximum base" {
  for version in [226, 242, 250] {
    let prefix = Bytes::from_array([255, version.to_byte(), 2, 0])
    let header = @header.parse(prefix).unwrap()
    for base in [header.main_data_offset() - 1, 2304] {
      let frame = Bytes::makei(base + 1, fn(i) {
        if i < 4 {
          prefix[i]
        } else {
          0
        }
      })
      let pcm = FrameDecoder::new().decode_frame(frame, free_format_size=base)
      assert_eq(pcm.length(), header.samples_per_frame() * 2)
      assert_true(pcm.iter().all(fn(x) { x == 0.0 }))
    }
  }
}
