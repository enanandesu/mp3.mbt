/* Reference-only driver. No decoder implementation is changed.
 * minimp3 ea99364f61c14656440e8d77e9c233ccf3124633:
 * minimp3_test.c decode_file; minimp3.h mp3dec_decode_frame;
 * minimp3_ex.h mp3dec_load_buf / mp3dec_check_vbrtag / mp3dec_skip_id3.
 * raw keeps every decoded frame; gapless is ONLY a diagnostic reference.
 */
#include <stdio.h>
#include <stdlib.h>
#include <limits.h>
#include <string.h>
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_NO_STDIO
#include "../third_party/minimp3/minimp3_ex.h"

static void fail(const char *message) { fprintf(stderr, "%s\n", message); exit(2); }

/* Explicit little-endian serialization; independent of host endianness. */
static void write_pcm(FILE *out, const mp3d_sample_t *pcm, size_t n) {
    for (size_t i = 0; i < n; ++i) {
#if defined(MINIMP3_FLOAT_OUTPUT) && !defined(REFERENCE_CONVERT_S16)
        uint32_t word;
        memcpy(&word, pcm + i, 4);
        unsigned char bytes[4] = {word & 255, (word >> 8) & 255, (word >> 16) & 255, word >> 24};
        if (fwrite(bytes, 1, 4, out) != 4) fail("PCM write failed");
#else
#ifdef REFERENCE_CONVERT_S16
        int16_t converted;
        mp3dec_f32_to_s16(pcm + i, &converted, 1);
        uint16_t word = (uint16_t)converted;
#else
        uint16_t word = (uint16_t)pcm[i];
#endif
        unsigned char bytes[2] = {word & 255, word >> 8};
        if (fwrite(bytes, 1, 2, out) != 2) fail("PCM write failed");
#endif
    }
}

int main(int argc, char **argv) {
    if (argc != 5 || (strcmp(argv[1], "raw") && strcmp(argv[1], "gapless")))
        fail("usage: reference_decode raw|gapless input output.pcm output.json");
    FILE *in = fopen(argv[2], "rb");
    if (!in) fail("input open failed");
    if (fseek(in, 0, SEEK_END)) fail("input seek failed");
    long size = ftell(in);
    if (size < 0 || size > 64 * 1024 * 1024) fail("input exceeds 64 MiB reference limit");
    rewind(in);
    uint8_t *buffer = calloc((size_t)size + 16, 1);
    if (!buffer || fread(buffer, 1, size, in) != (size_t)size) fail("input read failed");
    fclose(in);
    const uint8_t *audio = buffer;
    size_t audio_size = size;
    mp3dec_skip_id3(&audio, &audio_size);
    size_t tag_prefix = (size_t)(audio - buffer);
    size_t tag_suffix = size - tag_prefix - audio_size;
    int free_bytes = 0, first_frame_bytes = 0;
    int offset = mp3d_find_frame(audio, (int)audio_size, &free_bytes, &first_frame_bytes);
    uint32_t vbr_frames = 0;
    int delay = 0, padding = 0, vbr = 0, first_samples = 0;
    if (first_frame_bytes && offset + first_frame_bytes <= (int)audio_size) {
        const uint8_t *h = audio + offset;
        first_samples = hdr_frame_samples(h);
        vbr = mp3dec_check_vbrtag(h, first_frame_bytes, &vbr_frames, &delay, &padding);
    }
    FILE *out = fopen(argv[3], "wb");
    if (!out) fail("PCM open failed");
    mp3dec_t dec;
    memset(&dec, 0, sizeof(dec));
    mp3dec_init(&dec);
    size_t samples = 0, decoded_frames = 0, skipped = 0, trailing = 0, zero_frames = 0;
    int hz = 0, channels = 0;
    if (!strcmp(argv[1], "gapless")) {
        mp3dec_file_info_t info;
        int result = mp3dec_load_buf(&dec, buffer, size, &info, NULL, NULL);
        if (result) fail("mp3dec_load_buf failed");
        hz = info.hz; channels = info.channels; samples = info.samples;
        write_pcm(out, info.buffer, info.samples);
        free(info.buffer);
    } else {
        size_t pos = 0;
        while (pos < audio_size) {
            mp3dec_frame_info_t info = {0};
            mp3d_sample_t pcm[MINIMP3_MAX_SAMPLES_PER_FRAME];
            int n = mp3dec_decode_frame(&dec, audio + pos, (int)(audio_size - pos), pcm, &info);
            if (info.frame_bytes <= 0 || info.hz == 0) { trailing = audio_size - pos; break; }
            if ((size_t)info.frame_bytes > audio_size - pos) fail("reference consumed beyond input");
            if (n) {
                if (hz && (hz != info.hz || channels != info.channels)) {
                    fprintf(stderr, "stream format changed at byte %llu: %d Hz/%d ch -> %d Hz/%d ch\n",
                        (unsigned long long)pos, hz, channels, info.hz, info.channels);
                    fail("project contract rejects changing sample rate or channel count");
                }
                hz = info.hz; channels = info.channels;
                write_pcm(out, pcm, (size_t)n * channels);
                samples += (size_t)n * channels;
                decoded_frames++;
            } else { zero_frames++; }
            skipped += info.frame_offset;
            pos += info.frame_bytes;
        }
    }
    if (fclose(out)) fail("PCM close failed");
    FILE *meta = fopen(argv[4], "w");
    if (!meta) fail("metadata open failed");
#if defined(MINIMP3_FLOAT_OUTPUT) && !defined(REFERENCE_CONVERT_S16)
    const char *format = "f32le";
#else
    const char *format = "s16le";
#endif
    fprintf(meta, "{\"format\":\"%s\",\"sample_rate\":%d,\"channels\":%d,"
        "\"sample_count\":%llu,\"frames_per_channel\":%llu,\"decoded_frames\":%llu,"
        "\"skipped_bytes\":%llu,\"trailing_bytes\":%llu,\"zero_sample_frames\":%llu,"
        "\"tag_prefix_bytes\":%llu,\"tag_suffix_bytes\":%llu,\"vbr_tag\":%d,"
        "\"vbr_frames\":%u,\"delay\":%d,\"padding\":%d,\"first_frame_samples\":%d}\n",
        format, hz, channels, (unsigned long long)samples,
        (unsigned long long)(channels ? samples / channels : 0),
        (unsigned long long)decoded_frames, (unsigned long long)skipped,
        (unsigned long long)trailing, (unsigned long long)zero_frames,
        (unsigned long long)tag_prefix, (unsigned long long)tag_suffix,
        vbr, vbr_frames, delay, padding, first_samples);
    if (fclose(meta)) fail("metadata close failed");
    free(buffer);
    return 0;
}
