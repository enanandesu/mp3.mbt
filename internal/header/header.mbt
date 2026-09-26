// Layer III header arithmetic is derived from minimp3.h at
// ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0): hdr_valid,
// hdr_compare, hdr_bitrate_kbps, hdr_sample_rate_hz, hdr_frame_samples,
// hdr_frame_bytes, hdr_padding, and HDR_* macros. See README.md for differences.

///|
pub(all) enum Version {
  Mpeg1
  Mpeg2
  Mpeg25
} derive(Eq, Show, Debug)

///|
pub(all) enum ChannelMode {
  Stereo
  JointStereo
  DualChannel
  Mono
} derive(Eq, Show, Debug)

///|
pub(all) enum Emphasis {
  NoEmphasis
  FiftyFifteen
  CcitJ17
  ReservedValue
} derive(Eq, Show, Debug)

///|
pub(all) enum HeaderError {
  InvalidOffset(Int)
  Truncated(available~ : Int)
  InvalidSync
  ReservedVersion
  ReservedLayer
  UnsupportedLayer(Int)
  InvalidBitrateIndex
  InvalidSampleRateIndex
  ReservedEmphasis
  InvalidFreeFormatSize(Int)
} derive(Eq, Show, Debug)

///|
/// A validated four-byte Layer III header. This does not validate frame payload.
pub struct Header {
  version : Version
  bitrate_kbps : Int?
  sample_rate_hz : Int
  padding : Bool
  crc_protected : Bool
  channel_mode : ChannelMode
  mode_extension : Int
  private_bit : Bool
  copyright : Bool
  original : Bool
  emphasis : Emphasis
} derive(Eq, Show, Debug)

///|
/// Parse one header at the given offset, without scanning or reading payload.
/// Truncated reports bytes actually available (0..3); invalid offsets are separate.
pub fn parse(
  data : Bytes,
  offset? : Int = 0,
  allow_reserved_emphasis? : Bool = false,
) -> Result[Header, HeaderError] {
  if offset < 0 || offset > data.length() {
    return Err(InvalidOffset(offset))
  }
  let available = data.length() - offset
  if available < 4 {
    return Err(Truncated(available~))
  }
  let b0 = data[offset].to_int()
  let b1 = data[offset + 1].to_int()
  let b2 = data[offset + 2].to_int()
  let b3 = data[offset + 3].to_int()
  if b0 != 0xff || (b1 & 0xe0) != 0xe0 {
    return Err(InvalidSync)
  }
  let version = match (b1 >> 3) & 3 {
    3 => Mpeg1
    2 => Mpeg2
    0 => Mpeg25
    _ => return Err(ReservedVersion)
  }
  match (b1 >> 1) & 3 {
    0 => return Err(ReservedLayer)
    1 => ()
    bits => return Err(UnsupportedLayer(4 - bits))
  }
  let bitrate_index = b2 >> 4
  if bitrate_index == 15 {
    return Err(InvalidBitrateIndex)
  }
  let sample_rate_index = (b2 >> 2) & 3
  if sample_rate_index == 3 {
    return Err(InvalidSampleRateIndex)
  }
  let emphasis = match b3 & 3 {
    0 => NoEmphasis
    1 => FiftyFifteen
    3 => CcitJ17
    _ =>
      if allow_reserved_emphasis {
        ReservedValue
      } else {
        return Err(ReservedEmphasis)
      }
  }
  // minimp3 halfrate[is_mpeg1][0], multiplied by two, Layer III only.
  let rates = if version == Mpeg1 {
    [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
  } else {
    [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
  }
  let rate_divisor = match version {
    Mpeg1 => 1
    Mpeg2 => 2
    Mpeg25 => 4
  }
  let sample_rate_hz = [44100, 48000, 32000][sample_rate_index] / rate_divisor
  let bitrate_kbps = if bitrate_index == 0 {
    None
  } else {
    Some(rates[bitrate_index])
  }
  let channel_mode = match b3 >> 6 {
    0 => Stereo
    1 => JointStereo
    2 => DualChannel
    _ => Mono
  }
  Ok({
    version,
    bitrate_kbps,
    sample_rate_hz,
    padding: (b2 & 2) != 0,
    crc_protected: (b1 & 1) == 0,
    channel_mode,
    mode_extension: (b3 >> 4) & 3,
    private_bit: (b2 & 1) != 0,
    copyright: (b3 & 8) != 0,
    original: (b3 & 4) != 0,
    emphasis,
  })
}

///|
pub fn Header::channels(self : Header) -> Int {
  if self.channel_mode == Mono {
    1
  } else {
    2
  }
}

///|
pub fn Header::samples_per_frame(self : Header) -> Int {
  if self.version == Mpeg1 {
    1152
  } else {
    576
  }
}

///|
/// Side-info bit count follows the fields consumed by L3_read_side_info.
/// This size excludes the four-byte header and optional two-byte CRC.
pub fn Header::side_info_bytes(self : Header) -> Int {
  match (self.version, self.channels()) {
    (Mpeg1, 1) => 17
    (Mpeg1, _) => 32
    (_, 1) => 9
    (_, _) => 17
  }
}

///|
pub fn Header::crc_bytes(self : Header) -> Int {
  if self.crc_protected {
    2
  } else {
    0
  }
}

///|
/// Offset of main data relative to the frame start. CRC is skipped, not checked.
pub fn Header::main_data_offset(self : Header) -> Int {
  4 + self.crc_bytes() + self.side_info_bytes()
}

///|
/// Total frame length, including header, optional CRC, side info and padding.
/// Free-format returns Ok(None) until its UNPADDED total frame length is known.
/// This function does not discover that length, impose a search limit, or infer
/// a bitrate. A supplied free-format size must fit its overhead and Int + padding.
pub fn Header::frame_bytes(
  self : Header,
  free_format_size? : Int,
) -> Result[Int?, HeaderError] {
  let padding = if self.padding { 1 } else { 0 }
  match self.bitrate_kbps {
    Some(kbps) =>
      Ok(
        Some(
          self.samples_per_frame() * kbps * 125 / self.sample_rate_hz + padding,
        ),
      )
    None =>
      match free_format_size {
        None => Ok(None)
        Some(size) => {
          if size < self.main_data_offset() - padding ||
            size > 2147483647 - padding {
            return Err(InvalidFreeFormatSize(size))
          }
          Ok(Some(size + padding))
        }
      }
  }
}

///|
pub fn Header::mid_side_stereo(self : Header) -> Bool {
  self.channel_mode == JointStereo && (self.mode_extension & 2) != 0
}

///|
pub fn Header::intensity_stereo(self : Header) -> Bool {
  self.channel_mode == JointStereo && (self.mode_extension & 1) != 0
}

///|
/// The same matching fields as hdr_compare on already validated Layer III
/// headers. Bitrate changes, padding, CRC, emphasis and channel modes may vary.
pub fn Header::sync_compatible(self : Header, other : Header) -> Bool {
  self.version == other.version &&
  self.sample_rate_hz == other.sample_rate_hz &&
  (self.bitrate_kbps is None) == (other.bitrate_kbps is None)
}

///|
/// Project stream policy additionally forbids channel-count changes. Switching
/// Stereo / JointStereo / DualChannel keeps two channels and remains compatible.
pub fn Header::stream_compatible(self : Header, other : Header) -> Bool {
  self.sync_compatible(other) && self.channels() == other.channels()
}
