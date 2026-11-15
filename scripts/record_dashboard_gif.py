"""Record docs/img/dashboard-demo.gif from a local Streamlit process.

The app is the committed sample and, because this script does not create a
DuckDB file, the twelve-week series in runs/kpi_demo.json. Playwright is not
a runtime dependency. Install it only to re-record the GIF:

    python -m pip install playwright
    python -m playwright install chromium
    python scripts/record_dashboard_gif.py

The GIF is committed. CI does not run this script.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "docs" / "img" / "dashboard-demo.gif"
LIMIT_BYTES = 5 * 1024 * 1024

VIEWS: tuple[tuple[str, str], ...] = (
    ("Scorecard", "Dimension"),
    ("Trend", "Principle KPIs"),
    ("Lineage", "Column lineage"),
    ("Glossary", "Physical columns"),
    ("Ownership", "Download ownership CSV"),
    ("Fairness", "Disparate impact"),
)


def main() -> None:
    """Start Streamlit, shoot one frame per view, and write the GIF."""
    port = _free_port()
    with tempfile.TemporaryDirectory() as temporary:
        log_path = Path(temporary) / "streamlit.log"
        process = _start_streamlit(port, log_path)
        frames: list[Image.Image] = []
        try:
            _wait_until_ready(process, port, log_path)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1200, "height": 760})
                page.goto(
                    f"http://127.0.0.1:{port}/?page=Scorecard",
                    wait_until="networkidle",
                )
                page.get_by_text("Governance-Sentinel").first.wait_for(timeout=60_000)
                sidebar = page.locator('[data-testid="stSidebar"]')
                for label, marker in VIEWS:
                    sidebar.get_by_text(label, exact=True).click()
                    page.get_by_text(marker).first.wait_for(timeout=30_000)
                    page.wait_for_timeout(600)
                    shot = page.screenshot(type="png")
                    frames.append(_frame(shot))
                browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    if len(frames) != len(VIEWS):
        raise RuntimeError(f"Expected {len(VIEWS)} frames, got {len(frames)}.")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    _write_gif(frames, OUTPUT)
    size = OUTPUT.stat().st_size
    if size >= LIMIT_BYTES:
        raise RuntimeError(f"{OUTPUT} is {size} bytes, over the 5 MB limit.")
    print(f"Wrote {OUTPUT} ({size} bytes, {len(frames)} frames).")


def _start_streamlit(port: int, log_path: Path) -> subprocess.Popen[bytes]:
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(REPO / "streamlit_app.py"),
        "--server.port",
        str(port),
        "--server.address",
        "127.0.0.1",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    log_handle = log_path.open("wb")
    return subprocess.Popen(
        command,
        cwd=REPO,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )


def _wait_until_ready(process: subprocess.Popen[bytes], port: int, log_path: Path) -> None:
    deadline = time.monotonic() + 90
    health = f"http://127.0.0.1:{port}/_stcore/health"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(log_path.read_text(encoding="utf-8", errors="replace"))
        try:
            with urllib.request.urlopen(health, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.4)
    raise RuntimeError(log_path.read_text(encoding="utf-8", errors="replace")[-2000:])


def _frame(payload: bytes) -> Image.Image:
    from io import BytesIO

    image = Image.open(BytesIO(payload)).convert("RGB")
    image.thumbnail((960, 608), Image.Resampling.LANCZOS)
    return image


def _write_gif(frames: list[Image.Image], path: Path) -> None:
    quantized = [frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=64) for frame in frames]
    quantized[0].save(
        path,
        save_all=True,
        append_images=quantized[1:],
        duration=1100,
        loop=0,
        optimize=True,
        disposal=2,
    )


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


if __name__ == "__main__":
    main()
