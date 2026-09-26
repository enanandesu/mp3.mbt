"""Exercise archive execution permissions on a real POSIX filesystem."""

import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import setup_ci_linux as installer


@unittest.skipUnless(os.name == "posix", "Requires POSIX execution permissions")
class ExecutablePermissions(unittest.TestCase):
    def setUp(self):
        (installer.ROOT / "target").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="installer-permissions-", dir=installer.ROOT / "target"
        )
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name)
        probe = self.output / "permission-probe"
        probe.write_bytes(b"data")
        probe.chmod(0o600)
        if probe.stat().st_mode & 0o111:
            self.skipTest("Filesystem ignores POSIX modes; use Linux storage, not /mnt/d")
        self.executables = installer.ARCHIVES["moonbit-linux-x86_64.tar.gz"]["executables"]
        self.program = b"#!/bin/sh\nprintf 'installed\\n'\n"
        self.data_files = ("bin/moonlex.wasm", "bin/moonyacc.wasm", "bin/moon_cove.wasm", "README.md")
        archive = self.output / "downloads/tools.tar.gz"
        archive.parent.mkdir()
        with tarfile.open(archive, "w:gz") as target:
            for name in [*self.executables, *self.data_files]:
                content = self.program if name in self.executables else b"data"
                member = tarfile.TarInfo(name)
                member.mode = 0o664
                member.size = len(content)
                target.addfile(member, io.BytesIO(content))
        self.specification = {
            "destination": "moon", "executables": self.executables,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        }

    def install(self):
        with patch.object(installer, "OUT", self.output), patch.object(
            installer.urllib.request, "urlopen", side_effect=AssertionError("Cache should avoid downloads")
        ):
            installer.install("tools.tar.gz", self.specification)

    def assert_tools_run(self):
        for name in self.executables:
            tool = self.output / "moon" / name
            self.assertEqual(tool.read_bytes(), self.program, name)
            self.assertEqual(tool.stat().st_mode & 0o111, 0o111, name)
            result = subprocess.run([str(tool)], capture_output=True, text=True, check=True, timeout=5)
            self.assertEqual(result.stdout, "installed\n", name)
        for name in self.data_files:
            data = self.output / "moon" / name
            self.assertEqual(data.read_bytes(), b"data", name)
            self.assertEqual(data.stat().st_mode & 0o111, 0, name)

    def test_nonexecutable_archive_tools_can_run_after_install(self):
        self.install()
        self.assert_tools_run()

    def test_cached_reinstall_restores_execution_permissions(self):
        self.install()
        for name in self.executables:
            (self.output / "moon" / name).chmod(0o664)
        self.install()
        self.assert_tools_run()


if __name__ == "__main__":
    unittest.main()
