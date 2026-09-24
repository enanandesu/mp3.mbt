"""Corroborate 8 kHz mixed PCM with a narrowly patched independent decoder.

Download the hash-pinned mpg123 1.33.7 source and build its generic float path.
Only the 8 kHz antialias extent and mixed IMDCT prefix are corrected. This is
explicitly NOT agreement with an unmodified decoder. LGPL source, builds and
PCM remain under ignored target/. No execution report is written.

Requires the project toolchain, make, and Git Bash on Windows (or bash on Unix).
The 16 acceptance cases exclude combined MS+intensity: mpg123's mixed intensity
routine still assumes eight long bands for LSF. Existing compatibility tests
cover that combination through the primary/reference-specific paths.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

from diagnostic_text import normalized
from pcm_compare import compare, read_pcm
from validate_compatibility import lsf_syntax
from validate_mpeg1 import ROOT, build_native_adapter
from verify_environment import verify

VERSION = "1.33.7"
ARCHIVE = f"mpg123-{VERSION}.tar.bz2"
URL = f"https://www.mpg123.de/download/{ARCHIVE}"
SHA256 = "31d0e35a4ca567ec9b5ebda6c3062bb4435d6d3eacd6ef0d95cadd7854dc03ee"
OUT = ROOT / "target/mixed-independent"
MODES = ((0, 0), (1, 0), (1, 1), (2, 0))

DRIVER = r'''
#include <stdio.h>
#include "mpg123.h"
int main(int argc, char **argv) {
    if(argc != 3 || mpg123_init() != MPG123_OK) return 2;
    int error;
    mpg123_handle *decoder = mpg123_new("generic", &error);
    if(!decoder) return 3;
    if(mpg123_param(decoder, MPG123_REMOVE_FLAGS, MPG123_GAPLESS, 0) != MPG123_OK
       || mpg123_param(decoder, MPG123_ADD_FLAGS,
           MPG123_FORCE_FLOAT | MPG123_QUIET, 0) != MPG123_OK) return 4;
    if(mpg123_open(decoder, argv[1]) != MPG123_OK) return 5;
    FILE *output = fopen(argv[2], "wb");
    if(!output) return 6;
    unsigned char buffer[16384];
    size_t count, samples = 0;
    int status, channels = 0, encoding;
    long rate = 0;
    do {
        status = mpg123_read(decoder, buffer, sizeof(buffer), &count);
        if(status == MPG123_NEW_FORMAT) {
            if(mpg123_getformat(decoder, &rate, &channels, &encoding) != MPG123_OK
               || encoding != MPG123_ENC_FLOAT_32 || channels != 2) return 7;
        }
        if(count % 4 || (count && fwrite(buffer, 1, count, output) != count)) return 8;
        samples += count / 4;
    } while(status == MPG123_OK || status == MPG123_NEW_FORMAT);
    if(status != MPG123_DONE || fclose(output)) return 9;
    printf("%ld %d %zu\n", rate, channels, samples);
    mpg123_close(decoder);
    mpg123_delete(decoder);
    mpg123_exit();
    return 0;
}
'''


def run(command, *, cwd=ROOT, **kwargs):
    result = subprocess.run(list(map(str, command)), cwd=cwd, capture_output=True,
                            text=True, errors="replace", **kwargs)
    if result.returncode:
        raise RuntimeError(normalized(result.stdout + result.stderr))
    return result.stdout.strip()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Pinned mpg123 patch location changed")
    return text.replace(old, new, 1)


def patch_layer3(source):
    """Change only antialias and mixed IMDCT operations, retaining source license."""
    path = source / "src/libmpg123/layer3.c"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text,
        "III_antialias(real xr[SBLIMIT][SSLIMIT],struct gr_info_s *gr_info)",
        "III_antialias(real xr[SBLIMIT][SSLIMIT],struct gr_info_s *gr_info, int sfreq)")
    text = replace_once(text, "sblim = 1;", "sblim = sfreq == 8 ? 3 : 1;")
    text = replace_once(text, "III_antialias(hybridIn[ch],gr_info);",
                        "III_antialias(hybridIn[ch],gr_info,sfreq);")
    start = text.index("\t\tsb = 2;", text.index("static void III_hybrid"))
    end = text.index("\n\t}", start)
    body = text[start:end]
    # Reuse the original pair of DCT calls and pointer advances. The only
    # semantic change repeats the pair for the two extra 8 kHz long subbands.
    body = replace_once(body, "\t\tsb = 2;\n", "")
    body = replace_once(body, "fsIn[0]", "fsIn[sb]")
    body = replace_once(body, "fsIn[1]", "fsIn[sb+1]")
    body = "\n".join("\t" + line for line in body.splitlines())
    replacement = ("\t\tconst size_t mixed_bands = fr->hdr.sampling_frequency == 8 ? 4 : 2;\n"
                   "\t\tfor(sb = 0; sb < mixed_bands; sb += 2)\n\t\t{\n"
                   + body + "\n\t\t}")
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8", newline="\n")


def bash_executable(override):
    if override:
        return Path(override).resolve()
    # Windows' system32/bash may invoke WSL. Prefer Git's own Windows shell.
    git = shutil.which("git")
    if os.name == "nt" and git:
        candidate = Path(git).resolve().parents[1] / "bin/bash.exe"
        if candidate.is_file():
            return candidate
    bash = shutil.which("bash")
    if not bash:
        raise RuntimeError("bash is required; supply --bash")
    return Path(bash).resolve()


def make_shell(bash):
    shell = bash.parent / "sh.exe" if os.name == "nt" else bash
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetShortPathNameW(str(shell), buffer, len(buffer)):
            raise RuntimeError("Could not resolve the shell path for make")
        shell = Path(buffer.value)
    if " " in str(shell):
        raise RuntimeError("make needs a shell path without spaces")
    return shell.as_posix()


def build_reference(bash):
    OUT.mkdir(parents=True, exist_ok=True)
    archive = OUT / ARCHIVE
    if not archive.exists():
        print(f"Downloading hash-pinned mpg123 {VERSION}", flush=True)
        with urllib.request.urlopen(URL, timeout=60) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("mpg123 source archive SHA-256 mismatch")
    source_parent = OUT / "source"
    source_parent.mkdir(exist_ok=True)
    with tarfile.open(archive) as bundle:
        # Python's data filter rejects absolute, escaping and unsafe link paths.
        bundle.extractall(source_parent, filter="data")
    source = source_parent / f"mpg123-{VERSION}"
    patch_layer3(source)
    build = OUT / "build"
    build.mkdir(exist_ok=True)
    options = ["--disable-components", "--enable-libmpg123", "--disable-shared",
               "--enable-static", "--with-cpu=generic", "--disable-layer1",
               "--disable-layer2", "--disable-network", "--disable-ipv6"]
    if os.name == "nt":
        machine = run(["gcc", "-dumpmachine"])
        options[:0] = [f"--build={machine}", f"--host={machine}"]
    config = build / "config.status"
    configuration = config.read_text(encoding="utf-8", errors="replace") if config.exists() else ""
    if not (build / "Makefile").exists() or any(option not in configuration for option in options):
        print("Configuring the test-only generic mpg123 library", flush=True)
        run([bash, (source / "configure").as_posix(), *options], cwd=build)
    print("Building the test-only library with two explicit 8 kHz corrections", flush=True)
    run(["make", "-j2", f"SHELL={make_shell(bash)}",
         "CFLAGS=-O2 -ffp-contract=off -fno-fast-math"], cwd=build)
    driver = OUT / "driver.c"
    driver.write_text(DRIVER, encoding="utf-8", newline="\n")
    executable = OUT / "patched-mpg123.exe"
    command = ["gcc", "-std=c99", "-O2", driver, "-I", source / "src/include",
               build / "src/libmpg123/.libs/libmpg123.a", "-lm"]
    if os.name == "nt":
        command.append("-lshlwapi")
    run([*command, "-o", executable])
    return executable


def metadata(text):
    rate, channels, count = map(int, text.split())
    return {"sample_rate": rate, "channels": channels, "sample_count": count}


def validate(reference, moon):
    policy = json.loads((ROOT / "tests/reference_policy.json").read_text())["f32"]
    cases = [(rate, extension, shift, False) for rate in (8000, 12000, 24000)
             for extension, shift in MODES]
    cases += [(8000, extension, shift, True) for extension, shift in MODES]
    worst_absolute = worst_rmse = 0.0
    for rate, extension, shift, free in cases:
        name = f"mixed-{rate}-mode{extension}-scale{shift}-{'free' if free else 'cbr'}"
        source = OUT / (name + ".mp3")
        source.write_bytes(lsf_syntax(rate, extension, shift, free))
        expected_path = OUT / (name + "-reference.pcm")
        actual_path = OUT / (name + "-moon.pcm")
        expected_meta = metadata(run([reference, source, expected_path]))
        actual_meta = metadata(run([moon], env=dict(os.environ,
            MP3_VALIDATION_INPUT=str(source), MP3_VALIDATION_OUTPUT=str(actual_path))))
        required = {"sample_rate": rate, "channels": 2, "sample_count": 9 * 576 * 2}
        if expected_meta != required or actual_meta != required:
            raise RuntimeError(f"{name}: wrong format or raw PCM extent")
        expected = read_pcm(expected_path, "f32le")
        actual = read_pcm(actual_path, "f32le")
        result = compare(expected, actual, expected_meta, actual_meta, **policy)
        if not result["passed"]:
            raise RuntimeError(f"{name}: {result}")
        worst_absolute = max(worst_absolute, result["max_abs_error"])
        worst_rmse = max(worst_rmse, result["rmse"])
        print(f"PASS {name}: max={result['max_abs_error']:.3g}, rmse={result['rmse']:.3g}")
    print(f"Passed {len(cases)} cases; max error {worst_absolute:.3g}, RMSE {worst_rmse:.3g}.")
    print("Scope: patched independent mpg123; combined MS+intensity is not an acceptance reference.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bash", help="Bash executable used to configure mpg123")
    args = parser.parse_args()
    verify()
    reference = build_reference(bash_executable(args.bash))
    moon = build_native_adapter(api="decode_all", output_root=OUT / "moon-validation")
    validate(reference, moon)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(normalized(str(error))) from None
    finally:
        # Autoconf records host/environment details here. It is not needed by
        # subsequent builds; keep diagnostics on the terminal, never as an
        # environment archive on disk.
        diagnostic = OUT / "build/config.log"
        if diagnostic.exists() and diagnostic.resolve().is_relative_to(OUT.resolve()):
            diagnostic.unlink()
