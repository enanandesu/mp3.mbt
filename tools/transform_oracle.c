/* Stage-local differential oracle for stereo and hybrid synthesis.
 * Unmodified minimp3 ea99364f61c14656440e8d77e9c233ccf3124633, CC0-1.0.
 * All expected transforms come from the upstream helpers, not copied formulae.
 * The bit writer and random/impulse input generator only build test inputs.
 */
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#define MINIMP3_FLOAT_OUTPUT
#include "../third_party/minimp3/minimp3.h"
#include <stdio.h>
#include <stdlib.h>

static float random_sample(uint32_t *seed)
{
    *seed = *seed * UINT32_C(1664525) + UINT32_C(1013904223);
    return (float)((int)(*seed >> 16) - 32768) * (1.0f/32768.0f);
}

static void put_bits(uint8_t *data, int offset, int width, unsigned value)
{
    for (int i = 0; i < width; i++) {
        int bit = offset + i;
        data[bit/8] |= ((value >> (width-1-i)) & 1) << (7-bit%8);
    }
}

static void granules(L3_gr_info_t *gr, uint8_t *hdr, int rate, int mode,
                     int left_block, int left_mixed, int right_block, int right_mixed)
{
    static const uint8_t modes[] = {0, 0x60, 0x50, 0x70};
    uint8_t side[32] = {0};
    hdr[0] = 255; hdr[1] = 251; hdr[2] = 144 | (rate << 2); hdr[3] = modes[mode];
    for (int i = 0; i < 4; i++) {
        int block = i % 2 ? right_block : left_block;
        int mixed = i % 2 ? right_mixed : left_mixed;
        if (block) {
            put_bits(side, 20 + i*59 + 33, 1, 1);
            put_bits(side, 20 + i*59 + 34, 2, block);
            put_bits(side, 20 + i*59 + 36, 1, mixed);
        }
    }
    bs_t bits;
    bs_init(&bits, side, sizeof(side));
    memset(gr, 0, 4*sizeof(*gr));
    if (L3_read_side_info(&bits, gr, hdr) != 0 || bits.pos != 256)
        exit(2);
}

static void words(const float *values, int count)
{
    for (int i = 0; i < count; i++) {
        uint32_t bits;
        memcpy(&bits, values + i, sizeof(bits));
        printf(" %08x", (unsigned)bits);
    }
}

static void run_case(int group, int rate, int mode, int input, int fixed_shape, int length)
{
    uint32_t first_seed = UINT32_C(0x413193ab) + (unsigned)group;
    uint32_t seed = first_seed;
    float overlap[2][288] = {{0}};
    if (input == 0)
        for (int ch = 0; ch < 2; ch++)
            for (int i = 0; i < 288; i++)
                overlap[ch][i] = random_sample(&seed);
    for (int step = 0; step < length; step++) {
        static const int sequence[] = {0, 1, 2, 3, 0};
        int left_block = length == 1 ? (fixed_shape ? 2 : 0) : sequence[step];
        int right_block = left_block;
        int left_mixed = length == 1 && fixed_shape == 2;
        int right_mixed = length == 1 ? left_mixed : (step == 2);
        L3_gr_info_t gr[4];
        uint8_t hdr[4], positions[39];
        float samples[1152] = {0}, scratch[576];
        granules(gr, hdr, rate, mode, left_block, left_mixed, right_block, right_mixed);
        for (int i = 0; i < 39; i++)
            positions[i] = (i + group + step) % 8;
        if (input == 0) {
            for (int i = 0; i < 1152; i++) samples[i] = random_sample(&seed);
            /* Three right-channel spectra: empty; different maxima per short
             * window; fully populated (tests fallback and last-band handling).
             */
            int profile = (group/3 + group%3 + step) % 3, offset = 576;
            for (int b = 0; b < gr[0].n_long_sfb + gr[0].n_short_sfb; b++) {
                int active = profile == 2 || (profile == 1 && b <= 4*(b%3));
                if (!active) memset(samples + offset, 0, gr[0].sfbtab[b]*sizeof(float));
                offset += gr[0].sfbtab[b];
            }
        } else if (step < 3) {
            samples[(step*113) % 576] = 1.0f;
            samples[575 - step*19] = -0.75f;
            samples[576 + (step*181 + 17) % 576] = 0.5f;
        }
        if (HDR_TEST_I_STEREO(hdr)) L3_intensity_stereo(samples, positions, gr, hdr);
        else if (HDR_IS_MS_STEREO(hdr)) L3_midside_stereo(samples, 576);
        printf("%d %d %d %d %d %d %d %d %d %u", group, rate, mode, input, step,
               left_block, left_mixed, right_block, right_mixed, (unsigned)first_seed);
        words(samples, 1152);
        for (int ch = 0; ch < 2; ch++) {
            float *channel = samples + ch*576;
            int long_bands = (gr[ch].mixed_block_flag ? 2 : 0)
                             << (int)(HDR_GET_MY_SAMPLE_RATE(hdr) == 2);
            int aa_bands = 31;
            if (gr[ch].n_short_sfb) {
                aa_bands = long_bands - 1;
                L3_reorder(channel + long_bands*18, scratch, gr[ch].sfbtab + gr[ch].n_long_sfb);
            }
            L3_antialias(channel, aa_bands);
            L3_imdct_gr(channel, overlap[ch], gr[ch].block_type, long_bands);
            L3_change_sign(channel);
        }
        words(samples, 1152);
        words(overlap[0], 288);
        words(overlap[1], 288);
        for (int i = 0; i < 39; i++) printf(" %08x", positions[i]);
        putchar('\n');
    }
}

int main(void)
{
    int group = 0;
    for (int rate = 0; rate < 3; rate++)
        for (int mode = 0; mode < 4; mode++)
            for (int shape = 0; shape < 3; shape++)
                run_case(group++, rate, mode, 0, shape, 1);
    for (int rate = 0; rate < 3; rate++)
        for (int input = 0; input < 2; input++)
            run_case(group++, rate, 3, input, 0, 5);
    return ferror(stdout) ? 1 : 0;
}
