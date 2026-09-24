/* File and RIFF I/O only. MP3 decoding and PCM quantization run in MoonBit. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#include <share.h>
#include <sys/stat.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

static FILE *source;
static FILE *destination;
static char *destination_path;
static uint32_t data_bytes;
static uint32_t output_rate;
static uint16_t output_channels;
static int write_failed;

static char *copy_path(const uint8_t *bytes, int32_t length) {
    if (length <= 0 || memchr(bytes, 0, (size_t)length)) return NULL;
    char *path = malloc((size_t)length + 1);
    if (!path) return NULL;
    memcpy(path, bytes, (size_t)length);
    path[length] = 0;
    return path;
}

static FILE *open_path(const char *path, const char *mode) {
#ifdef _WIN32
    int path_size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
    int mode_size = MultiByteToWideChar(CP_UTF8, 0, mode, -1, NULL, 0);
    if (!path_size || !mode_size) return NULL;
    wchar_t *wide_path = malloc((size_t)path_size * sizeof(wchar_t));
    wchar_t *wide_mode = malloc((size_t)mode_size * sizeof(wchar_t));
    if (!wide_path || !wide_mode) {
        free(wide_path);
        free(wide_mode);
        return NULL;
    }
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide_path, path_size);
    MultiByteToWideChar(CP_UTF8, 0, mode, -1, wide_mode, mode_size);
    FILE *file = _wfopen(wide_path, wide_mode);
    free(wide_path);
    free(wide_mode);
    return file;
#else
    return fopen(path, mode);
#endif
}

static FILE *create_path(const char *path) {
#ifdef _WIN32
    int size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
    if (!size) return NULL;
    wchar_t *wide = malloc((size_t)size * sizeof(wchar_t));
    if (!wide) return NULL;
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide, size);
    int fd = -1;
    int result = _wsopen_s(&fd, wide, _O_WRONLY | _O_CREAT | _O_EXCL | _O_BINARY,
                           _SH_DENYRW, _S_IREAD | _S_IWRITE);
    free(wide);
    if (result) return NULL;
    FILE *file = _fdopen(fd, "wb");
    if (!file) _close(fd);
    return file;
#else
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0666);
    if (fd < 0) return NULL;
    FILE *file = fdopen(fd, "wb");
    if (!file) close(fd);
    return file;
#endif
}

static int remove_path(const char *path) {
#ifdef _WIN32
    int size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
    if (!size) return -1;
    wchar_t *wide = malloc((size_t)size * sizeof(wchar_t));
    if (!wide) return -1;
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide, size);
    int result = _wremove(wide);
    free(wide);
    return result;
#else
    return remove(path);
#endif
}

static int write_u16(uint16_t value) {
    unsigned char bytes[2] = {(unsigned char)value, (unsigned char)(value >> 8)};
    return fwrite(bytes, 1, 2, destination) == 2 ? 0 : -1;
}

static int write_u32(uint32_t value) {
    return write_u16((uint16_t)value) || write_u16((uint16_t)(value >> 16));
}

static int write_header(uint32_t rate, uint16_t channels, uint32_t size) {
    return fwrite("RIFF", 1, 4, destination) != 4 ||
           write_u32(size + 36) ||
           fwrite("WAVEfmt ", 1, 8, destination) != 8 ||
           write_u32(16) || write_u16(1) || write_u16(channels) ||
           write_u32(rate) || write_u32(rate * channels * 2) ||
           write_u16((uint16_t)(channels * 2)) || write_u16(16) ||
           fwrite("data", 1, 4, destination) != 4 || write_u32(size);
}

int32_t wav_cli_open_input(const uint8_t *bytes, int32_t length) {
    char *path = copy_path(bytes, length);
    if (!path) return -1;
    source = open_path(path, "rb");
    free(path);
    return source ? 0 : -1;
}

int32_t wav_cli_read_byte(void) {
    int value = fgetc(source);
    if (value != EOF) return value;
    return ferror(source) ? -2 : -1;
}

int32_t wav_cli_open_output(const uint8_t *bytes, int32_t length,
                            int32_t rate, int32_t channels) {
    if (rate <= 0 || (channels != 1 && channels != 2)) return -1;
    char *path = copy_path(bytes, length);
    if (!path) return -1;
    destination = create_path(path);
    if (!destination) {
        free(path);
        return -1;
    }
    destination_path = path;
    output_rate = (uint32_t)rate;
    output_channels = (uint16_t)channels;
    if (write_header((uint32_t)rate, (uint16_t)channels, 0)) {
        write_failed = 1;
        return -1;
    }
    return 0;
}

int32_t wav_cli_write_sample(int32_t value) {
    if (write_failed || data_bytes > UINT32_MAX - 38 ||
        write_u16((uint16_t)value)) {
        write_failed = 1;
        return -1;
    }
    data_bytes += 2;
    return 0;
}

int32_t wav_cli_finish_output(void) {
    if (write_failed || fseek(destination, 0, SEEK_SET) ||
        write_header(output_rate, output_channels, data_bytes) ||
        fflush(destination)) {
        return -1;
    }
    if (fclose(destination)) {
        destination = NULL;
        return -1;
    }
    destination = NULL;
    if (source) fclose(source);
    source = NULL;
    free(destination_path);
    destination_path = NULL;
    return 0;
}

void wav_cli_abort_output(void) {
    if (destination) fclose(destination);
    if (destination_path) remove_path(destination_path);
    if (source) fclose(source);
    free(destination_path);
}

void wav_cli_exit(int32_t status) { exit(status); }
