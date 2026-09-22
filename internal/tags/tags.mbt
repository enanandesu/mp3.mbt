// Boundary-skipping logic based on minimp3_ex.h, mp3dec_skip_id3v1 and
// mp3dec_skip_id3v2, commit ea99364f61c14656440e8d77e9c233ccf3124633.
// The upstream license is preserved in third_party/minimp3/LICENSE.
// Unlike the C helper, this package validates version-specific flags, checks
// footers and limits, and reports incomplete input instead of clamping to EOF.

///|
/// Outer ID3v2 boundaries only. Metadata and extended headers are not parsed.
pub(all) struct Id3v2 {
  version : Int
  revision : Int
  flags : Int
  payload_bytes : Int
  total_bytes : Int
} derive(Eq, Show)

///|
pub(all) enum TagError {
  InvalidLimit
  UnsupportedVersion(Int)
  InvalidRevision(Int)
  InvalidFlags(Int)
  InvalidSynchsafeSize
  TooLarge(Int)
  Truncated(Int, Int)
  InvalidFooter
} derive(Eq, Show)

///|
/// NeedMoreInput carries the minimum total buffer length, not a byte delta.
/// Truncated carries the required and available lengths. No input is consumed
/// until Tag is returned, so retrying a partial prefix is side-effect free.
pub(all) enum PrefixResult {
  NotATag
  NeedMoreInput(Int)
  Invalid(TagError)
  Tag(Id3v2)
} derive(Eq, Show)

///|
fn incomplete(required : Int, available : Int, eof : Bool) -> PrefixResult {
  if eof {
    Invalid(Truncated(required, available))
  } else {
    NeedMoreInput(required)
  }
}

///|
/// Inspect a leading ID3v2.2, v2.3 or v2.4 tag. max_tag_bytes includes the
/// ten-byte header and optional ten-byte v2.4 footer. A negative limit is an
/// InvalidLimit; zero permits only inputs without a leading tag.
///
/// A nonempty partial "ID3" signature is incomplete, while an empty EOF is
/// NotATag. Reserved flags and revision 255 are invalid; compatible revisions
/// 0..254 are accepted. Flagged compression/unsynchronisation is skipped without
/// decoding its contents. Valid outer boundaries do not certify valid metadata.
///
/// This is a no-I/O, no-copy probe. The caller supplies contiguous input and a
/// length limit; successful total_bytes is always within that input and limit.
pub fn inspect_id3v2(
  input : BytesView,
  eof : Bool,
  max_tag_bytes : Int,
) -> PrefixResult {
  if max_tag_bytes < 0 {
    return Invalid(InvalidLimit)
  }
  let length = input.length()
  if length == 0 {
    return if eof { NotATag } else { NeedMoreInput(3) }
  }
  let signature = b"ID3"
  for index = 0; index < 3 && index < length; index = index + 1 {
    if input[index] != signature[index] {
      return NotATag
    }
  }
  if length < 3 {
    return incomplete(3, length, eof)
  }
  if length < 10 {
    return incomplete(10, length, eof)
  }
  let version = input[3].to_int()
  let revision = input[4].to_int()
  let flags = input[5].to_int()
  let reserved_mask = match version {
    2 => 0x3f
    3 => 0x1f
    4 => 0x0f
    _ => return Invalid(UnsupportedVersion(version))
  }
  if revision == 255 {
    return Invalid(InvalidRevision(revision))
  }
  if (flags & reserved_mask) != 0 {
    return Invalid(InvalidFlags(flags))
  }
  let mut payload_bytes = 0
  for index = 6; index < 10; index = index + 1 {
    let byte = input[index].to_int()
    if (byte & 0x80) != 0 {
      return Invalid(InvalidSynchsafeSize)
    }
    payload_bytes = (payload_bytes << 7) | byte
  }
  let footer = version == 4 && (flags & 0x10) != 0
  // 28 bits plus at most 20 fits Int on every supported backend.
  let total_bytes = payload_bytes + (if footer { 20 } else { 10 })
  if total_bytes > max_tag_bytes {
    return Invalid(TooLarge(total_bytes))
  }
  if length < total_bytes {
    return incomplete(total_bytes, length, eof)
  }
  if footer {
    let start = total_bytes - 10
    if input[start] != b'3' ||
      input[start + 1] != b'D' ||
      input[start + 2] != b'I' {
      return Invalid(InvalidFooter)
    }
    for index = 3; index < 10; index = index + 1 {
      if input[start + index] != input[index] {
        return Invalid(InvalidFooter)
      }
    }
  }
  Tag({ version, revision, flags, payload_bytes, total_bytes })
}

///|
/// audio_end is the exclusive end relative to the supplied view.
pub(all) struct TailInfo {
  audio_end : Int
  tag_bytes : Int
  enhanced : Bool
} derive(Eq, Show)

///|
/// Inspect a complete EOF buffer for a trailing 128-byte ID3v1 block. Also
/// remove its optional immediately preceding 227-byte TAG+ block, matching
/// minimp3. An isolated TAG+ is never removed. Call only once EOF is established:
/// a partial ID3v1 block cannot reliably be distinguished from ordinary bytes.
/// APEv2 and appended ID3v2 are deliberately outside this helper's scope.
pub fn trim_id3v1(input : BytesView) -> TailInfo {
  let length = input.length()
  if length < 128 {
    return { audio_end: length, tag_bytes: 0, enhanced: false }
  }
  let start = length - 128
  if input[start] != b'T' ||
    input[start + 1] != b'A' ||
    input[start + 2] != b'G' {
    return { audio_end: length, tag_bytes: 0, enhanced: false }
  }
  let enhanced_start = start - 227
  if enhanced_start >= 0 &&
    input[enhanced_start] == b'T' &&
    input[enhanced_start + 1] == b'A' &&
    input[enhanced_start + 2] == b'G' &&
    input[enhanced_start + 3] == b'+' {
    { audio_end: enhanced_start, tag_bytes: 355, enhanced: true }
  } else {
    { audio_end: start, tag_bytes: 128, enhanced: false }
  }
}
