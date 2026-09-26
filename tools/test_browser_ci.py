"""Run the browser UI smoke test against a temporary loopback HTTP server."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
from threading import Thread


ROOT = Path(__file__).resolve().parents[1]


def main():
    env = os.environ.copy()
    if env.get("BROWSER_PATH"):
        env["EDGE_PATH"] = env["BROWSER_PATH"]
    if os.name != "nt" and not env.get("EDGE_PATH"):
        browser = shutil.which("google-chrome") or shutil.which("chromium")
        if not browser:
            raise RuntimeError("Install Chromium or set EDGE_PATH/BROWSER_PATH for browser UI checks")
        env["EDGE_PATH"] = browser
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    )
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/examples/browser/"
        subprocess.run(["node", "tools/test_browser_ui.mjs", url], cwd=ROOT,
                       env=env, check=True, timeout=180)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


if __name__ == "__main__":
    main()
