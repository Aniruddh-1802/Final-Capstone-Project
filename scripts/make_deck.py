"""Build presentation/Project_Presentation.pptx and its PDF copy from ONE slide definition (python-pptx + headless Chrome).

    python scripts/make_deck.py

Every figure comes from the measured results in docs/ (see the SOURCES notes). Keep bullets short: the screenshots carry the story.
"""
from __future__ import annotations

import html
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "presentation"
log = logging.getLogger("make_deck")

# Measured results (docs/test_report.md, docs/performance_notes.md, docs/data_contract.md).
TESTS_BACKEND = 315
TESTS_UI = 42
CHECKS_E2E = 71
CHECKS_KPI = 88
COVERAGE = 94

SHOT = ROOT / "docs" / "screenshots"
NAVY, BLUE, GREY, RED = "1c2530", "1f4e79", "55616e", "8c1d18"

SLIDES = [
    {"layout": "title", "title": "Healthcare Patient Management System",
     "sub": "From a flat CSV to a secured, audited, scheduled data system\nUCI Diabetes 130-US Hospitals, 1999-2008  |  Educational use only",
     "notes": "Say first: admission dates are simulated because the dataset has no dates, and every finding is an association, not a cause."},
    {"title": "The problem and four questions",
     "bullets": ["101,766 encounters, 71,518 patients, flat CSV, no dates",
                 "Q1  What is the 30-day readmission rate, and for whom?",
                 "Q2  How long do patients stay?",
                 "Q3  How do admissions trend over time? (simulated dates)",
                 "Q4  Which medication, lab and prior-visit patterns are associated with readmission?"],
     "image": "arch_small", "notes": "One row is one encounter, not one patient: patients repeat. The data has no hospital id, so we compare categories, never hospitals."},
    {"title": "Solution overview",
     "bullets": ["ETL: 13 quality rules, quarantine, idempotent reloads",
                 "MySQL: 16 tables, one view as the soft-delete filter",
                 "FastAPI: 32 operations, JWT, 3 roles, audit trail",
                 "React dashboard, CSV and Excel reports",
                 "Airflow: hourly load, weekly reports"],
     "image": "02_dashboard_top", "notes": "Everything runs locally: no Docker, cloud or CI/CD. Headline: 11.39% 30-day readmission over eligible encounters."},
    {"title": "Architecture and data flow", "layout": "wide", "image": "Architecture_Diagram.png",
     "caption": "Dataset to ETL to MySQL to API to React; Airflow triggers; quarantine, logs and reports on the side",
     "notes": "Walk the arrows: batches in, one transaction per file, SQL via a view, role checks and audit in the API, React only presents. Quality lives in the ETL, audit in the API."},
    {"title": "Data and quality rules",
     "bullets": ["'?' is missing; the word 'None' is a real lab value",
                 "DQ01-DQ13: reject, correct, flag, measure",
                 "Bad file (over 20% rejected) loads nothing",
                 "Faulty batch: 23 rows quarantined, with reasons",
                 "Same file twice: SKIPPED_DUPLICATE_FILE"],
     "image": "11_data_quality.png", "notes": "Live demo: load a held-back batch, show the pipeline_runs row, counts reconcile (read = loaded + rejected + skipped), then the faulty batch with reasons. Dates are simulated; the rules are real."},
    {"title": "Database design",
     "bullets": ["Third normal form: race and gender on patients only",
                 "Diagnoses and medications as child tables",
                 "Medications: only prescribed rows, 120,054 vs 2.1M",
                 "4 indexes, each proven by EXPLAIN",
                 "Date-range list: 256 ms to 0.8 ms; ICD search: 765 ms to 9 ms"],
     "image": "erd.png", "notes": "One EXPLAIN before and after. The biggest win was rewriting the view as NOT EXISTS, not an index. One proposed index was rejected because it did not help."},
    {"title": "API and security",
     "bullets": ["JWT, 60 minutes; role read from the database each request",
                 "Roles enforced on the server, not in the UI",
                 "Analyst: no patient id, race or gender; 403 on patients",
                 "Audit row written in the same transaction as the change",
                 "Errors: one contract, never a stack trace"],
     "image": "08_audit_log.png", "notes": "Swagger demo: login, filtered and paged encounters, 403 for the wrong role, the audit row after an update. The audit records which field changed, never race or gender values."},
    {"title": "Dashboard results", "layout": "wide", "image": "dash_bottom",
     "caption": "Associated with, not caused by. Dates simulated.",
     "bullets": ["Prior inpatient visits 0 vs 3+: 8.6% vs 26.4% readmitted within 30 days",
                 "Insulin dose 'Down' 14.2% vs 'No insulin' 10.2%"],
     "notes": "Switch to analyst and show what disappears; export Excel. Say 'associated with' every time. Trends are illustrative because dates are simulated."},
    {"title": "Testing and reliability",
     "bullets": [f"{TESTS_BACKEND} backend tests on a real MySQL schema, {COVERAGE}% line coverage",
                 f"{TESTS_UI} UI tests; {CHECKS_E2E} real-browser checks per role",
                 f"{CHECKS_KPI} KPI checks: SQL = API = pandas on the raw CSV",
                 "Deliberate bug (wrong denominator): 6 tests fail",
                 "Hard-kill test: nothing half-loaded"],
     "image": "24_airflow_etl_run_history.png", "notes": "State the gaps honestly: no real tablet, no screen reader, Excel not opened in Excel, Airflow 3.1 only. Mocked: nothing in the database layer."},
    {"title": "Challenges, trade-offs and limits",
     "bullets": ["Simulated dates: trends are illustrative only",
                 "No hospital id: categories compared, not hospitals",
                 "Whole-file reject above 20%: safe, but strict",
                 "No summary table: two queries stay at 0.6-0.8 s",
                 "Airflow in WSL2: two environments to maintain"],
     "image": "23_airflow_etl_run_failed_graph.png", "notes": "Each limit has a stated reason. Bugs found by running, not reading: WSL path variable, view plan flip, ICD rule rejecting 5,732 real codes, demographics in the audit trail."},
    {"title": "Learnings and next steps",
     "bullets": ["A plausible number can be wrong: check the denominator",
                 "Measure first; one index was rejected on evidence",
                 "Run the commands: fresh-clone check found real gaps",
                 "Next: real timestamps, hospital dimension",
                 "Next: validated risk model; alerting on failed runs"],
     "image": "10_pipeline_runs.png", "notes": "Close on scale: 100x data means summary tables, partitioning by admission date, read replicas and queued exports."},
]


def prepare_images() -> dict[str, Path]:
    """Resolve image keys to files; crop the tall dashboard shot to its top and shrink the diagram."""
    tmp = Path(tempfile.mkdtemp(prefix="deck_"))
    paths: dict[str, Path] = {}
    top = Image.open(SHOT / "02_dashboard_admin.png")
    top.crop((0, 0, top.width, min(top.height, 1100))).save(tmp / "02_dashboard_top.png")
    paths["02_dashboard_top"] = tmp / "02_dashboard_top.png"
    bottom = top.crop((0, max(0, top.height - 1000), top.width, top.height))      # insulin, A1C and prior-visit charts
    bottom.save(tmp / "dash_bottom.png")
    paths["dash_bottom"] = tmp / "dash_bottom.png"
    arch = Image.open(ROOT / "architecture" / "Architecture_Diagram.png")
    arch.save(tmp / "arch.png")
    paths["Architecture_Diagram.png"] = tmp / "arch.png"
    paths["arch_small"] = tmp / "arch.png"
    paths["erd.png"] = ROOT / "docs" / "erd.png"
    for name in ("11_data_quality.png", "08_audit_log.png", "24_airflow_etl_run_history.png", "23_airflow_etl_run_failed_graph.png", "10_pipeline_runs.png"):
        paths[name] = SHOT / name
    return paths


def rgb(h: str) -> RGBColor:
    return RGBColor.from_string(h.upper())


def add_text(slide, x, y, w, h, text, size, color=NAVY, bold=False, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        run = p.add_run()
        run.text = line
        run.font.size, run.font.bold, run.font.color.rgb, run.font.name = Pt(size), bold, rgb(color), "Calibri"
    return box


def place_image(slide, path: Path, x, y, max_w, max_h):
    with Image.open(path) as im:
        ratio = im.width / im.height
    w = max_w
    h = w / ratio
    if h > max_h:
        h, w = max_h, max_h * ratio
    slide.shapes.add_picture(str(path), Inches(x + (max_w - w) / 2), Inches(y + (max_h - h) / 2), Inches(w), Inches(h))


def build_pptx(images: dict[str, Path], target: Path) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    for n, s in enumerate(SLIDES, 1):
        slide = prs.slides.add_slide(blank)
        if s.get("layout") == "title":
            bg = slide.shapes.add_shape(1, 0, 0, prs.slide_width, prs.slide_height)
            bg.fill.solid(); bg.fill.fore_color.rgb = rgb(NAVY); bg.line.fill.background()
            add_text(slide, 0.9, 2.2, 11.5, 1.4, s["title"], 44, "FFFFFF", True)
            add_text(slide, 0.9, 3.9, 11.5, 1.6, s["sub"], 22, "C9D6E2")
            add_text(slide, 0.9, 6.5, 11.5, 0.5, "Dates in this data are simulated  |  Findings are associations, not causes", 14, "F0C27B")
        else:
            bar = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(1.0))
            bar.fill.solid(); bar.fill.fore_color.rgb = rgb(BLUE); bar.line.fill.background()
            add_text(slide, 0.5, 0.15, 12.3, 0.7, s["title"], 32, "FFFFFF", True)
            wide = s.get("layout") == "wide"
            if s.get("bullets"):
                bw = 4.3 if wide else 5.9
                text = "\n".join("•  " + b for b in s["bullets"])
                add_text(slide, 0.5, 1.4, bw, 5.2, text, 18 if wide else 20)
            if s.get("image"):
                img = images[s["image"]]
                if wide and s.get("bullets"):
                    place_image(slide, img, 5.0, 1.25, 8.0, 5.4)
                elif wide:
                    place_image(slide, img, 0.4, 1.2, 12.5, 5.5)
                else:
                    place_image(slide, img, 6.6, 1.35, 6.4, 5.3)
            if s.get("caption"):
                add_text(slide, 0.5, 6.85, 12.3, 0.4, s["caption"], 14, GREY)
            add_text(slide, 12.3, 7.05, 0.8, 0.3, str(n), 12, GREY, align=PP_ALIGN.RIGHT)
        slide.notes_slide.notes_text_frame.text = s["notes"]
    prs.save(target)


def build_html(images: dict[str, Path]) -> str:
    pages = []
    for n, s in enumerate(SLIDES, 1):
        if s.get("layout") == "title":
            pages.append(f"<section class='title'><h1>{html.escape(s['title'])}</h1><p>{html.escape(s['sub']).replace(chr(10), '<br>')}</p>"
                         f"<small>Dates in this data are simulated &nbsp;|&nbsp; Findings are associations, not causes</small></section>")
            continue
        wide = s.get("layout") == "wide"
        bullets = "".join(f"<li>{html.escape(b)}</li>" for b in s.get("bullets", []))
        img = f"<img src='{images[s['image']].as_uri()}'>" if s.get("image") else ""
        cap = f"<div class='cap'>{html.escape(s['caption'])}</div>" if s.get("caption") else ""
        textcol = f"<ul class='{'narrow' if wide else ''}'>{bullets}</ul>" if bullets else ""
        pages.append(f"<section><header>{html.escape(s['title'])}</header><div class='body {'wide' if wide else ''}'>{textcol}<div class='pic'>{img}</div></div>{cap}<span class='n'>{n}</span></section>")
    css = f"""@page {{ size: 13.333in 7.5in; margin: 0 }} * {{ box-sizing: border-box }}
    body {{ margin: 0; font-family: Calibri, 'Segoe UI', Arial, sans-serif; color: #{NAVY} }}
    section {{ width: 13.333in; height: 7.5in; position: relative; page-break-after: always; overflow: hidden }}
    header {{ background: #{BLUE}; color: #fff; font-size: 32pt; font-weight: 700; height: 1in; padding: 0.17in 0.5in }}
    .body {{ display: flex; gap: 0.3in; padding: 0.35in 0.5in 0; height: 5.7in }} ul {{ flex: 0 0 5.9in; margin: 0; padding-left: 0.3in; font-size: 20pt; line-height: 1.35 }}
    ul.narrow {{ flex-basis: 4.3in; font-size: 18pt }} li {{ margin-bottom: 0.14in }}
    .pic {{ flex: 1; display: flex; align-items: center; justify-content: center; min-width: 0 }} .pic img {{ max-width: 100%; max-height: 5.4in }}
    .cap {{ position: absolute; left: 0.5in; bottom: 0.2in; font-size: 14pt; color: #{GREY} }} .n {{ position: absolute; right: 0.4in; bottom: 0.15in; color: #{GREY}; font-size: 12pt }}
    section.title {{ background: #{NAVY}; color: #fff; padding: 2.2in 0.9in }} .title h1 {{ font-size: 44pt; margin: 0 0 0.4in }} .title p {{ font-size: 22pt; color: #C9D6E2 }}
    .title small {{ position: absolute; left: 0.9in; bottom: 0.6in; font-size: 14pt; color: #F0C27B }}"""
    return f"<!doctype html><html><head><meta charset='utf-8'><title>Project Presentation</title><style>{css}</style></head><body>{''.join(pages)}</body></html>"


def build_pdf(images: dict[str, Path], target: Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_pdfs import find_chrome
    page = Path(tempfile.mkdtemp(prefix="deck_html_")) / "deck.html"
    page.write_text(build_html(images), encoding="utf-8")
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([find_chrome(), "--headless=new", "--disable-gpu", f"--user-data-dir={profile}", "--no-pdf-header-footer",
                        "--allow-file-access-from-files", f"--print-to-pdf={target}", page.as_uri()], check=True, timeout=180, capture_output=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    OUT.mkdir(exist_ok=True)
    imgs = prepare_images()
    build_pptx(imgs, OUT / "Project_Presentation.pptx")
    build_pdf(imgs, OUT / "Project_Presentation.pdf")
    log.info("wrote presentation/Project_Presentation.pptx and .pdf (%d slides)", len(SLIDES))

