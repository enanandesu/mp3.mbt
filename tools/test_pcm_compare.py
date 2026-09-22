import math
import struct
import tempfile
import unittest
from pathlib import Path
from pcm_compare import compare, read_pcm


class ComparatorTests(unittest.TestCase):
    def setUp(self):
        self.pcm = [x for i in range(512)
                    for x in (0.5 * math.sin(i * 0.13), 0.3 * math.cos(i * 0.23))]
        self.meta = {"sample_rate": 44100, "channels": 2, "sample_count": len(self.pcm)}

    def check(self, candidate, meta=None):
        return compare(self.pcm, candidate, self.meta, meta or self.meta)

    def test_exact_match(self):
        self.assertTrue(self.check(self.pcm)["passed"])

    def test_channel_swap(self):
        swapped = [x for i in range(0, len(self.pcm), 2) for x in self.pcm[i:i+2][::-1]]
        self.assertFalse(self.check(swapped)["passed"])

    def test_one_frame_shift_preserving_length(self):
        self.assertFalse(self.check([0.0, 0.0] + self.pcm[:-2])["passed"])

    def test_gain_scaling(self):
        self.assertFalse(self.check([x * 0.99 for x in self.pcm])["passed"])

    def test_tail_deleted(self):
        self.assertEqual(self.check(self.pcm[:-2], {**self.meta, "sample_count": len(self.pcm)-2})["reason"], "sample_count")

    def test_metadata_contract(self):
        for field, value in (("channels", 1), ("sample_rate", 48000)):
            self.assertFalse(self.check(self.pcm, {**self.meta, field: value})["passed"])
        self.assertEqual(self.check(self.pcm[:-2])["reason"], "metadata_sample_count")

    def test_nan_and_infinity_rejected(self):
        for value in (math.nan, math.inf, -math.inf):
            self.assertFalse(self.check([value] + self.pcm[1:])["passed"])

    def test_silence_is_valid_but_empty_is_not(self):
        silence = [0.0] * len(self.pcm)
        self.assertTrue(compare(silence, silence, self.meta, self.meta)["passed"])
        self.assertFalse(compare([], [], {**self.meta, "sample_count": 0}, {**self.meta, "sample_count": 0})["passed"])

    def test_fullscale_psnr_and_actual_denominator(self):
        result = compare([0.0]*4, [1/32768]*4, {**self.meta, "sample_count": 4}, {**self.meta, "sample_count": 4})
        self.assertAlmostEqual(result["psnr_db"], 20 * math.log10(32767))
        self.assertFalse(result["passed"])

    def test_float_thresholds(self):
        candidate = [x + 2e-6 for x in self.pcm]
        self.assertFalse(compare(self.pcm, candidate, self.meta, self.meta, max_rmse=1e-6)["passed"])

    def test_little_endian_read_and_partial_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pcm"
            path.write_bytes(struct.pack("<3h", -32768, 0, 32767))
            self.assertEqual(read_pcm(path, "s16le"), [-1.0, 0.0, 32767/32768])
            path.write_bytes(b"\x00")
            with self.assertRaises(ValueError):
                read_pcm(path, "s16le")


if __name__ == "__main__":
    unittest.main()
