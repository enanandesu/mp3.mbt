/* Generate valid-read expectations from the unmodified upstream helper.
 * minimp3 commit ea99364f61c14656440e8d77e9c233ccf3124633 (CC0-1.0).
 * This file is a development oracle, never a MoonBit runtime dependency.
 */
#include <inttypes.h>
#include <stdio.h>

#define MINIMP3_IMPLEMENTATION
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#include "../third_party/minimp3/minimp3.h"

int main(void)
{
    for (int seed = 0; seed < 4; ++seed)
    {
        uint8_t bytes[8];
        for (int i = 0; i < 8; ++i)
            bytes[i] = (uint8_t)(seed * 83 + i * 61);
        for (int offset = 0; offset < 8; ++offset)
        {
            for (int width = 1; width <= 32; ++width)
            {
                bs_t reader;
                bs_init(&reader, bytes, (int)sizeof(bytes));
                if (offset > 0)
                    (void)get_bits(&reader, offset);
                /* All reads are within bytes. Even at width 32, the largest
                 * left shift in get_bits is 32 + 7 - 8 = 31, on uint32_t.
                 * We deliberately never exercise upstream's zero-bit EOF or
                 * out-of-bounds behavior: MoonBit defines safer semantics.
                 */
                uint32_t value = get_bits(&reader, width);
                if (reader.pos != offset + width)
                    return 1;
                printf("%" PRIu32 "\n", value);
            }
        }
    }
    return 0;
}
