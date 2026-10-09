"""Render the Markdown deliverables to PDF with headless Chrome (no pandoc or Word needed).

    python scripts/build_pdfs.py            # all documents
    python scripts/build_pdfs.py design     # only names containing "design"

Each Markdown file becomes HTML (python-markdown) next to the source, is printed to PDF by Chrome, and the temporary HTML is removed.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("build_pdfs")

DOCUMENTS = [  # (markdown source, pdf output, title)
    (ROOT / "design" / "Design_Document.md", ROOT / "design" / "Design_Document.pdf", "Design Document"),
    (ROOT / "docs" / "API_Documentation.md", ROOT / "docs" / "API_Documentation.pdf", "API Documentation"),
    (ROOT / "docs" / "Dataset_Details.md", ROOT / "docs" / "Dataset_Details.pdf", "Dataset Details"),
    (ROOT / "docs" / "test_report.md", ROOT / "docs" / "test_report.pdf", "Test Report"),
]

CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10.5pt; line-height: 1.45; color: #1c2530; }
h1 { font-size: 22pt; border-bottom: 3px solid #1f4e79; padding-bottom: 4px; color: #1f4e79; }
h2 { font-size: 15pt; color: #1f4e79; margin-top: 22px; border-bottom: 1px solid #c9d6e2; padding-bottom: 2px; page-break-after: avoid; }
h3 { font-size: 12pt; margin-top: 16px; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; font-size: 9.2pt; page-break-inside: auto; }
tr { page-break-inside: avoid; }
th { background: #1f4e79; color: #fff; text-align: left; padding: 4px 6px; }
td { border: 1px solid #c9d6e2; padding: 3px 6px; vertical-align: top; }
tr:nth-child(even) td { background: #f4f8fb; }
code { font-family: Consolas, 'Courier New', monospace; font-size: 9pt; background: #eef2f6; padding: 0 3px; border-radius: 3px; }
pre { background: #f1f4f8; border: 1px solid #d5dde6; border-radius: 4px; padding: 7px 9px; font-size: 8.2pt; white-space: pre-wrap; word-break: break-all; page-break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 8.2pt; }
blockquote { border-left: 4px solid #c0392b; background: #fdf2f0; margin: 10px 0; padding: 6px 12px; }
img { max-width: 100%; }
"""


def find_chrome() -> str:
    for candidate in (os.environ.get("CHROME_PATH", ""), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                      r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                      r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit("Chrome or Edge not found; set CHROME_PATH")


def blank_line_before_lists(text: str) -> str:
    """GitHub renders a list that follows a paragraph directly; python-markdown needs a blank line. Code fences are left alone."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        starts_list = line.startswith(("- ", "* ")) or (line[:1].isdigit() and line.split(" ", 1)[0].rstrip(".").isdigit() and line.split(" ", 1)[0].endswith("."))
        if not in_fence and starts_list and out and out[-1].strip() and not out[-1].startswith(("- ", "* ", "|")) \
                and not out[-1][:1].isdigit() and not out[-1].startswith("  "):
            out.append("")
        out.append(line)
    return "\n".join(out) + "\n"


def render(source: Path, target: Path, title: str, chrome: str) -> None:
    html_body = markdown.markdown(blank_line_before_lists(source.read_text(encoding="utf-8")), extensions=["tables", "fenced_code", "sane_lists"])
    html = f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title><style>{CSS}</style></head><body>{html_body}</body></html>"
    page = source.with_suffix(".print.html")
    page.write_text(html, encoding="utf-8")
    try:
        with tempfile.TemporaryDirectory() as profile:
            subprocess.run([chrome, "--headless=new", "--disable-gpu", f"--user-data-dir={profile}", "--no-pdf-header-footer",
                            f"--print-to-pdf={target}", page.as_uri()], check=True, timeout=180, capture_output=True)
    finally:
        page.unlink(missing_ok=True)
    log.info("wrote %s (%d KB)", target.relative_to(ROOT), target.stat().st_size // 1024)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    wanted = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    exe = find_chrome()
    for src, dst, name in DOCUMENTS:
        if wanted in src.name.lower() and src.exists():
            render(src, dst, name, exe)
