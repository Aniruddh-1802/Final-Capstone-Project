"""Render docs/erd.png (from docs/erd.mmd) and architecture/architecture_v0.png with matplotlib.

Needs matplotlib (documentation tooling only, not in requirements.txt):  pip install matplotlib
Run from the repository root:  python scripts/make_diagrams.py
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ROW_H, BOX_W, HEADER_H = 0.2, 4.2, 0.4

# Top-left corner (x, y) of each table box in the ERD; y grows upward.
LAYOUT = {
    "patients": (5.5, 25.9),
    "encounters": (5.5, 22.6),
    "ref_admission_type": (0.3, 24.0),
    "ref_admission_source": (0.3, 21.4),
    "ref_discharge_disposition": (0.3, 18.6),
    "ref_medical_specialty": (0.3, 15.3),
    "ref_payer": (0.3, 12.7),
    "encounter_outcomes": (10.9, 22.6),
    "encounter_diagnoses": (10.9, 19.0),
    "encounter_medications": (10.9, 16.0),
    "medications": (16.3, 16.0),
    "app_users": (0.3, 9.3),
    "audit_logs": (5.5, 9.3),
    "pipeline_runs": (10.9, 9.3),
    "dq_issues": (16.3, 9.3),
    "report_runs": (21.7, 9.3),
}
CARD = {"||": "1", "|o": "0..1", "o|": "0..1", "o{": "0..*", "|{": "1..*", "}o": "0..*", "}|": "1..*"}


def parse_mermaid(text: str):
    """Return (tables, relations) from the erDiagram text."""
    tables: dict[str, list[tuple[str, str, str]]] = {}
    relations: list[tuple[str, str, str, str, str]] = []
    current: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^(\w+)\s*\{$", line)
        if m:
            current = m.group(1)
            tables[current] = []
            continue
        if line == "}":
            current = None
            continue
        if current and line:
            parts = line.split(" ", 2)
            rest = parts[2] if len(parts) > 2 else ""
            flags = rest.split('"')[0].strip().replace(",", " ")
            tables[current].append((parts[0], parts[1], flags))
            continue
        r = re.match(r"^(\w+)\s+([|}o]{2})--([|o{]{2})\s+(\w+)\s*:\s*\"(.*)\"$", line)
        if r:
            relations.append((r.group(1), r.group(2), r.group(3), r.group(4), r.group(5)))
    return tables, relations


def box_geometry(name: str, n_cols: int) -> tuple[float, float, float, float]:
    x, y = LAYOUT[name]
    h = HEADER_H + n_cols * ROW_H + 0.1
    return x, y, BOX_W, h


def draw_erd(src: Path, out: Path) -> None:
    tables, relations = parse_mermaid(src.read_text(encoding="utf-8"))
    fig, ax = plt.subplots(figsize=(22, 24))
    ax.set_xlim(0, 26.5)
    ax.set_ylim(4.5, 27)
    ax.axis("off")
    geo = {n: box_geometry(n, len(c)) for n, c in tables.items()}

    for name, cols in tables.items():
        x, y, w, h = geo[name]
        ax.add_patch(Rectangle((x, y - h), w, h, fc="#ffffff", ec="#333333", lw=1.2, zorder=2))
        ax.add_patch(Rectangle((x, y - HEADER_H), w, HEADER_H, fc="#1f4e79", ec="#333333", lw=1.2, zorder=3))
        ax.text(x + w / 2, y - HEADER_H / 2, name, color="white", ha="center", va="center",
                fontsize=9.5, fontweight="bold", zorder=4)
        for i, (typ, col, flags) in enumerate(cols):
            ty = y - HEADER_H - (i + 0.6) * ROW_H
            weight = "bold" if "PK" in flags else "normal"
            ax.text(x + 0.08, ty, f"{col}", fontsize=6.6, va="center", fontweight=weight, zorder=4)
            ax.text(x + w * 0.55, ty, typ, fontsize=6.2, va="center", color="#555555", zorder=4)
            ax.text(x + w - 0.08, ty, flags.replace("PK FK", "PK,FK"), fontsize=6.2, va="center", ha="right",
                    color="#b03a2e", zorder=4)

    def anchor(src_n: str, dst_n: str) -> tuple[tuple[float, float], tuple[float, float]]:
        sx, sy, sw, sh = geo[src_n]
        dx, dy, dw, dh = geo[dst_n]
        scx, scy, dcx, dcy = sx + sw / 2, sy - sh / 2, dx + dw / 2, dy - dh / 2
        horizontal = sx + sw < dx or dx + dw < sx
        if horizontal:
            sxp = sx + sw if scx < dcx else sx
            dxp = dx if scx < dcx else dx + dw
            syp = min(max(dcy, sy - sh + 0.2), sy - 0.2)
            dyp = min(max(scy, dy - dh + 0.2), dy - 0.2)
            return (sxp, syp), (dxp, dyp)
        syp = sy - sh if scy > dcy else sy
        dyp = dy if scy > dcy else dy - dh
        sxp = min(max(dcx, sx + 0.3), sx + sw - 0.3)
        dxp = min(max(scx, dx + 0.3), dx + dw - 0.3)
        return (sxp, syp), (dxp, dyp)

    for a, lc, rc, b, label in relations:
        (x1, y1), (x2, y2) = anchor(a, b)
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-", color="#2e7d32", lw=1.3, zorder=1,
                                     connectionstyle="arc3,rad=0.0"))
        for (px, py), (qx, qy), sym in (((x1, y1), (x2, y2), lc), ((x2, y2), (x1, y1), rc)):
            ox = 0.28 if qx > px else -0.28 if qx < px else 0
            oy = 0.2 if qy > py else -0.2 if qy < py else 0
            if abs(qx - px) < 0.01:
                ox = 0.25
            ax.text(px + ox, py + oy, CARD.get(sym, sym), fontsize=7, color="#2e7d32", ha="center",
                    va="center", fontweight="bold", zorder=5,
                    bbox=dict(fc="white", ec="none", pad=0.4))

    ax.text(0.3, 26.6, "Healthcare Patient Management System - ERD (admission/discharge dates are SIMULATED)",
            fontsize=13, fontweight="bold")
    ax.text(0.3, 26.25, "PK = primary key, FK = foreign key, UK = unique. Keys encounter_id and patient_nbr are BIGINT "
            "from the source (not auto-generated). race/gender exist only on patients.", fontsize=8)
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)


def draw_architecture(out: Path) -> None:
    fig, ax = plt.subplots(figsize=(18, 9))
    ax.set_xlim(0, 18)
    ax.set_ylim(0, 9)
    ax.axis("off")

    def node(x: float, y: float, w: float, h: float, title: str, body: str, color: str) -> tuple[float, float, float, float]:
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.05,rounding_size=0.12",
                                    fc=color, ec="#333333", lw=1.3))
        ax.text(x + w / 2, y + h - 0.28, title, ha="center", va="center", fontsize=10, fontweight="bold")
        ax.text(x + w / 2, y + (h - 0.5) / 2, body, ha="center", va="center", fontsize=7.8)
        return x, y, w, h

    def arrow(p: tuple[float, float], q: tuple[float, float], label: str = "", dy: float = 0.18) -> None:
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=14, lw=1.5, color="#1f4e79"))
        if label:
            ax.text((p[0] + q[0]) / 2, (p[1] + q[1]) / 2 + dy, label, ha="center", fontsize=7.5, color="#1f4e79")

    src = node(0.3, 5.6, 2.8, 2.2, "Data sources", "diabetic_data.csv\n(101,766 encounters)\nIDs_mapping.csv\n(3 lookup tables)", "#fdebd0")
    prep = node(0.3, 2.6, 2.8, 2.2, "prepare_batches.py", "seeded SIMULATED dates\n1 initial + 4 incremental\nbatch files\n(data/incoming, held_back)", "#fdebd0")
    etl = node(4.3, 3.6, 3.7, 4.2, "ETL (Pandas, src/etl)", "extract  - read '?' as NULL\ntransform - pure functions\nquality   - DQ rules\nload      - upsert, idempotent\nincremental + pipeline.py\n(reusable modules)", "#d6eaf8")
    db = node(9.2, 3.6, 3.2, 4.2, "MySQL 8", "patients, encounters,\ndiagnoses, medications,\noutcomes, ref_* lookups,\napp_users, audit_logs,\npipeline_runs, dq_issues,\nreport_runs", "#d5f5e3")
    api = node(13.4, 3.6, 2.4, 4.2, "FastAPI", "JWT login + 3 roles\nCRUD + audit\nfilter/sort/page/search\nanalytics, exports\nSwagger /docs", "#e8daef")
    ui = node(16.2, 3.6, 1.6, 4.2, "React (Vite)", "role-aware UI\nKPI dashboard\nrecords, admin\nreports", "#fadbd8")
    air = node(4.3, 0.4, 3.7, 1.9, "Airflow (scheduling)", "incremental ETL DAG\nweekly report DAG\ncall the same functions as the CLI", "#fcf3cf")
    files = node(9.2, 0.4, 3.2, 1.9, "Files and logs", "data/rejected (quarantine)\ndata/reports (CSV/Excel)\nlogs/ (rotating)", "#eaeded")

    arrow((1.7, 5.6), (1.7, 4.8), "raw CSV")
    arrow((3.1, 3.7), (4.3, 5.2), "batch CSVs")
    arrow((3.1, 6.7), (4.3, 6.7), "IDs_mapping")
    arrow((8.0, 5.7), (9.2, 5.7), "clean rows (SQLAlchemy)")
    arrow((12.4, 5.7), (13.4, 5.7), "SQL")
    arrow((15.8, 5.7), (16.2, 5.7))
    arrow((6.1, 2.3), (6.1, 3.6), "triggers")
    arrow((8.0, 3.9), (9.2, 2.2), "rejects, logs")
    arrow((13.9, 3.6), (12.4, 2.0), "reports")
    arrow((8.0, 1.4), (9.2, 1.4))
    arrow((10.8, 3.6), (10.8, 2.3), "pipeline_runs, dq_issues")

    ax.text(0.3, 8.6, "Architecture v0 - Healthcare Patient Management System", fontsize=14, fontweight="bold")
    ax.text(0.3, 8.25, "CSV batches -> Pandas ETL (clean, validate) -> MySQL -> FastAPI (RBAC, audit) -> React dashboard and exports. "
            "Dates are simulated. Local only: no Docker, cloud or CI/CD.", fontsize=8.5)
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)


def draw_architecture_final(out_dir: Path) -> None:
    """The final architecture of the BUILT system -> Architecture_Diagram.pdf / .jpeg / .png (every box exists in the repository)."""
    fig, ax = plt.subplots(figsize=(22, 11.5))
    ax.set_xlim(0, 22)
    ax.set_ylim(0, 11.5)
    ax.axis("off")
    ink, blue, amber, red, grey = "#1c2530", "#1f4e79", "#9a6200", "#8c1d18", "#555555"

    def box(x, y, w, h, title, lines, color, title_size=11, body_size=8.6):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04,rounding_size=0.12", fc=color, ec="#333333", lw=1.3))
        ax.text(x + w / 2, y + h - 0.3, title, ha="center", va="center", fontsize=title_size, fontweight="bold", color=ink)
        ax.text(x + w / 2, y + (h - 0.6) / 2, "\n".join(lines), ha="center", va="center", fontsize=body_size, color=ink, linespacing=1.4)

    def arrow(p, q, label="", color=blue, ls="-", lx=None, ly=None, ha="center"):
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=16, lw=1.8, color=color, linestyle=ls))
        if label:
            ax.text(lx if lx is not None else (p[0] + q[0]) / 2, ly if ly is not None else (p[1] + q[1]) / 2 + 0.12, label, ha=ha,
                    va="bottom", fontsize=8.5, color=color, bbox=dict(fc="white", ec="none", pad=0.8, alpha=0.95))

    ax.text(0.2, 11.1, "Healthcare Patient Management System - Architecture", fontsize=18, fontweight="bold", color=ink)
    ax.text(0.2, 10.7, "Dataset -> ETL -> MySQL -> FastAPI -> React, scheduled by Airflow. Everything runs locally (no cloud, Docker or CI/CD). "
            "Admission and discharge dates are SIMULATED.", fontsize=10, color="#444")

    # ---- row 1: the data flow --------------------------------------------------------------------------------------------
    box(0.2, 6.9, 2.9, 3.2, "Data sources", ["diabetic_data.csv", "101,766 encounters", "50 columns", "IDs_mapping.csv", "(3 lookup tables)", "UCI Diabetes 130-US", "Hospitals, 1999-2008"], "#fdebd0")
    box(3.7, 6.9, 2.9, 3.2, "prepare_batches.py", ["seed 42: SIMULATED", "admission and discharge", "dates added", "1 initial + 4 incremental", "batch CSVs in", "data/incoming and", "data/held_back"], "#fdebd0")
    ax.add_patch(FancyBboxPatch((7.2, 6.9), 6.2, 3.2, boxstyle="round,pad=0.04,rounding_size=0.15", fc="#eaf3fb", ec="#333333", lw=1.5))
    ax.text(10.3, 9.8, "ETL  (Pandas, src/etl: reusable pure functions)", ha="center", fontsize=11, fontweight="bold", color=ink)
    for i, (name, lines) in enumerate([("extract", ["read_batch", "'?' = missing", "'None' kept", "ICD as text"]), ("transform", ["standardise", "age_order, flags", "30-day, eligible", "melt medications"]),
                                       ("quality", ["DQ01 - DQ13", "reject / correct", "/ flag; 20% limit", "quarantine"]), ("load", ["one transaction", "per file; file hash", "+ key check =", "idempotent"])]):
        x = 7.35 + i * 1.5
        box(x, 7.5, 1.35, 1.95, name, lines, "#d6eaf8", 9.5, 7.8)
        if i:
            arrow((x - 0.15, 8.5), (x, 8.5), color="#2e4a66")
    ax.text(10.3, 7.1, "pipeline.py: one pipeline_runs row per file; read = loaded + rejected + skipped", ha="center", fontsize=8.3, color="#2e4a66")
    box(14.0, 6.9, 3.2, 3.2, "MySQL 8", ["patients (race, gender only here)", "encounters, outcomes, diagnoses,", "medications, ref_* lookups", "view v_active_encounters", "(single soft-delete filter)", "app_users, audit_logs,", "pipeline_runs, dq_issues,", "report_runs; 4 indexes"], "#d5f5e3", body_size=8.2)
    box(17.8, 6.9, 4.0, 3.2, "FastAPI  (src/app)", ["JWT login and 3 roles (RBAC)", "CRUD with audit in the same", "transaction; validation", "filter, sort, page, search", "analytics in SQL (eligible", "denominator); CSV/Excel exports", "uniform errors; Swagger /docs"], "#e8daef", body_size=8.4)
    arrow((3.1, 8.5), (3.7, 8.5), "raw CSV", ly=8.6, lx=3.4)
    arrow((6.6, 8.5), (7.2, 8.5), "batches", ly=8.6, lx=6.9)
    arrow((13.4, 8.5), (14.0, 8.5), "rows", ly=8.6, lx=13.7)
    arrow((17.2, 8.5), (17.8, 8.5), "SQL", ly=8.6, lx=17.5)

    # ---- row 2: operations, scheduling, the user interface ------------------------------------------------------------------------
    box(0.2, 3.3, 6.4, 2.7, "Evidence and tests", ["315 backend tests (pytest) + 42 UI tests (Vitest)", "headless-browser run: 71 checks, UI vs API per role", "verify_kpis.py: SQL = API = pandas, 88 of 88",
                                                  "docs/: contract, performance notes, runbook, audit log"], "#eaeded", body_size=8.4)
    box(7.2, 3.3, 4.6, 2.7, "Airflow 3.1  (WSL2, own virtualenv)", ["healthcare_incremental_etl (hourly):", "scan > run_etl > check_quality > summary", "healthcare_weekly_report (Mondays 06:00)", "retries 2, catchup off, one run at a time", "fallback: scripts/scheduler.py"], "#fcf3cf", body_size=8.2)
    box(12.2, 3.3, 5.0, 2.7, "Files and logs", ["data/rejected: quarantined rows with a reason", "data/reports: generated CSV and Excel", "logs/: rotating, request id on every line", "audit_logs: who changed what, before and after"], "#eaeded", body_size=8.4)
    box(17.8, 3.3, 4.0, 2.7, "React + Vite  (frontend)", ["role-aware navigation", "KPI dashboard (9 charts)", "patients, encounters, reports", "audit, pipeline, data quality", "simulated-dates banner"], "#fadbd8", body_size=8.4)
    arrow((9.5, 6.0), (9.5, 6.9), "triggers", color=amber, ly=6.25, lx=10.35, ha="left")
    arrow((12.9, 6.9), (13.7, 6.0), "rejected rows, logs", color=red, ls="--", ly=6.45, lx=13.5, ha="left")
    arrow((19.8, 6.9), (19.8, 6.0), "REST + JSON (Bearer JWT)", ly=6.3, lx=19.95, ha="left")
    arrow((11.8, 4.2), (12.2, 4.2), "", color=amber)
    ax.text(12.0, 4.5, "weekly\nreports", ha="center", fontsize=7.6, color=amber)

    # ---- row 3: people ------------------------------------------------------------------------------------------------------------
    box(17.8, 0.5, 4.0, 1.8, "Users", ["administrator  |  clinical_ops  |  analyst", "(analyst sees no patient_nbr, race or gender)"], "#f6ddcc", body_size=8.2)
    arrow((19.8, 2.3), (19.8, 3.3), "browser", ly=2.5, lx=19.95, ha="left")
    for i, text in enumerate(["solid arrow: data flow", "dashed arrow: operational output (quarantine, logs)", "amber arrow: scheduled trigger"]):
        ax.text(0.3, 2.45 - i * 0.4, text, fontsize=9, color="#444")
    ax.text(0.3, 0.55, "Responsibility boundary: the ETL cleans and validates, MySQL stores and aggregates, FastAPI enforces access rules and exposes contracts,\n"
            "React only presents. Business rules (for example the readmission denominator: eligible encounters only) live in one place on the server.", fontsize=9, color=ink, linespacing=1.55)
    out_dir.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png", "jpeg"):
        fig.savefig(out_dir / f"Architecture_Diagram.{ext}", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    draw_erd(ROOT / "docs" / "erd.mmd", ROOT / "docs" / "erd.png")
    draw_architecture(ROOT / "architecture" / "architecture_v0.png")
    draw_architecture_final(ROOT / "architecture")
    print("wrote docs/erd.png, architecture/architecture_v0.png and architecture/Architecture_Diagram.{pdf,png,jpeg}")
