/* Compare the MoonBit header parser to unmodified minimp3 functions.
 * Reference: ea99364f61c14656440e8d77e9c233ccf3124633, CC0-1.0.
 * Build with tools/generate_header_vectors.py; no decoder changes are made.
 */
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#include "../third_party/minimp3/minimp3.h"
#include <stdio.h>

int main(void)
{
    const int versions[] = {3, 2, 0};
    const uint8_t compare_base[4] = {255, 0xfb, 0x90, 0};
    for (unsigned v = 0; v < 3; ++v)
    for (int sr = 0; sr < 3; ++sr)
    for (int br = 0; br < 15; ++br)
    for (int pad = 0; pad < 2; ++pad)
    for (int crc = 0; crc < 2; ++crc)
    for (int mode = 0; mode < 4; ++mode)
    {
        uint8_t h[4] = {255, 0xe0 | (versions[v] << 3) | 2 | !crc,
                        (br << 4) | (sr << 2) | (pad << 1),
                        (mode << 6) | 0x30};
        uint8_t side_info[32] = {0};
        bs_t bs;
        L3_gr_info_t granules[4] = {{0}};
        bs_init(&bs, side_info, sizeof(side_info));
        if (!hdr_valid(h) || !hdr_compare(h, h) ||
            L3_read_side_info(&bs, granules, h) != 0)
            return 1;
        printf("%u,%u,%u,%u,%u,%u,%d,%d,%d,%d,%d,%d\n",
               h[1], h[2], h[3], hdr_bitrate_kbps(h),
               hdr_sample_rate_hz(h), hdr_frame_samples(h),
               hdr_frame_bytes(h, 1000) + hdr_padding(h),
               HDR_IS_CRC(h), HDR_IS_MONO(h) ? 1 : 2,
               bs.pos / 8, HDR_IS_MS_STEREO(h), hdr_compare(compare_base, h));
    }
    return ferror(stdout) ? 2 : 0;
}
