"""Strict PCM comparator. No alignment search, cropping, or resampling.

Samples are normalized by 32768 for s16le; floats are already normalized.
PSNR uses the upstream minimp3_test.c full scale 32767/32768 convention,
but divides squared error by the actual compared sample count.
"""
import argparse
import array
import json
import math
from pathlib import Path
import sys


def read_pcm(path, fmt):
    if fmt not in ("s16le", "f32le"):
        raise ValueError(f"unsupported PCM format: {fmt}")
    data = Path(path).read_bytes()
    width = 2 if fmt == "s16le" else 4
    if len(data) % width:
        raise ValueError("partial PCM sample")
    samples = array.array("h" if width == 2 else "f")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    return [v / 32768 if width == 2 else float(v) for v in samples]


def compare(reference, candidate, reference_meta, candidate_meta, *,
            min_psnr_db=96.0, max_rmse=None, max_abs_error=None):
    for meta, pcm in ((reference_meta, reference), (candidate_meta, candidate)):
        if meta.get("channels") not in (1, 2) or meta.get("sample_rate", 0) <= 0:
            return {"passed": False, "reason": "invalid_metadata"}
        if len(pcm) != meta.get("sample_count") or len(pcm) % meta["channels"]:
            return {"passed": False, "reason": "metadata_sample_count"}
    for field in ("channels", "sample_rate", "sample_count"):
        if reference_meta[field] != candidate_meta[field]:
            return {"passed": False, "reason": field,
                    "reference": reference_meta[field], "candidate": candidate_meta[field]}
    return compare_samples(reference, candidate, min_psnr_db=min_psnr_db,
                           max_rmse=max_rmse, max_abs_error=max_abs_error)


def compare_samples(reference, candidate, *, min_psnr_db=96.0,
                    max_rmse=None, max_abs_error=None):
    """Compare a serialized PCM extent after the caller verifies frame metadata.

    This also supports mixed-channel streams without inventing one stream-wide
    channel count. No alignment, cropping, resampling, or threshold changes.
    """
    if len(reference) != len(candidate):
        return {"passed": False, "reason": "sample_count",
                "reference": len(reference), "candidate": len(candidate)}
    if not reference:
        return {"passed": False, "reason": "empty_pcm"}
    if any(not math.isfinite(x) for pcm in (reference, candidate) for x in pcm):
        return {"passed": False, "reason": "nonfinite_pcm"}
    errors = [abs(a - b) for a, b in zip(reference, candidate)]
    rmse = math.sqrt(math.fsum(e * e for e in errors) / len(errors))
    maximum = max(errors)
    psnr = None if rmse == 0 else 20 * math.log10((32767 / 32768) / rmse)
    passed = (psnr is None or psnr >= min_psnr_db)
    if max_rmse is not None:
        passed = passed and rmse <= max_rmse
    if max_abs_error is not None:
        passed = passed and maximum <= max_abs_error
    return {"passed": passed, "reason": "ok" if passed else "numeric_error",
            "sample_count": len(reference), "rmse": rmse,
            "max_abs_error": maximum, "psnr_db": psnr, "exact": rmse == 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("reference_meta", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("candidate_meta", type=Path)
    parser.add_argument("--min-psnr-db", type=float, default=96)
    parser.add_argument("--max-rmse", type=float)
    parser.add_argument("--max-abs-error", type=float)
    args = parser.parse_args()
    rm = json.loads(args.reference_meta.read_text())
    cm = json.loads(args.candidate_meta.read_text())
    result = compare(read_pcm(args.reference, rm["format"]),
                     read_pcm(args.candidate, cm["format"]), rm, cm,
                     min_psnr_db=args.min_psnr_db, max_rmse=args.max_rmse,
                     max_abs_error=args.max_abs_error)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
