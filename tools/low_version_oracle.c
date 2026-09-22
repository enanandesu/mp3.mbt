/* All-version scalar core oracle using minimp3.h primitives, CC0-1.0,
 * ea99364f61c14656440e8d77e9c233ccf3124633. Outputs only numeric fixtures.
 * The 8 kHz mixed band table is corrected at the call site, as explained in
 * make_frame. Those cases intentionally are not an unmodified-C oracle. */
#include <stdio.h>
#include <string.h>
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_FLOAT_OUTPUT
#define MINIMP3_NO_SIMD
#define MINIMP3_ONLY_MP3
#include "../third_party/minimp3/minimp3.h"

static uint32_t words_hash(const float *values, int count)
{
    uint32_t hash = 2166136261u;
    for (int i = 0; i < count; i++) {
        uint32_t bits;
        memcpy(&bits, values + i, 4);
        hash = (hash ^ bits) * 16777619u;
    }
    return hash;
}
static uint32_t positions_hash(const uint8_t *values, int count)
{
    uint32_t hash = 2166136261u;
    for (int i = 0; i < count; i++) hash = (hash ^ values[i]) * 16777619u;
    return hash;
}
static void put_bits(uint8_t *bytes, int *position, int width, int value)
{
    for (int i = width - 1; i >= 0; i--, (*position)++)
        bytes[*position / 8] |= ((value >> i) & 1) << (7 - (*position & 7));
}
static int make_frame(uint8_t *frame, int rate, int layout, int channels, int crc,
                      int mode, L3_gr_info_t *gr)
{
    const uint8_t versions[] = {227,243,251};
    int mpeg1 = rate >= 6, position = 32 + (crc ? 16 : 0);
    int count = channels * (mpeg1 ? 2 : 1);
    bs_t bits;
    memset(frame, 0, 4096);
    frame[0] = 255; frame[1] = versions[rate / 3] - crc;
    frame[2] = 0x90 | (rate % 3) * 4;
    frame[3] = channels == 1 ? 0xc0 : (0x40 | mode * 16);
    put_bits(frame, &position, mpeg1 ? 9 : 8, 0);
    put_bits(frame, &position, mpeg1 ? (channels == 1 ? 5 : 3) : channels, 0);
    if (mpeg1) for (int ch = 0; ch < channels; ch++) put_bits(frame, &position, 4, 0);
    for (int g = 0; g < count; g++) {
        int block = layout == 4 ? 2 : layout;
        put_bits(frame, &position, 12, 0);
        put_bits(frame, &position, 9, 0);
        put_bits(frame, &position, 8, 180 + g);
        put_bits(frame, &position, mpeg1 ? 4 : 9, mpeg1 ? 15 : 500 + g);
        put_bits(frame, &position, 1, block != 0);
        if (block) {
            put_bits(frame, &position, 2, block);
            put_bits(frame, &position, 1, layout == 4);
            put_bits(frame, &position, 5, 1); put_bits(frame, &position, 5, 31);
            put_bits(frame, &position, 3, 1); put_bits(frame, &position, 3, 3);
            put_bits(frame, &position, 3, 7);
        } else {
            put_bits(frame, &position, 5, 1); put_bits(frame, &position, 5, 16);
            put_bits(frame, &position, 5, 31);
            put_bits(frame, &position, 4, 5); put_bits(frame, &position, 3, 6);
        }
        if (mpeg1) put_bits(frame, &position, 1, 1);
        put_bits(frame, &position, 1, g & 1); put_bits(frame, &position, 1, 1);
    }
    int size = hdr_frame_bytes(frame, 0);
    bs_init(&bits, frame + 4, size - 4);
    if (crc) get_bits(&bits, 16);
    memset(gr, 0, 4 * sizeof(*gr));
    if (L3_read_side_info(&bits, gr, frame) != 0 || bits.pos + 32 != position) return -1;
    if (rate == 2 && layout == 4) {
        /* Original mixed[1] has 39 bands and a 48-sample long prefix, but
         * declares 6+30 bands and starts the transform at 72. Its reorder
         * would read/write beyond the 576-sample channel. Obtain the six
         * long bands and short bands 3..12 from the fixed original tables. */
        static uint8_t bounded_mixed[37];
        uint8_t auxiliary[4096];
        L3_gr_info_t long_gr[4], short_gr[4];
        if (make_frame(auxiliary,rate,0,channels,crc,mode,long_gr) < 0 ||
            make_frame(auxiliary,rate,2,channels,crc,mode,short_gr) < 0) return -1;
        int total = 0;
        for (int i = 0; i < 6; i++) total += (bounded_mixed[i] = long_gr[0].sfbtab[i]);
        if (total != 72) return -1;
        for (int i = 0; i < 30; i++) total += (bounded_mixed[6+i] = short_gr[0].sfbtab[9+i]);
        bounded_mixed[36] = 0;
        if (total != 576) return -1;
        for (int g = 0; g < count; g++) gr[g].sfbtab = bounded_mixed;
    }
    return size;
}
int main(void)
{
    int id = 0;
    for (int layout = 0; layout < 3; layout++)
    for (int intensity = 0; intensity < 2; intensity++)
    for (int compress = 0; compress < 512; compress++, id++) {
        uint8_t hdr[4] = {255, id & 1 ? 227 : 243, 144, intensity ? 0x70 : 0};
        uint8_t data[128], positions[40];
        float scales[40] = {0};
        bs_t bits; L3_gr_info_t gr;
        memset(&gr, 0, sizeof(gr));
        gr.n_long_sfb = layout == 0 ? 22 : (layout == 1 ? 0 : 6);
        gr.n_short_sfb = layout == 0 ? 0 : (layout == 1 ? 39 : 30);
        gr.scalefac_compress = compress;
        gr.global_gain = (id * 29) % 256;
        gr.scalefac_scale = id & 1;
        gr.preflag = compress >= 500;
        gr.subblock_gain[0] = 1; gr.subblock_gain[1] = 3; gr.subblock_gain[2] = 7;
        for (int i = 0; i < 128; i++) data[i] = (uint8_t)(i * 73 + id * 19 + 23);
        for (int i = 0; i < 40; i++) positions[i] = i % 7;
        bs_init(&bits, data, 128);
        L3_decode_scalefactors(hdr, positions, &bits, &gr, scales, intensity);
        printf("S %d %d %d %d %d %d %u %u\n", id, layout, intensity, compress,
               hdr[1], bits.pos, positions_hash(positions, 40),
               words_hash(scales, gr.n_long_sfb + gr.n_short_sfb));
    }
    for (int rate = 0; rate < 9; rate++)
    for (int layout = 0; layout < 5; layout++)
    for (int channels = 1; channels <= 2; channels++)
    for (int crc = 0; crc < 2; crc++) {
        uint8_t frame[4096]; L3_gr_info_t gr[4];
        int size = make_frame(frame, rate, layout, channels, crc, 0, gr);
        if (size < 0) return 2;
        printf("B %d %d %d %d %d", rate, layout, channels, crc, size);
        for (int g = 0; g < channels * (rate >= 6 ? 2 : 1); g++) {
            const L3_gr_info_t *p = gr + g;
            printf(" %d %d %d %d %d %d %d %d %d %d %d %d", p->part_23_length,
              p->big_values,p->scalefac_compress,p->global_gain,p->block_type,p->mixed_block_flag,
              p->n_long_sfb,p->n_short_sfb,p->preflag,p->scalefac_scale,p->count1_table,p->scfsi);
            for (int i = 0; i < 3; i++) printf(" %d", p->table_select[i]);
            for (int i = 0; i < 3; i++) printf(" %d", p->region_count[i]);
            for (int i = 0; i < 3; i++) printf(" %d", p->subblock_gain[i]);
            for (int i = 0; i <= p->n_long_sfb + p->n_short_sfb; i++) printf(" %d", p->sfbtab[i]);
        }
        puts("");
    }
    id = 0;
    for (int rate = 0; rate < 9; rate++)
    for (int layout = 0; layout < 5; layout++)
    for (int mode = 0; mode < 4; mode++)
    for (int parity = 0; parity < 2; parity++, id++) {
        uint8_t frame[4096], positions[39]; L3_gr_info_t gr[4];
        float samples[1152], overlap[2][288];
        if (make_frame(frame, rate, layout, 2, 0, mode, gr) < 0) return 3;
        gr[1].scalefac_compress = parity;
        for (int i = 0; i < 1152; i++) samples[i] = (float)((i * 29 + id * 13) % 257 - 128) / 1024;
        for (int i = 128 + id % 200; i < 576; i++) samples[576 + i] = 0;
        for (int i = 0; i < 39; i++) positions[i] = i % 11 == 0 ? 255 : (i * 3 + id) % (rate >= 6 ? 9 : 64);
        for (int ch = 0; ch < 2; ch++) for (int i = 0; i < 288; i++)
            overlap[ch][i] = (float)((i + ch) % 17 - 8) / 8192;
        if (HDR_TEST_I_STEREO(frame)) L3_intensity_stereo(samples, positions, gr, frame);
        else if (HDR_IS_MS_STEREO(frame)) L3_midside_stereo(samples, 576);
        printf("T %d %d %d %d %d %u %u", id, rate, layout, mode, parity,
               words_hash(samples,1152), positions_hash(positions,39));
        for (int ch = 0; ch < 2; ch++) {
            int long_bands = (gr[ch].mixed_block_flag ? 2 : 0) << (HDR_GET_MY_SAMPLE_RATE(frame) == 2);
            float scratch[576];
            if (gr[ch].n_short_sfb) L3_reorder(samples + ch * 576 + long_bands * 18, scratch,
                                             gr[ch].sfbtab + gr[ch].n_long_sfb);
            L3_antialias(samples + ch * 576, gr[ch].n_short_sfb ? long_bands - 1 : 31);
            L3_imdct_gr(samples + ch * 576, overlap[ch], gr[ch].block_type,long_bands);
            L3_change_sign(samples + ch * 576);
        }
        printf(" %u %u\n", words_hash(samples,1152),words_hash(overlap[0],576));
    }
    return 0;
}
