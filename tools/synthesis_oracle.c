/* Continuous-granule scalar float synthesis oracle using unmodified minimp3.
 * minimp3 commit ea99364f61c14656440e8d77e9c233ccf3124633, CC0-1.0.
 */
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#define MINIMP3_FLOAT_OUTPUT
#include "../third_party/minimp3/minimp3.h"
#include <stdio.h>

static float sample(uint32_t *seed)
{
    *seed = *seed * UINT32_C(1664525) + UINT32_C(1013904223);
    return (float)((int)(*seed >> 16) - 32768) * (1.0f / 32768.0f);
}

static void words(const float *values, int count)
{
    for (int i = 0; i < count; i++) {
        uint32_t bits;
        memcpy(&bits, values + i, sizeof(bits));
        printf(" %08x", (unsigned)bits);
    }
}

static void run_case(int mode, int initial_channels, int count)
{
    uint32_t seed = UINT32_C(0x735193ab) + (uint32_t)(mode * 32 + initial_channels);
    float state[15*64] = {0};
    float grbuf[2*576];
    float lins[(18+15)*64];
    float pcm[2*576];
    if (mode == 3)
        for (int i = 0; i < 15*64; i++)
            state[i] = sample(&seed);
    for (int step = 0; step < count; step++) {
        int nch = mode == 3 ? 2 - step % 2 : initial_channels;
        memset(grbuf, 0, sizeof(grbuf));
        memset(lins, 0, sizeof(lins));
        memset(pcm, 0, sizeof(pcm));
        if (mode >= 2) {
            for (int i = 0; i < nch*576; i++)
                grbuf[i] = sample(&seed);
        } else if (mode == 1 && step == 0) {
            grbuf[0] = 1.0f;
            grbuf[18*31 + 17] = -0.75f;
            if (nch == 2) {
                grbuf[576 + 16*18 + 9] = 0.5f;
                grbuf[576 + 17] = -1.0f;
            }
        }
        mp3d_synth_granule(state, grbuf, 18, nch, pcm, lins);
        printf("%d %d %d", mode, nch, step);
        words(pcm, 576*nch);
        words(state, 15*64);
        words(grbuf, 576*nch);
        putchar('\n');
    }
}

int main(void)
{
    for (int nch = 1; nch <= 2; nch++)
        for (int mode = 0; mode < 3; mode++)
            run_case(mode, nch, 3);
    run_case(3, 2, 4);
    return ferror(stdout) ? 1 : 0;
}
