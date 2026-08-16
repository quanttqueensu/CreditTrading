#!/usr/bin/env python3
"""Build the team PDFs from the markdown sources in docs/.

Run it from anywhere:

    python3 docs/build_pdfs.py

It turns each markdown file into HTML with pandoc, styles it with
docs/print.css, then prints it through headless Chrome. Chrome is driven over
the DevTools Protocol rather than the plain --print-to-pdf flag, because that
is the only way to get a proper page-number footer.

Edit the markdown, re-run this, commit both. The PDFs are build output, not
something to edit by hand.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

import websocket

DOCS = Path(__file__).resolve().parent
CSS = DOCS / "print.css"
OUT = DOCS / "pdf"

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# (markdown file, output pdf, whether to build a table of contents)
JOBS = [
    ("INFRASTRUCTURE.md", "QUANTT-Infrastructure.pdf", True),
    ("PROJECT_INTRO.md", "QUANTT-Project-Intro.pdf", False),
    ("SUMMER_2026_SUMMARY.md", "QUANTT-Summer-2026-Summary.pdf", True),
]

FOOTER = """
<div style="width:100%; font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;
            font-size:7.5pt; color:#8A9096; padding:0 0.85in;
            display:flex; justify-content:space-between; letter-spacing:0.06em;">
  <span style="text-transform:uppercase;">QUANTT Credit Trading</span>
  <span><span class="pageNumber"></span></span>
</div>
"""

HEADER = '<div style="display:none"></div>'


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def build_html(md_path, html_path, toc):
    cmd = [
        "pandoc", str(md_path),
        "--from", "markdown+pipe_tables+backtick_code_blocks",
        "--to", "html5",
        "--standalone",
        "--template", str(DOCS / "template.html"),
        "--css", CSS.name,
        "--metadata", "pagetitle=" + md_path.stem,
    ]
    if toc:
        cmd += ["--toc", "--toc-depth=2"]
    subprocess.run(cmd + ["-o", str(html_path)], check=True)


def print_pdf(html_path, pdf_path, port, profile):
    proc = subprocess.Popen(
        [CHROME, "--headless", "--disable-gpu", "--no-first-run",
         f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         "--remote-allow-origins=*",
         "--run-all-compositor-stages-before-draw", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    ws_url = None
    for _ in range(80):
        try:
            data = json.loads(urlopen(f"http://127.0.0.1:{port}/json/version").read())
            ws_url = data["webSocketDebuggerUrl"]
            break
        except Exception:
            time.sleep(0.25)
    if not ws_url:
        proc.kill()
        raise RuntimeError("Chrome did not expose a debugging socket")

    ws = websocket.create_connection(ws_url, timeout=60)
    n = [0]

    def send(method, params=None, sid=None):
        n[0] += 1
        msg = {"id": n[0], "method": method, "params": params or {}}
        if sid:
            msg["sessionId"] = sid
        ws.send(json.dumps(msg))
        while True:
            reply = json.loads(ws.recv())
            if reply.get("id") == n[0]:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})

    target = send("Target.createTarget", {"url": "about:blank"})["targetId"]
    sid = send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
    send("Page.enable", {}, sid)
    send("Page.navigate", {"url": html_path.as_uri()}, sid)
    time.sleep(2.5)  # let fonts settle before pagination

    result = send("Page.printToPDF", {
        "printBackground": True,
        "paperWidth": 8.5,
        "paperHeight": 11,
        "marginTop": 0.85,
        "marginBottom": 0.85,
        "marginLeft": 1.08,
        "marginRight": 1.08,
        "displayHeaderFooter": True,
        "headerTemplate": HEADER,
        "footerTemplate": FOOTER,
        "preferCSSPageSize": False,
    }, sid)

    import base64
    pdf_path.write_bytes(base64.b64decode(result["data"]))

    ws.close()
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main():
    if not Path(CHROME).exists():
        sys.exit(f"Chrome not found at {CHROME}")
    OUT.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="quantt-pdf-"))
    shutil.copy(CSS, work / CSS.name)

    try:
        for md_name, pdf_name, toc in JOBS:
            md_path = DOCS / md_name
            if not md_path.exists():
                print(f"skip {md_name} (missing)")
                continue
            html_path = work / (md_path.stem + ".html")
            build_html(md_path, html_path, toc)
            profile = work / ("profile-" + md_path.stem)
            print_pdf(html_path, OUT / pdf_name, free_port(), profile)
            size = (OUT / pdf_name).stat().st_size
            print(f"built {pdf_name}  ({size/1024:.0f} KB)")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
