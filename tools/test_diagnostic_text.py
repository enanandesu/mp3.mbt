from pathlib import Path
import unittest

from diagnostic_text import ROOT, normalized


class DiagnosticTextTests(unittest.TestCase):
    def test_project_path_retains_relative_context(self):
        path = ROOT / "tests" / "sample.mp3"
        for spelling in (str(path), path.as_posix(), str(path).replace("\\", "\\\\")):
            result = normalized(spelling)
            self.assertTrue(result.startswith("<ROOT>"))
            self.assertIn("sample.mp3", result)
            self.assertNotIn(str(ROOT), result)

    def test_home_directory_is_removed(self):
        result = normalized(str(Path.home() / "private.wav"))
        self.assertTrue(result.startswith("<HOME>"))
        self.assertNotIn(str(Path.home()), result)

    def test_external_paths_with_spaces_and_unc_are_removed(self):
        paths = [r"Z:\Local Tools\audio.dll", r"C:\Users\Someone Else\private.mp3",
                 r"\\private-server\audio share\source.mp3", "/home/another-user/private.mp3"]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(normalized(f"cannot open '{path}'"), "cannot open '<PATH>'")

    def test_ffmpeg_addresses_are_removed(self):
        self.assertEqual(normalized("[mp3 @ 000001abcdef] bad frame"), "[mp3 @ <address>] bad frame")
        self.assertEqual(normalized("[mp3 @ 0xabcdef] bad frame"), "[mp3 @ <address>] bad frame")

    def test_numerical_results_and_source_urls_are_preserved(self):
        text = "RMSE=1.2e-5 samples=1152 https://github.com/FFmpeg/FFmpeg/blob/e347b4ff31/libavcodec/mpegaudiodec_template.c"
        self.assertEqual(normalized(text), text)


if __name__ == "__main__":
    unittest.main()
