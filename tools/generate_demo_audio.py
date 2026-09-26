"""Generate the original synthesized chime bundled with the browser example.

Requires FFmpeg with libmp3lame. Source code and generated audio: Apache-2.0.
The MP3 is checked in, so using the demo does not require FFmpeg.
"""

import array
import math
from pathlib import Path
import subprocess
import sys
import wave


ROOT = Path(__file__).resolve().parents[1]
RATE = 44100
DURATION = 3


def main():
    work = ROOT / "target" / "demo-audio"
    work.mkdir(parents=True, exist_ok=True)
    pcm = array.array("h")
    # Three overlapping notes with a soft attack and exponential decay.
    notes = [(0.15, 523.25, -0.35), (0.75, 659.25, 0.0), (1.35, 783.99, 0.35)]
    for frame in range(RATE * DURATION):
        time = frame / RATE
        channels = [0.0, 0.0]
        for start, frequency, pan in notes:
            age = time - start
            if age < 0:
                continue
            envelope = min(1.0, age / 0.015) * math.exp(-3.5 * age)
            tone = (math.sin(2 * math.pi * frequency * age)
                    + 0.2 * math.sin(4 * math.pi * frequency * age))
            for channel, weight in enumerate([(1 - pan) / 2, (1 + pan) / 2]):
                channels[channel] += 0.45 * envelope * tone * weight
        fade = min(1.0, (DURATION - time) / 0.1)
        pcm.extend(round(max(-1.0, min(1.0, value * fade)) * 32767)
                   for value in channels)
    if sys.byteorder != "little":
        pcm.byteswap()
    wav_path = work / "source.wav"
    with wave.open(str(wav_path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(pcm.tobytes())
    destination = ROOT / "examples" / "browser" / "sample.mp3"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(wav_path), "-map_metadata", "-1",
        "-c:a", "libmp3lame", "-b:a", "128k", "-write_xing", "0",
        "-id3v2_version", "0", str(destination),
    ], check=True)
    print(f"Generated {destination.relative_to(ROOT)} ({destination.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
