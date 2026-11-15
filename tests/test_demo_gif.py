"""The committed dashboard GIF is present, small, and linked from the README."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GIF = REPO / "docs" / "img" / "dashboard-demo.gif"
LIMIT_BYTES = 5 * 1024 * 1024


def test_dashboard_gif_is_a_small_animation() -> None:
    payload = GIF.read_bytes()
    assert payload[:6] in {b"GIF87a", b"GIF89a"}
    assert len(payload) < LIMIT_BYTES
    assert len(payload) > 10_000


def test_readme_embeds_the_gif_and_marks_the_live_url() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "docs/img/dashboard-demo.gif" in readme.split("## Run it", maxsplit=1)[0]
    assert "Live demo URL: coming soon." in readme
    assert "runtime.txt" in readme
    assert "does not deploy the app" in readme
