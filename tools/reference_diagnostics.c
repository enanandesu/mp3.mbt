/* Read-only state tracing around the actual, unmodified scalar decoder.
 * minimp3 ea99364f61c14656440e8d77e9c233ccf3124633, minimp3.h:
 * mp3dec_decode_frame, L3_read_side_info, L3_restore_reservoir.
 * Shadow helper calls explain return values; only the real decoder changes
 * the live state. No PCM shifts, padding, replacement, or output editing. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_NO_STDIO
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#define MINIMP3_FLOAT_OUTPUT
#include "../third_party/minimp3/minimp3_ex.h"

static void fail(const char *message) { fprintf(stderr, "%s\n", message); exit(2); }

/* Exact fast-path predicate from mp3dec_decode_frame. A miss clears history
 * before its synchronization search, even if the search finds a later frame. */
static int keeps_history(const mp3dec_t *before, const uint8_t *p, int n)
{
    if (n > 4 && before->header[0] == 0xff && hdr_compare(before->header, p)) {
        int size = hdr_frame_bytes(p, before->free_format_bytes) + hdr_padding(p);
        if (size != n && (size + HDR_SIZE > n || !hdr_compare(p, p + size))) return 0;
        return size != 0;
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 2) fail("usage: reference_diagnostics input.mp3");
    FILE *in = fopen(argv[1], "rb");
    if (!in || fseek(in, 0, SEEK_END)) fail("input open/seek failed");
    long size = ftell(in);
    if (size < 0 || size > 64 * 1024 * 1024) fail("input exceeds limit");
    rewind(in);
    uint8_t *buffer = calloc((size_t)size + 16, 1);
    if (!buffer || fread(buffer, 1, size, in) != (size_t)size) fail("input read failed");
    fclose(in);
    const uint8_t *audio = buffer;
    size_t length = size;
    mp3dec_skip_id3(&audio, &length);
    mp3dec_t dec = {0};
    mp3dec_init(&dec);
    size_t pos = 0, index = 0, total_samples = 0, nominal_samples = 0, zero_frames = 0;
    int channels = 0, hz = 0;
    printf("{\"frames\":[");
    while (pos < length) {
        mp3dec_t before = dec;
        int history_kept = keeps_history(&before, audio + pos, (int)(length - pos));
        mp3dec_frame_info_t info = {0};
        mp3d_sample_t pcm[MINIMP3_MAX_SAMPLES_PER_FRAME];
        int samples = mp3dec_decode_frame(&dec, audio + pos, (int)(length - pos), pcm, &info);
        if (info.frame_bytes <= 0 || info.hz == 0) break;
        if ((size_t)info.frame_bytes > length - pos || info.frame_offset < 0) fail("decoder frame boundary invalid");
        const uint8_t *hdr = audio + pos + info.frame_offset;
        int frame_bytes = info.frame_bytes - info.frame_offset;
        int nominal = hdr_frame_samples(hdr);
        int main_data_begin = -1, side_pos = -1, side_limit = -1, restored = -1;
        int effective_reservoir = history_kept ? before.reserv : 0;
        const char *reason = "decoded";
        if (info.layer == 3) {
            bs_t bits;
            mp3dec_scratch_t scratch;
            bs_init(&bits, hdr + HDR_SIZE, frame_bytes - HDR_SIZE);
            if (HDR_IS_CRC(hdr)) get_bits(&bits, 16);
            main_data_begin = L3_read_side_info(&bits, scratch.gr_info, hdr);
            side_pos = bits.pos;
            side_limit = bits.limit;
            if (main_data_begin < 0 || bits.pos > bits.limit) {
                reason = "invalid_side_info";
            } else {
                mp3dec_t shadow = before;
                if (!history_kept) memset(&shadow, 0, sizeof(shadow));
                restored = L3_restore_reservoir(&shadow, &bits, &scratch, main_data_begin);
                if (!restored) reason = "insufficient_bit_reservoir";
            }
        } else { reason = "unsupported_layer"; }
        int explained = samples ? !strcmp(reason, "decoded") : strcmp(reason, "decoded") != 0;
        if (!explained) fail("shadow explanation disagrees with real decoder");
        if (index) printf(",");
        printf("{\"index\":%llu,\"byte_offset\":%llu,\"encoded_bytes\":%d,"
               "\"skipped_before\":%d,\"header\":\"%02x%02x%02x%02x\","
               "\"sample_rate\":%d,\"channels\":%d,\"samples_per_channel\":%d,"
               "\"nominal_samples_per_channel\":%d,\"history_reset\":%s,"
               "\"reservoir_before\":%d,\"effective_reservoir\":%d,"
               "\"main_data_begin\":%d,\"side_info_bits\":%d,\"payload_bit_limit\":%d,"
               "\"restore_result\":%d,\"reservoir_after\":%d,\"reason\":\"%s\"}",
               (unsigned long long)index, (unsigned long long)(audio - buffer + pos + info.frame_offset),
               frame_bytes, info.frame_offset, hdr[0], hdr[1], hdr[2], hdr[3],
               info.hz, info.channels, samples, nominal, history_kept ? "false" : "true",
               before.reserv, effective_reservoir, main_data_begin, side_pos, side_limit,
               restored, dec.reserv, reason);
        total_samples += (size_t)samples * info.channels;
        nominal_samples += (size_t)nominal * info.channels;
        if (!samples) zero_frames++;
        channels = info.channels;
        hz = info.hz;
        index++;
        pos += info.frame_bytes;
    }
    size_t tail_bytes = length - pos;
    int tail_header = tail_bytes >= HDR_SIZE && hdr_valid(audio + pos);
    int tail_expected = tail_header ? hdr_frame_bytes(audio + pos, dec.free_format_bytes) + hdr_padding(audio + pos) : 0;
    printf("],\"tail\":{\"byte_offset\":%llu,\"available_bytes\":%llu,"
           "\"valid_mpeg_header\":%s,\"header_frame_bytes\":%d},"
           "\"summary\":{\"frame_count\":%llu,\"sample_count\":%llu,"
           "\"nominal_sample_count\":%llu,\"zero_sample_frames\":%llu,"
           "\"trailing_bytes\":%llu,\"sample_rate\":%d,\"channels\":%d}}\n",
           (unsigned long long)(audio - buffer + pos), (unsigned long long)tail_bytes,
           tail_header ? "true" : "false", tail_expected,
           (unsigned long long)index, (unsigned long long)total_samples,
           (unsigned long long)nominal_samples, (unsigned long long)zero_frames,
           (unsigned long long)(length - pos), hz, channels);
    free(buffer);
    return 0;
}
