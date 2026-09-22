"""Redact local paths and process addresses from persisted diagnostics."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def normalized(text):
    for path, replacement in ((ROOT, "<ROOT>"), (Path.home(), "<HOME>")):
        for spelling in {str(path), path.as_posix(), str(path).replace("\\", "\\\\")}:
            text = text.replace(spelling, replacement)
    # Tool errors can mention installations or temporary files outside the repo.
    text = re.sub(r"(?i)(?<![\w>])(?:[a-z]:[\\/]|\\\\[\w.-]+[\\/])[^\r\n'\"<>]*", "<PATH>", text)
    text = re.sub(r"(?<![:/\w])/(?:home|Users|tmp|private|opt|usr|var|mnt)/[^\r\n'\"<>]*", "<PATH>", text)
    return re.sub(r"(?<= @ )(?:0x)?[0-9a-fA-F]+", "<address>", text)
