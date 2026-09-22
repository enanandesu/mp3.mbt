/* Validation-only file adapter. All MP3 decoding runs in MoonBit. */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static unsigned char *input;
static FILE *output;
void validation_fail(void) { exit(2); }
int32_t validation_input_length(void) {
    const char *path = getenv("MP3_VALIDATION_INPUT");
    FILE *f = path ? fopen(path, "rb") : NULL;
    if (!f || fseek(f, 0, SEEK_END)) validation_fail();
    long n = ftell(f);
    if (n < 0 || n > 64 * 1024 * 1024 || fseek(f, 0, SEEK_SET)) validation_fail();
    input = malloc(n ? (size_t)n : 1);
    if (!input || fread(input, 1, (size_t)n, f) != (size_t)n) validation_fail();
    fclose(f);
    path = getenv("MP3_VALIDATION_OUTPUT");
    output = path ? fopen(path, "wb") : NULL;
    if (!output) validation_fail();
    return (int32_t)n;
}
int32_t validation_input_byte(int32_t i) { return input[i]; }
void validation_output_sample(float value) {
    uint32_t word;
    memcpy(&word, &value, sizeof(word));
    unsigned char bytes[4] = {word & 255, (word >> 8) & 255, (word >> 16) & 255, word >> 24};
    if (fwrite(bytes, 1, 4, output) != 4) validation_fail();
}
void validation_close_output(void) {
    if (fclose(output)) validation_fail();
    free(input);
}
