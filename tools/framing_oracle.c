/* Direct mp3d_find_frame oracle from minimp3, fixed commit
 * ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0).
 * Valid streams only. The MoonBit API adds explicit EOF/limit failures and
 * accepts base 2304 plus padding; C's exclusive candidate limit does not.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#include "../third_party/minimp3/minimp3.h"

int main(int argc, char **argv)
{
    if (argc == 2)
    {
        FILE *f = fopen(argv[1], "rb");
        if (!f) return 2;
        if (fseek(f, 0, SEEK_END)) return 2;
        long n = ftell(f);
        if (n < 0 || n > 10000000 || fseek(f, 0, SEEK_SET)) return 2;
        unsigned char *data = calloc((size_t)n + 16, 1);
        if (!data || fread(data, 1, (size_t)n, f) != (size_t)n) return 2;
        fclose(f);
        int base = 0, size = 0;
        int offset = mp3d_find_frame(data, (int)n, &base, &size);
        if (offset != 0 || base <= 0 || size <= 0) return 3;
        printf("%d,%d,%d\n", offset, size, base);
        free(data);
        return 0;
    }
    const int bases[] = {64, 129, 511, 1024, 2302};
    const int versions[] = {251, 243, 227};
    unsigned char data[10000];
    for (int version = 0; version < 3; ++version)
    for (int rate = 0; rate < 3; ++rate)
    for (int channels = 1; channels <= 2; ++channels)
    for (int crc = 0; crc <= 1; ++crc)
    for (int mask = 0; mask < 8; ++mask)
    for (int b = 0; b < 5; ++b)
    {
        memset(data, 0, sizeof(data));
        int pos = 0;
        for (int frame = 0; frame < 4; ++frame)
        {
            int pad = (mask >> frame) & 1;
            data[pos] = 255;
            data[pos + 1] = (unsigned char)(versions[version] - crc);
            data[pos + 2] = (unsigned char)((rate << 2) | (pad << 1));
            data[pos + 3] = (unsigned char)(channels == 1 ? 192 : 0);
            pos += bases[b] + pad;
        }
        int base = 0, size = 0;
        int offset = mp3d_find_frame(data, pos, &base, &size);
        if (offset || base != bases[b] || size != bases[b] + (mask & 1)) return 4;
        printf("%d,%d,%d,%d,%d,%d,%d,%d,%d\n", version, rate, channels,
               crc, mask, bases[b], offset, size, base);
    }
    return 0;
}
