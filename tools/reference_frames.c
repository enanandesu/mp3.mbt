/* Frame-preserving raw reference for compatibility acceptance.
 * Calls unmodified minimp3 ea99364f61c14656440e8d77e9c233ccf3124633.
 * Unlike the strict reference_decode adapter, channel transitions are retained.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_NO_STDIO
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#define MINIMP3_FLOAT_OUTPUT
#include "../third_party/minimp3/minimp3_ex.h"

static void fail(const char *message) { fprintf(stderr, "%s\n", message); exit(2); }
int main(int argc, char **argv) {
    if (argc != 4) fail("usage: reference_frames input output.pcm output.json");
    FILE *in = fopen(argv[1], "rb");
    if (!in || fseek(in, 0, SEEK_END)) fail("input open/seek failed");
    long size = ftell(in);
    if (size < 0 || size > 64 * 1024 * 1024 || fseek(in, 0, SEEK_SET)) fail("input size/seek failed");
    unsigned char *buffer = calloc((size_t)size + 16, 1);
    if (!buffer || fread(buffer, 1, size, in) != (size_t)size || fclose(in)) fail("input read failed");
    const unsigned char *audio = buffer;
    size_t length = (size_t)size;
    mp3dec_skip_id3(&audio, &length);
    FILE *pcm = fopen(argv[2], "wb"), *meta = fopen(argv[3], "w");
    if (!pcm || !meta) fail("output open failed");
    mp3dec_t decoder = {0};
    mp3dec_init(&decoder);
    size_t pos = 0, count = 0, skipped = 0, zero = 0, first = 1;
    fprintf(meta, "{\"frames\":[");
    while (pos < length) {
        mp3dec_frame_info_t info = {0};
        float samples[MINIMP3_MAX_SAMPLES_PER_FRAME];
        int n = mp3dec_decode_frame(&decoder, audio + pos, (int)(length-pos), samples, &info);
        if (!info.hz || info.frame_bytes <= 0) break;
        if ((size_t)info.frame_bytes > length-pos) fail("reference overread");
        skipped += info.frame_offset;
        if (n) {
            size_t extent = (size_t)n * info.channels;
            fprintf(meta, "%s{\"source_offset\":%llu,\"sample_rate\":%d,\"channels\":%d,\"sample_count\":%llu}",
                first ? "" : ",", (unsigned long long)(audio-buffer+pos+info.frame_offset),
                info.hz, info.channels, (unsigned long long)extent);
            first = 0;
            for (size_t i=0; i<extent; ++i) {
                uint32_t word;
                memcpy(&word, samples+i, 4);
                unsigned char bytes[4] = {word&255, (word>>8)&255, (word>>16)&255, word>>24};
                if (fwrite(bytes,1,4,pcm)!=4) fail("PCM write failed");
            }
            count += extent;
        } else { ++zero; }
        pos += info.frame_bytes;
    }
    fprintf(meta, "],\"sample_count\":%llu,\"skipped_bytes\":%llu,\"zero_sample_frames\":%llu,\"trailing_bytes\":%llu}\n",
        (unsigned long long)count, (unsigned long long)skipped, (unsigned long long)zero, (unsigned long long)(length-pos));
    if (fclose(pcm) || fclose(meta)) fail("output close failed");
    free(buffer);
    return 0;
}
