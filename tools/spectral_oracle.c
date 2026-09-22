/* Test-only scalar oracle. All numerical results come from unmodified minimp3
 * ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0).
 * Caller supplies complete Huffman codewords so no padded sign bits are tested
 * as valid data. The MoonBit-only malformed-budget tests enforce the safe API. */
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#include "../third_party/minimp3/minimp3.h"
#include <stdio.h>

static uint32_t float_bits(float f)
{
    uint32_t u;
    memcpy(&u, &f, sizeof(u));
    return u;
}

int main(void)
{
    int kind, id;
    while (scanf("%d%d", &kind, &id) == 2)
    {
        L3_gr_info_t gr;
        bs_t bs;
        unsigned char data[2048] = {0};
        memset(&gr, 0, sizeof(gr));
        if (kind == 0)
        {
            int layout, compress, reuse, gain, scale, pre, ms, ch, i;
            uint8_t ist[40];
            float scf[40] = {0};
            uint8_t hdr[4] = {255,251,144,0};
            if (scanf("%d%d%d%d%d%d%d%d", &layout, &compress, &reuse,
                &gain, &scale, &pre, &ms, &ch) != 8) return 2;
            hdr[3] = ms ? 0x60 : 0;
            for (i = 0; i < 128; i++) data[i] = (uint8_t)(i * 73 + id * 19 + 23);
            for (i = 0; i < 40; i++) ist[i] = (uint8_t)(i % 7);
            gr.n_long_sfb = layout == 0 ? 22 : (layout == 1 ? 0 : 8);
            gr.n_short_sfb = layout == 0 ? 0 : (layout == 1 ? 39 : 30);
            gr.scalefac_compress = compress;
            gr.scfsi = reuse;
            gr.global_gain = gain;
            gr.scalefac_scale = scale;
            gr.preflag = pre;
            gr.subblock_gain[0] = 1; gr.subblock_gain[1] = 3; gr.subblock_gain[2] = 7;
            bs_init(&bs, data, 128);
            L3_decode_scalefactors(hdr, ist, &bs, &gr, scf, ch);
            printf("S,%d,%d", id, bs.pos);
            for (i = 0; i < 40; i++) printf(",%d", ist[i]);
            for (i = 0; i < gr.n_long_sfb + gr.n_short_sfb; i++) printf(",%u", float_bits(scf[i]));
            puts("");
        }
        else if (kind == 1)
        {
            int table, big, count, limit, length, i, value;
            uint8_t bands[] = {4,6,8,6,138,138,138,138,0};
            float scales[] = {0.03125f,0.75f,2.f,5.f,1.f,1.f,1.f,1.f};
            float dst[576] = {0};
            if (scanf("%d%d%d%d%d", &table, &big, &count, &limit, &length) != 5) return 2;
            if (length < 0 || length > 2000) return 3;
            for (i = 0; i < length; i++) { if (scanf("%d", &value) != 1) return 2; data[i] = (uint8_t)value; }
            gr.sfbtab = bands;
            gr.table_select[0] = gr.table_select[1] = gr.table_select[2] = table;
            gr.region_count[0] = 0; gr.region_count[1] = 1; gr.region_count[2] = 255;
            gr.big_values = big;
            gr.count1_table = count;
            bs_init(&bs, data, length);
            L3_huffman(dst, &bs, &gr, scales, limit);
            printf("H,%d,%d", id, bs.pos);
            for (i = 0; i < 576; i++) printf(",%u", float_bits(dst[i]));
            puts("");
        }
        else if (kind == 2)
        {
            int x;
            if (scanf("%d", &x) != 1) return 2;
            printf("P,%d,%u\n", id, float_bits(L3_pow_43(x)));
        }
        else return 4;
    }
    return 0;
}
