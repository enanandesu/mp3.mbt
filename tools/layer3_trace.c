/* Scalar checkpoints from unmodified minimp3, CC0-1.0, upstream commit
 * ea99364f61c14656440e8d77e9c233ccf3124633. Scheduling is transcribed from
 * mp3dec_decode_frame and L3_decode solely to observe intermediate arrays.
 * Every completed frame is checked bit-for-bit against a parallel invocation
 * of the original mp3dec_decode_frame before any of its checkpoints are saved.
 * The binary format contains numerical/byte fixtures, never paths or addresses.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <limits.h>
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_FLOAT_OUTPUT
#define MINIMP3_NO_SIMD
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_STDIO
#include "../third_party/minimp3/minimp3_ex.h"

typedef struct { unsigned char data[131072]; size_t used; } trace_buffer;

static void fail(const char *message)
{
    fprintf(stderr, "%s\n", message);
    exit(2);
}

static void bytes(trace_buffer *trace, const void *data, size_t count)
{
    if (count > sizeof(trace->data) - trace->used) fail("checkpoint buffer overflow");
    memcpy(trace->data + trace->used, data, count);
    trace->used += count;
}

static void u32(trace_buffer *trace, uint32_t value)
{
    const unsigned char output[4] = {value & 255, (value >> 8) & 255,
                                   (value >> 16) & 255, value >> 24};
    bytes(trace, output, sizeof(output));
}

static void floats(trace_buffer *trace, const float *values, int count)
{
    int i;
    for (i = 0; i < count; i++)
    {
        uint32_t bits;
        memcpy(&bits, values + i, sizeof(bits));
        u32(trace, bits);
    }
}

static void granule_info(trace_buffer *trace, const L3_gr_info_t *gr)
{
    int i;
    u32(trace, gr->part_23_length); u32(trace, gr->big_values);
    u32(trace, gr->scalefac_compress); u32(trace, gr->global_gain);
    u32(trace, gr->block_type); u32(trace, gr->mixed_block_flag);
    u32(trace, gr->n_long_sfb); u32(trace, gr->n_short_sfb);
    u32(trace, gr->preflag); u32(trace, gr->scalefac_scale);
    u32(trace, gr->count1_table); u32(trace, gr->scfsi);
    for (i = 0; i < 3; i++) u32(trace, gr->table_select[i]);
    for (i = 0; i < 3; i++) u32(trace, gr->region_count[i]);
    for (i = 0; i < 3; i++) u32(trace, gr->subblock_gain[i]);
}

static void trace_granule(trace_buffer *trace, mp3dec_t *dec,
                          mp3dec_scratch_t *s, L3_gr_info_t *gr,
                          int channels, float *pcm)
{
    int ch, i;
    memset(s->grbuf, 0, sizeof(s->grbuf));
    for (ch = 0; ch < channels; ch++)
    {
        int before = s->bs.pos;
        int limit = before + gr[ch].part_23_length;
        int after_scalefactors;
        memset(s->scf, 0, sizeof(s->scf));
        L3_decode_scalefactors(dec->header, s->ist_pos[ch], &s->bs, gr + ch, s->scf, ch);
        after_scalefactors = s->bs.pos;
        L3_huffman(s->grbuf[ch], &s->bs, gr + ch, s->scf, limit);
        granule_info(trace, gr + ch);
        u32(trace, before); u32(trace, after_scalefactors); u32(trace, s->bs.pos);
        for (i = 0; i < 39; i++) u32(trace, s->ist_pos[ch][i]);
        floats(trace, s->scf, 40);
        floats(trace, s->grbuf[ch], 576);
    }
    if (HDR_TEST_I_STEREO(dec->header))
        L3_intensity_stereo(s->grbuf[0], s->ist_pos[1], gr, dec->header);
    else if (HDR_IS_MS_STEREO(dec->header))
        L3_midside_stereo(s->grbuf[0], 576);
    floats(trace, s->grbuf[0], 1152);
    for (ch = 0; ch < channels; ch++)
    {
        int aa_bands = 31;
        int n_long_bands = (gr[ch].mixed_block_flag ? 2 : 0) <<
                          (int)(HDR_GET_MY_SAMPLE_RATE(dec->header) == 2);
        if (gr[ch].n_short_sfb)
        {
            aa_bands = n_long_bands - 1;
            L3_reorder(s->grbuf[ch] + n_long_bands * 18, s->syn[0],
                       gr[ch].sfbtab + gr[ch].n_long_sfb);
        }
        L3_antialias(s->grbuf[ch], aa_bands);
        L3_imdct_gr(s->grbuf[ch], dec->mdct_overlap[ch], gr[ch].block_type, n_long_bands);
        L3_change_sign(s->grbuf[ch]);
    }
    floats(trace, s->grbuf[0], 1152);
    mp3d_synth_granule(dec->qmf_state, s->grbuf[0], 18, channels, pcm, s->syn[0]);
    floats(trace, pcm, 576 * channels);
    floats(trace, dec->mdct_overlap[0], 576);
    floats(trace, dec->qmf_state, 960);
}

int main(int argc, char **argv)
{
    FILE *input, *output;
    long file_size;
    uint8_t *storage;
    const uint8_t *audio;
    size_t audio_size, offset;
    long max_frames;
    char *end;
    int frame_size = 0, free_format = 0, skipped, frames = 0;
    mp3dec_t observed, original;
    trace_buffer *trace;
    if (argc != 4) fail("usage: layer3_trace input output.bin max_frames (0 = all)");
    max_frames = strtol(argv[3], &end, 10);
    if (*end || max_frames < 0 || max_frames > INT_MAX) fail("invalid frame count");
    input = fopen(argv[1], "rb");
    if (!input) fail("input open failed");
    if (fseek(input, 0, SEEK_END)) fail("input seek failed");
    file_size = ftell(input);
    if (file_size < 0 || file_size > 64 * 1024 * 1024) fail("input exceeds trace limit");
    rewind(input);
    storage = (uint8_t *)calloc((size_t)file_size + 16, 1);
    if (!storage || fread(storage, 1, (size_t)file_size, input) != (size_t)file_size)
        fail("input read failed");
    fclose(input);
    audio = storage;
    audio_size = (size_t)file_size;
    mp3dec_skip_id3(&audio, &audio_size);
    skipped = mp3d_find_frame(audio, (int)audio_size, &free_format, &frame_size);
    if (!frame_size || skipped < 0 || (size_t)skipped >= audio_size) fail("no initial frame");
    offset = (size_t)skipped;
    memset(&observed, 0, sizeof(observed));
    memset(&original, 0, sizeof(original));
    observed.free_format_bytes = free_format;
    mp3dec_init(&observed);
    mp3dec_init(&original);
    trace = (trace_buffer *)calloc(1, sizeof(*trace));
    if (!trace) fail("checkpoint allocation failed");
    output = fopen(argv[2], "wb");
    if (!output) fail("checkpoint open failed");
    u32(trace, 0x3352504d); u32(trace, 1);
    if (fwrite(trace->data, 1, trace->used, output) != trace->used) fail("header write failed");
    while (offset + HDR_SIZE <= audio_size && (!max_frames || frames < max_frames))
    {
        const uint8_t *frame = audio + offset;
        mp3dec_scratch_t scratch;
        bs_t frame_bits;
        int channels, main_begin, igr, samples;
        mp3dec_frame_info_t info;
        float pcm[MINIMP3_MAX_SAMPLES_PER_FRAME] = {0};
        float baseline[MINIMP3_MAX_SAMPLES_PER_FRAME] = {0};
        if (!hdr_valid(frame)) fail("non-frame data in contiguous trace");
        if (!HDR_TEST_MPEG1(frame) || HDR_GET_LAYER(frame) != 1) fail("trace requires MPEG1 Layer III");
        if (frames && !hdr_compare(observed.header, frame)) fail("stream format changed");
        frame_size = hdr_frame_bytes(frame, free_format) + hdr_padding(frame);
        if (frame_size <= HDR_SIZE || (size_t)frame_size > audio_size - offset) fail("truncated frame");
        channels = HDR_IS_MONO(frame) ? 1 : 2;
        memcpy(observed.header, frame, HDR_SIZE);
        memset(&scratch, 0, sizeof(scratch));
        bs_init(&frame_bits, frame + HDR_SIZE, frame_size - HDR_SIZE);
        if (HDR_IS_CRC(frame)) get_bits(&frame_bits, 16);
        main_begin = L3_read_side_info(&frame_bits, scratch.gr_info, frame);
        if (main_begin < 0 || frame_bits.pos > frame_bits.limit) fail("invalid side information");
        if (!L3_restore_reservoir(&observed, &frame_bits, &scratch, main_begin))
            fail("insufficient initial reservoir history");
        trace->used = 0;
        u32(trace, (uint32_t)((audio - storage) + offset));
        u32(trace, frame_size); u32(trace, channels);
        u32(trace, hdr_sample_rate_hz(frame)); u32(trace, main_begin);
        u32(trace, scratch.bs.limit / 8);
        bytes(trace, scratch.maindata, (size_t)scratch.bs.limit / 8);
        for (igr = 0; igr < 2; igr++)
            trace_granule(trace, &observed, &scratch, scratch.gr_info + igr * channels,
                          channels, pcm + igr * 576 * channels);
        L3_save_reservoir(&observed, &scratch);
        u32(trace, scratch.bs.pos); u32(trace, observed.reserv);
        bytes(trace, observed.reserv_buf, (size_t)observed.reserv);
        memset(&info, 0, sizeof(info));
        samples = mp3dec_decode_frame(&original, frame, (int)(audio_size - offset), baseline, &info);
        if (samples != 1152 || info.frame_offset || info.frame_bytes != frame_size ||
            info.channels != channels || info.hz != (int)hdr_sample_rate_hz(frame))
            fail("original decoder frame scheduling differs");
        if (memcmp(pcm, baseline, (size_t)samples * channels * sizeof(float)))
            fail("trace PCM differs from unmodified scalar decoder");
        if (observed.reserv != original.reserv) fail("trace reservoir size differs from original");
        if (memcmp(observed.reserv_buf, original.reserv_buf, (size_t)observed.reserv))
            fail("trace reservoir bytes differ from original");
        if (memcmp(observed.mdct_overlap, original.mdct_overlap, sizeof(observed.mdct_overlap)))
            fail("trace overlap differs from original");
        {
            int qi;
            for (qi = 0; qi < 960; qi++)
            {
                /* mp3d_synth leaves lanes 2/3 of its final 15 tuples unwritten.
                 * They are overwritten before the next call reads them. The
                 * original stack scratch has indeterminate bytes here; never
                 * inspect or persist them. Our scratch explicitly starts zero. */
                if (qi >= 896 && qi < 956 && (qi & 3) >= 2) continue;
                if (memcmp(observed.qmf_state + qi, original.qmf_state + qi, sizeof(float)))
                    fail("trace live synthesis history differs from original");
            }
        }
        if (fwrite(trace->data, 1, trace->used, output) != trace->used) fail("checkpoint write failed");
        offset += (size_t)frame_size;
        frames++;
    }
    if (!frames || (max_frames && frames < max_frames)) fail("not enough complete frames");
    if (fclose(output)) fail("checkpoint close failed");
    printf("Verified %d contiguous scalar frames and all live retained decoder state\n", frames);
    free(trace);
    free(storage);
    return 0;
}
