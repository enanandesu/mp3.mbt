"""Ensure hosted regression scope cannot accept compiler or upstream hash drift."""

import copy
import json
import unittest
from unittest.mock import patch

import verify_environment as environment


class ToolchainScopes(unittest.TestCase):
    def setUp(self):
        self.baseline = json.loads(environment.LOCK.read_text(encoding="utf-8"))

    def portable(self, actual):
        with patch.object(environment, "current", return_value=actual), \
                patch.object(environment, "platform_lock", return_value=environment.LOCK):
            return environment.verify_portable_tools()

    def test_portable_records_host_compiler_drift(self):
        actual = copy.deepcopy(self.baseline)
        actual["tools"]["gcc"]["executable_sha256"] = "different-host-compiler"
        report = self.portable(actual)
        self.assertEqual(report["observed_host_tools"]["gcc"]["executable_sha256"],
                         "different-host-compiler")
        self.assertIn("not a full reference environment", report["verification_scope"])

    def test_portable_rejects_every_pinned_tool_drift(self):
        for name in ("moon", "moonc", "moonrun", "moonfmt", "node", "moonbitlang/core"):
            with self.subTest(tool=name):
                actual = copy.deepcopy(self.baseline)
                actual["tools"][name] = {"executable_sha256": "wrong"}
                with self.assertRaisesRegex(RuntimeError, name):
                    self.portable(actual)

    def test_portable_rejects_upstream_or_platform_drift(self):
        for field in ("system", "machine", "upstream_commit", "upstream_files"):
            with self.subTest(field=field):
                actual = copy.deepcopy(self.baseline)
                actual[field] = "wrong"
                with self.assertRaisesRegex(RuntimeError, field):
                    self.portable(actual)

    def test_full_reference_scope_still_rejects_host_drift(self):
        actual = copy.deepcopy(self.baseline)
        actual["tools"]["gcc"]["executable_sha256"] = "different-host-compiler"
        with patch.object(environment, "current", return_value=actual), \
                patch.object(environment, "platform_lock", return_value=environment.LOCK):
            with self.assertRaisesRegex(RuntimeError, "gcc"):
                environment.verify()


if __name__ == "__main__":
    unittest.main()
