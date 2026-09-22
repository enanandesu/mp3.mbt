/* Test-only oracle for minimp3 tag boundaries. Not linked into MoonBit.
 * Source: ea99364f61c14656440e8d77e9c233ccf3124633/minimp3_ex.h.
 * Disable APEv2 to isolate the explicitly supported ID3v1/TAG+ behavior. */
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#define MINIMP3_NO_STDIO
#define MINIMP3_NOSKIP_APEV2
#include "../third_party/minimp3/minimp3_ex.h"
#include <stdio.h>

static int hex_digit(char value)
{
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

int main(int argc, char **argv)
{
    if (argc != 3 || (strcmp(argv[1], "prefix") && strcmp(argv[1], "tail"))) return 2;
    size_t chars = strlen(argv[2]);
    if (chars % 2 || chars > 1048576) return 2;
    size_t length = chars / 2;
    unsigned char *input = (unsigned char *)malloc(length ? length : 1);
    if (!input) return 3;
    for (size_t i = 0; i < length; ++i) {
        int hi = hex_digit(argv[2][2 * i]);
        int lo = hex_digit(argv[2][2 * i + 1]);
        if (hi < 0 || lo < 0) { free(input); return 2; }
        input[i] = (unsigned char)((hi << 4) | lo);
    }
    if (!strcmp(argv[1], "prefix")) {
        printf("%zu\n", mp3dec_skip_id3v2(input, length));
    } else {
        size_t remaining = length;
        mp3dec_skip_id3v1(input, &remaining);
        printf("%zu\n", length - remaining);
    }
    free(input);
    return 0;
}
