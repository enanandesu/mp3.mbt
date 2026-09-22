/* Side information and continuous reservoir oracle: unmodified static helpers
 * in minimp3@ea99364f61c14656440e8d77e9c233ccf3124633, CC0-1.0.
 * Development only; no C code is linked into the MoonBit library.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#include "../third_party/minimp3/minimp3.h"

static void hex(const unsigned char *p, int size)
{
    putchar('"');
    for (int i = 0; i < size; ++i) printf("%02x", p[i]);
    putchar('"');
}

int main(int argc, char **argv)
{
    if (argc != 3) return 2;
    FILE *input = fopen(argv[1], "rb");
    if (!input) return 3;
    fseek(input, 0, SEEK_END);
    long size = ftell(input);
    if (size < 0 || size > 10000000) return 4;
    rewind(input);
    unsigned char *data = calloc((size_t)size + 16, 1);
    if (!data || fread(data, 1, (size_t)size, input) != (size_t)size) return 5;
    fclose(input);
    mp3dec_t state;
    memset(&state, 0, sizeof(state));
    int offset = 0, count = 0, maximum = atoi(argv[2]);
    while (offset + 4 <= size && count < maximum)
    {
        const uint8_t *hdr = data + offset;
        if (!hdr_valid(hdr) || !HDR_TEST_MPEG1(hdr) ||
            HDR_GET_LAYER(hdr) != 1 || HDR_IS_FREE_FORMAT(hdr))
        { ++offset; continue; }
        int frame_size = hdr_frame_bytes(hdr, 0) + hdr_padding(hdr);
        if (offset + frame_size > size) break;
        mp3dec_scratch_t scratch;
        memset(&scratch, 0, sizeof(scratch));
        bs_t bits;
        bs_init(&bits, hdr + 4, frame_size - 4);
        if (HDR_IS_CRC(hdr)) get_bits(&bits, 16);
        int begin = L3_read_side_info(&bits, scratch.gr_info, hdr);
        if (begin < 0) return 6;
        int side_bits = bits.pos;
        if (!L3_restore_reservoir(&state, &bits, &scratch, begin)) return 7;
        printf("{\"frame\":"); hex(hdr, frame_size);
        printf(",\"begin\":%d,\"side_bits\":%d,\"main\":", begin, side_bits + 32);
        hex(scratch.maindata, scratch.bs.limit / 8);
        printf(",\"granules\":[");
        int consumed = 0;
        for (int gr = 0; gr < (HDR_IS_MONO(hdr) ? 2 : 4); ++gr)
        {
            L3_gr_info_t *g = scratch.gr_info + gr;
            if (gr) putchar(',');
            printf("[%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d",
                   g->part_23_length, g->big_values, g->scalefac_compress,
                   g->global_gain, g->block_type, g->mixed_block_flag,
                   g->n_long_sfb, g->n_short_sfb, g->preflag,
                   g->scalefac_scale, g->count1_table, g->scfsi);
            for (int j = 0; j < 3; ++j) printf(",%d", g->table_select[j]);
            for (int j = 0; j < 3; ++j) printf(",%d", g->region_count[j]);
            for (int j = 0; j < 3; ++j) printf(",%d", g->subblock_gain[j]);
            for (int j = 0; j < g->n_long_sfb + g->n_short_sfb + 1; ++j)
                printf(",%d", g->sfbtab[j]);
            putchar(']');
            consumed += g->part_23_length;
        }
        scratch.bs.pos = consumed;
        L3_save_reservoir(&state, &scratch);
        printf("],\"consumed\":%d,\"saved\":", consumed);
        hex(state.reserv_buf, state.reserv);
        puts("}");
        offset += frame_size;
        ++count;
    }
    free(data);
    return count == maximum ? 0 : 8;
}
