"""Synthetic lab-report generator.

Emits one PDF and one matching ground-truth JSON (schema.LabReport shape) per
synthetic case into sample_data/pdfs/ and sample_data/ground_truth/. Ground
truth holds the *correct final structured record* a perfect extraction should
produce -- i.e. canonical analyte names and parsed date/range values -- not a
literal OCR transcript, since that's what eval/evaluate.py will diff the
pipeline's output against.

Deterministic: fixed patient/value/timestamp data and a fixed RNG seed for the
scanned-document jitter, so re-running overwrites files with identical bytes.

Run (after installing deps in whatever env you like):
    pip install -r sample_data/requirements.txt
    python sample_data/generate.py
"""

from __future__ import annotations

import hashlib
import io
import random
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "extractor"))

import reportlab.rl_config  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import LETTER  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import inch  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from schema import Diagnosis, Flag, LabReport, Patient, Result, Sex  # noqa: E402

# Freeze reportlab's embedded creation date so re-running this script produces
# byte-identical PDFs instead of ones that differ only by timestamp.
reportlab.rl_config.invariant = 1

HERE = Path(__file__).resolve().parent
PDF_DIR = HERE / "pdfs"
GT_DIR = HERE / "ground_truth"

SEED = 20260704
GROUND_TRUTH_TIMESTAMP = datetime(2026, 7, 4, 9, 0, 0)

LabelStyle = Literal["canonical", "abbrev", "caps"]
UnitStyle = Literal["us", "si"]
RangeLayout = Literal["combined", "split"]
DateStyle = Literal["mdy", "dmy", "iso"]
FlagStyle = Literal["letters", "arrows", "asterisk"]
Template = Literal["rows", "panels", "inline"]
OneSided = Literal["lt", "gt"] | None


# --- analyte catalog ---------------------------------------------------
# One entry per lab test. `normal_value`/`flagged_value` are pre-converted
# per unit system (not run through a real conversion formula) so a doc's
# unit choice never has to reconcile against a recomputed number.


@dataclass(frozen=True)
class AnalyteSpec:
    canonical: str
    synonyms: dict[LabelStyle, str]
    unit: dict[UnitStyle, str]
    normal_value: dict[UnitStyle, float]
    flagged_value: dict[UnitStyle, float]
    ref_low: dict[UnitStyle, float]
    ref_high: dict[UnitStyle, float]
    # Some tests are conventionally reported one-sided ("<200", ">40") --
    # that's a property of the test, not a doc-level style choice, so the
    # unused bound is a sentinel and never rendered or read for flag math.
    one_sided: OneSided = None


ANALYTES: dict[str, AnalyteSpec] = {
    "hemoglobin": AnalyteSpec(
        canonical="Hemoglobin",
        synonyms={"canonical": "Hemoglobin", "abbrev": "Hgb", "caps": "HGB"},
        unit={"us": "g/dL", "si": "g/L"},
        normal_value={"us": 14.2, "si": 142.0},
        flagged_value={"us": 11.0, "si": 110.0},
        ref_low={"us": 13.5, "si": 135.0},
        ref_high={"us": 17.5, "si": 175.0},
    ),
    "wbc": AnalyteSpec(
        canonical="White Blood Cell Count",
        synonyms={"canonical": "White Blood Cell Count", "abbrev": "WBC", "caps": "LEUKOCYTES"},
        unit={"us": "x10^3/uL", "si": "x10^9/L"},
        normal_value={"us": 7.5, "si": 7.5},
        flagged_value={"us": 13.5, "si": 13.5},
        ref_low={"us": 4.0, "si": 4.0},
        ref_high={"us": 11.0, "si": 11.0},
    ),
    "glucose": AnalyteSpec(
        canonical="Glucose",
        synonyms={"canonical": "Glucose", "abbrev": "GLU", "caps": "BLOOD SUGAR"},
        unit={"us": "mg/dL", "si": "mmol/L"},
        normal_value={"us": 92.0, "si": 5.1},
        flagged_value={"us": 118.0, "si": 6.6},
        ref_low={"us": 70.0, "si": 3.9},
        ref_high={"us": 100.0, "si": 5.6},
    ),
    "creatinine": AnalyteSpec(
        canonical="Creatinine",
        synonyms={"canonical": "Creatinine", "abbrev": "Creat", "caps": "CREA"},
        unit={"us": "mg/dL", "si": "umol/L"},
        normal_value={"us": 0.9, "si": 80.0},
        flagged_value={"us": 1.6, "si": 141.0},
        ref_low={"us": 0.6, "si": 53.0},
        ref_high={"us": 1.3, "si": 115.0},
    ),
    "sodium": AnalyteSpec(
        canonical="Sodium",
        synonyms={"canonical": "Sodium", "abbrev": "Na", "caps": "NA+"},
        unit={"us": "mEq/L", "si": "mmol/L"},
        normal_value={"us": 140.0, "si": 140.0},
        flagged_value={"us": 130.0, "si": 130.0},
        ref_low={"us": 136.0, "si": 136.0},
        ref_high={"us": 145.0, "si": 145.0},
    ),
    "potassium": AnalyteSpec(
        canonical="Potassium",
        synonyms={"canonical": "Potassium", "abbrev": "K", "caps": "K+"},
        unit={"us": "mEq/L", "si": "mmol/L"},
        normal_value={"us": 4.2, "si": 4.2},
        flagged_value={"us": 6.8, "si": 6.8},  # adversarial doc only: critical high
        ref_low={"us": 3.5, "si": 3.5},
        ref_high={"us": 5.1, "si": 5.1},
    ),
    "alt": AnalyteSpec(
        canonical="Alanine Aminotransferase",
        synonyms={"canonical": "Alanine Aminotransferase", "abbrev": "ALT", "caps": "SGPT"},
        unit={"us": "U/L", "si": "U/L"},
        normal_value={"us": 30.0, "si": 30.0},
        flagged_value={"us": 75.0, "si": 75.0},
        ref_low={"us": 7.0, "si": 7.0},
        ref_high={"us": 56.0, "si": 56.0},
    ),
    "total_cholesterol": AnalyteSpec(
        canonical="Total Cholesterol",
        synonyms={
            "canonical": "Total Cholesterol",
            "abbrev": "Chol",
            "caps": "CHOLESTEROL, TOTAL",
        },
        unit={"us": "mg/dL", "si": "mmol/L"},
        normal_value={"us": 180.0, "si": 4.65},
        flagged_value={"us": 230.0, "si": 5.95},
        ref_low={"us": 0.0, "si": 0.0},  # sentinel: no floor, never printed/read
        ref_high={"us": 200.0, "si": 5.2},
        one_sided="lt",
    ),
    "hdl": AnalyteSpec(
        canonical="HDL Cholesterol",
        synonyms={"canonical": "HDL Cholesterol", "abbrev": "HDL", "caps": "HDL-C"},
        unit={"us": "mg/dL", "si": "mmol/L"},
        normal_value={"us": 55.0, "si": 1.42},
        flagged_value={"us": 32.0, "si": 0.83},
        ref_low={"us": 40.0, "si": 1.0},
        ref_high={"us": 999.0, "si": 999.0},  # sentinel: no ceiling, never printed/read
        one_sided="gt",
    ),
    "tsh": AnalyteSpec(
        canonical="Thyroid Stimulating Hormone",
        synonyms={"canonical": "Thyroid Stimulating Hormone", "abbrev": "TSH", "caps": "TSH"},
        unit={"us": "mIU/L", "si": "mIU/L"},
        normal_value={"us": 2.1, "si": 2.1},
        flagged_value={"us": 6.5, "si": 6.5},
        ref_low={"us": 0.4, "si": 0.4},
        ref_high={"us": 4.0, "si": 4.0},
    ),
}

PANELS: dict[str, list[str]] = {
    "Lipid Panel": ["total_cholesterol", "hdl"],
    "Complete Blood Count (CBC)": ["hemoglobin", "wbc"],
    "Basic Metabolic Panel (BMP)": ["sodium", "potassium", "glucose", "creatinine"],
    "Liver Panel": ["alt"],
    "Thyroid Panel": ["tsh"],
}


@dataclass
class Case:
    doc_id: str
    template: Template
    label_style: LabelStyle
    unit_style: UnitStyle
    range_layout: RangeLayout
    date_style: DateStyle
    flag_style: FlagStyle
    scanned: bool
    patient_id: str
    patient_name: str
    dob: date
    sex: Sex
    physician: str | None
    lab_name: str
    report_date: date
    collection_date: date
    analytes: list[str]
    diagnosis_text: str
    flagged_key: str | None = None
    # analyte key -> (printed value, printed flag) that deliberately overrides
    # what resolve_row() would otherwise compute -- used for the adversarial doc.
    row_overrides: dict[str, tuple[float, Flag]] = field(default_factory=dict)


# --- flag / range / date formatting -------------------------------------


def recompute_flag(value: float, ref_low: float, ref_high: float, one_sided: OneSided) -> Flag:
    """Recompute the normal/abnormal flag from value vs. reference range.

    Mirrors the plausibility check validate.py will implement on Day 2, so
    ground truth already encodes the expected review-routing outcome.
    """
    if one_sided == "lt":
        if value > ref_high * 1.2:
            return Flag.CRITICAL_HIGH
        return Flag.HIGH if value > ref_high else Flag.NORMAL
    if one_sided == "gt":
        if value < ref_low * 0.8:
            return Flag.CRITICAL_LOW
        return Flag.LOW if value < ref_low else Flag.NORMAL
    if value > ref_high:
        return Flag.CRITICAL_HIGH if value > ref_high * 1.2 else Flag.HIGH
    if value < ref_low:
        return Flag.CRITICAL_LOW if value < ref_low * 0.8 else Flag.LOW
    return Flag.NORMAL


def resolve_row(case: Case, key: str) -> tuple[float, Flag]:
    """Return (printed value, printed flag) for one analyte on one doc."""
    if key in case.row_overrides:
        return case.row_overrides[key]
    spec = ANALYTES[key]
    if key == case.flagged_key:
        value = spec.flagged_value[case.unit_style]
    else:
        value = spec.normal_value[case.unit_style]
    printed_flag = recompute_flag(
        value, spec.ref_low[case.unit_style], spec.ref_high[case.unit_style], spec.one_sided
    )
    return value, printed_flag


def format_range(spec: AnalyteSpec, unit_style: UnitStyle) -> str:
    if spec.one_sided == "lt":
        return f"<{spec.ref_high[unit_style]:g}"
    if spec.one_sided == "gt":
        return f">{spec.ref_low[unit_style]:g}"
    return f"{spec.ref_low[unit_style]:g}-{spec.ref_high[unit_style]:g}"


def format_date(d: date, style: DateStyle) -> str:
    if style == "mdy":
        return d.strftime("%m/%d/%Y")
    if style == "dmy":
        return d.strftime("%d.%m.%Y")
    return d.isoformat()


def format_flag(flag: Flag, style: FlagStyle) -> str:
    if style == "letters":
        return "" if flag == Flag.NORMAL else flag.value
    if style == "arrows":
        if flag == Flag.CRITICAL_HIGH:
            return "↑↑"
        if flag == Flag.HIGH:
            return "↑"
        if flag == Flag.CRITICAL_LOW:
            return "↓↓"
        if flag == Flag.LOW:
            return "↓"
        return ""
    if style == "asterisk":
        if flag in (Flag.CRITICAL_HIGH, Flag.CRITICAL_LOW):
            return "**"
        return "" if flag == Flag.NORMAL else "*"
    raise ValueError(style)


# --- ground truth --------------------------------------------------------


def build_result(case: Case, key: str) -> Result:
    spec = ANALYTES[key]
    value, printed_flag = resolve_row(case, key)
    ref_low = spec.ref_low[case.unit_style]
    ref_high = spec.ref_high[case.unit_style]
    computed_flag = recompute_flag(value, ref_low, ref_high, spec.one_sided)
    return Result(
        analyte=spec.canonical,
        value=f"{value:g}",
        unit=spec.unit[case.unit_style],
        ref_range_raw=format_range(spec, case.unit_style),
        ref_low=None if spec.one_sided == "lt" else ref_low,
        ref_high=None if spec.one_sided == "gt" else ref_high,
        printed_flag=printed_flag,
        computed_flag=computed_flag,
        confidence=1.0,  # ground truth is certain, not a pipeline confidence score
        needs_review=printed_flag != computed_flag,
    )


def build_ground_truth(case: Case) -> LabReport:
    results = [build_result(case, key) for key in case.analytes]
    diagnosis = Diagnosis(text=case.diagnosis_text, confidence=1.0)
    return LabReport(
        source_file=f"{case.doc_id}.pdf",
        extraction_model="ground_truth",
        extracted_at=GROUND_TRUTH_TIMESTAMP,
        report_date=case.report_date,
        collection_date=case.collection_date,
        ordering_physician=case.physician,
        lab_name=case.lab_name,
        needs_review=any(r.needs_review for r in results) or case.physician is None,
        patient=Patient(
            patient_id=case.patient_id, name=case.patient_name, dob=case.dob, sex=case.sex
        ),
        results=results,
        diagnoses=[diagnosis],
    )


# --- clean (reportlab) rendering -----------------------------------------


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "LabName": ParagraphStyle("LabName", parent=base["Heading1"], fontSize=16, spaceAfter=6),
        "Meta": ParagraphStyle("Meta", parent=base["Normal"], fontSize=10, leading=13),
        "PanelHeading": ParagraphStyle(
            "PanelHeading", parent=base["Heading2"], fontSize=12, spaceBefore=6, spaceAfter=4
        ),
        "Inline": ParagraphStyle("Inline", parent=base["Normal"], fontSize=10.5, leading=15),
    }


_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbe4ee")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
)


def _table_header(range_layout: RangeLayout) -> list[str]:
    if range_layout == "split":
        return ["Test", "Result", "Units", "Low", "High", "Flag"]
    return ["Test", "Result", "Units", "Reference Range", "Flag"]


def _table_row(case: Case, key: str) -> list[str]:
    spec = ANALYTES[key]
    value, printed_flag = resolve_row(case, key)
    label = spec.synonyms[case.label_style]
    unit = spec.unit[case.unit_style]
    flag_text = format_flag(printed_flag, case.flag_style)
    value_text = f"{value:g}"
    if case.range_layout == "split":
        lo = "-" if spec.one_sided == "lt" else f"{spec.ref_low[case.unit_style]:g}"
        hi = "-" if spec.one_sided == "gt" else f"{spec.ref_high[case.unit_style]:g}"
        return [label, value_text, unit, lo, hi, flag_text]
    return [label, value_text, unit, format_range(spec, case.unit_style), flag_text]


def _header_flowables(case: Case, styles: dict[str, ParagraphStyle]) -> list:
    story = [
        Paragraph(case.lab_name, styles["LabName"]),
        Paragraph(
            f"Patient: {case.patient_name} &nbsp;&nbsp; "
            f"DOB: {format_date(case.dob, case.date_style)} &nbsp;&nbsp; "
            f"Sex: {case.sex.value} &nbsp;&nbsp; Patient ID: {case.patient_id}",
            styles["Meta"],
        ),
    ]
    meta2 = (
        f"Report Date: {format_date(case.report_date, case.date_style)} &nbsp;&nbsp; "
        f"Collection Date: {format_date(case.collection_date, case.date_style)}"
    )
    if case.physician:
        meta2 += f" &nbsp;&nbsp; Ordering Physician: {case.physician}"
    story.append(Paragraph(meta2, styles["Meta"]))
    story.append(Spacer(1, 0.2 * inch))
    return story


def _diagnosis_flowables(case: Case, styles: dict[str, ParagraphStyle]) -> list:
    return [
        Spacer(1, 0.25 * inch),
        Paragraph("Clinical Notes / Impression:", styles["PanelHeading"]),
        Paragraph(case.diagnosis_text, styles["Meta"]),
    ]


def render_clean_pdf(case: Case, path: Path) -> None:
    styles = _styles()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=LETTER,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
    )
    story = _header_flowables(case, styles)

    if case.template == "rows":
        data = [_table_header(case.range_layout)] + [_table_row(case, k) for k in case.analytes]
        table = Table(data, hAlign="LEFT")
        table.setStyle(_TABLE_STYLE)
        story.append(table)
    elif case.template == "panels":
        for panel_name, keys in PANELS.items():
            included = [k for k in keys if k in case.analytes]
            if not included:
                continue
            story.append(Paragraph(panel_name, styles["PanelHeading"]))
            data = [_table_header(case.range_layout)] + [_table_row(case, k) for k in included]
            table = Table(data, hAlign="LEFT")
            table.setStyle(_TABLE_STYLE)
            story.append(table)
            story.append(Spacer(1, 0.15 * inch))
    elif case.template == "inline":
        for key in case.analytes:
            spec = ANALYTES[key]
            value, printed_flag = resolve_row(case, key)
            label = spec.synonyms[case.label_style]
            unit = spec.unit[case.unit_style]
            range_text = format_range(spec, case.unit_style)
            text = f"{label}: {value:g} {unit} (Ref: {range_text})"
            flag_text = format_flag(printed_flag, case.flag_style)
            if flag_text:
                text += f" [{flag_text}]"
            story.append(Paragraph(text, styles["Inline"]))
            story.append(Spacer(1, 0.05 * inch))
    else:
        raise ValueError(case.template)

    story.extend(_diagnosis_flowables(case, styles))
    doc.build(story)


# --- scanned (PIL) rendering ----------------------------------------------

_FONT_CANDIDATES = ["cour.ttf", "consola.ttf", "DejaVuSansMono.ttf", "Menlo.ttc"]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_scanned_pdf(case: Case, path: Path) -> None:
    width, height = 1700, 2200  # ~8.5x11in @ 200dpi
    img = Image.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(img)
    font_title = _load_font(30)
    font_body = _load_font(22)

    y = 60

    def line(text: str, font: ImageFont.ImageFont, dy: int) -> None:
        nonlocal y
        draw.text((60, y), text, fill=0, font=font)
        y += dy

    line(case.lab_name, font_title, 44)
    line(
        f"Patient: {case.patient_name}   DOB: {format_date(case.dob, case.date_style)}   "
        f"Sex: {case.sex.value}   ID: {case.patient_id}",
        font_body,
        32,
    )
    meta2 = (
        f"Report Date: {format_date(case.report_date, case.date_style)}   "
        f"Collection Date: {format_date(case.collection_date, case.date_style)}"
    )
    if case.physician:
        meta2 += f"   Ordering Physician: {case.physician}"
    line(meta2, font_body, 40)

    line(f"{'Test':<26}{'Result':<12}{'Units':<12}{'Reference Range':<18}{'Flag'}", font_body, 32)
    line("-" * 80, font_body, 30)
    for key in case.analytes:
        spec = ANALYTES[key]
        value, printed_flag = resolve_row(case, key)
        label = spec.synonyms[case.label_style]
        unit = spec.unit[case.unit_style]
        range_text = format_range(spec, case.unit_style)
        flag_text = format_flag(printed_flag, case.flag_style)
        line(f"{label:<26}{value:<12g}{unit:<12}{range_text:<18}{flag_text}", font_body, 32)

    y += 20
    line("Clinical Notes / Impression:", font_body, 32)
    for wrapped in textwrap.wrap(case.diagnosis_text, width=90):
        line(wrapped, font_body, 30)

    # hash() is salted per-process -- use a stable hash so jitter (and thus the
    # rendered PDF) is identical across separate runs of this script.
    doc_hash = int(hashlib.md5(case.doc_id.encode()).hexdigest(), 16)
    rng = random.Random(SEED + doc_hash % 1000)
    angle = rng.uniform(-1.6, 1.6)
    img = img.rotate(angle, expand=True, fillcolor=255)
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))

    # Re-encode through low-quality JPEG to introduce scan-like compression artifacts.
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=55)
    buf.seek(0)
    # Pillow's PDF writer stamps its own live CreationDate/ModDate (unrelated to
    # reportlab.rl_config.invariant) -- pin both so reruns are byte-identical.
    fixed_date = GROUND_TRUTH_TIMESTAMP.timetuple()
    Image.open(buf).convert("RGB").save(
        path, "PDF", resolution=200.0, creationDate=fixed_date, modDate=fixed_date
    )


# --- case definitions ------------------------------------------------------

CASES: list[Case] = [
    Case(
        doc_id="doc01_rows_clean",
        template="rows",
        label_style="canonical",
        unit_style="us",
        range_layout="combined",
        date_style="mdy",
        flag_style="letters",
        scanned=False,
        patient_id="P-1001",
        patient_name="Jordan Ellery Voss",
        dob=date(1985, 3, 14),
        sex=Sex.FEMALE,
        physician="Dr. Priya Anand",
        lab_name="Meridian Health Labs",
        report_date=date(2026, 6, 20),
        collection_date=date(2026, 6, 19),
        analytes=["hemoglobin", "wbc", "glucose", "total_cholesterol", "creatinine"],
        flagged_key="hemoglobin",
        diagnosis_text=(
            "Routine annual physical. Mild anemia noted; recommend iron studies follow-up."
        ),
    ),
    Case(
        doc_id="doc02_rows_clean",
        template="rows",
        label_style="abbrev",
        unit_style="si",
        range_layout="split",
        date_style="dmy",
        flag_style="arrows",
        scanned=False,
        patient_id="P-1002",
        patient_name="Casey Nakamura-Reyes",
        dob=date(1978, 11, 2),
        sex=Sex.MALE,
        physician="Dr. Owen Faulkner",
        lab_name="Brightpath Diagnostics",
        report_date=date(2026, 6, 22),
        collection_date=date(2026, 6, 21),
        analytes=["sodium", "potassium", "glucose", "alt", "tsh"],
        flagged_key="glucose",
        diagnosis_text="Follow-up visit for hyperglycemia management; results improving.",
    ),
    Case(
        doc_id="doc03_panels_clean",
        template="panels",
        label_style="caps",
        unit_style="us",
        range_layout="combined",
        date_style="iso",
        flag_style="asterisk",
        scanned=False,
        patient_id="P-1003",
        patient_name="Morgan Feldt",
        dob=date(1992, 7, 22),
        sex=Sex.FEMALE,
        physician="Dr. Elias Thorne",
        lab_name="Northgate Clinical Labs",
        report_date=date(2026, 6, 24),
        collection_date=date(2026, 6, 23),
        analytes=[
            "total_cholesterol",
            "hdl",
            "hemoglobin",
            "wbc",
            "sodium",
            "potassium",
            "glucose",
            "creatinine",
        ],
        flagged_key="hdl",
        diagnosis_text="Lipid panel follow-up; HDL below target, dietary counseling provided.",
    ),
    Case(
        doc_id="doc04_panels_clean",
        template="panels",
        label_style="canonical",
        unit_style="si",
        range_layout="split",
        date_style="mdy",
        flag_style="letters",
        scanned=False,
        patient_id="P-1004",
        patient_name="Avery Kowalczyk",
        dob=date(1966, 1, 30),
        sex=Sex.MALE,
        physician="Dr. Sana Okafor",
        lab_name="Meridian Health Labs",
        report_date=date(2026, 6, 25),
        collection_date=date(2026, 6, 24),
        analytes=["tsh", "alt", "hemoglobin", "wbc"],
        flagged_key="tsh",
        diagnosis_text="Thyroid function follow-up; mild subclinical hypothyroidism suspected.",
    ),
    Case(
        doc_id="doc05_inline_clean",
        template="inline",
        label_style="abbrev",
        unit_style="us",
        range_layout="combined",
        date_style="dmy",
        flag_style="arrows",
        scanned=False,
        patient_id="P-1005",
        patient_name="Riley Bostrom",
        dob=date(2001, 9, 9),
        sex=Sex.FEMALE,
        physician="Dr. Owen Faulkner",
        lab_name="Brightpath Diagnostics",
        report_date=date(2026, 6, 27),
        collection_date=date(2026, 6, 26),
        analytes=["total_cholesterol", "hdl", "glucose", "creatinine", "sodium"],
        flagged_key="creatinine",
        diagnosis_text=(
            "Renal function check; creatinine mildly elevated, "
            "recommend hydration and recheck in 2 weeks."
        ),
    ),
    Case(
        doc_id="doc06_inline_clean",
        template="inline",
        label_style="caps",
        unit_style="si",
        range_layout="combined",
        date_style="iso",
        flag_style="asterisk",
        scanned=False,
        patient_id="P-1006",
        patient_name="Toma Ishikawa-Reed",
        dob=date(1954, 5, 18),
        sex=Sex.MALE,
        physician="Dr. Priya Anand",
        lab_name="Northgate Clinical Labs",
        report_date=date(2026, 6, 28),
        collection_date=date(2026, 6, 27),
        analytes=["hemoglobin", "wbc", "sodium", "potassium", "alt"],
        flagged_key="wbc",
        diagnosis_text="Pre-operative labs; mild leukocytosis, likely reactive, no action needed.",
    ),
    Case(
        doc_id="doc07_rows_scanned",
        template="rows",
        label_style="canonical",
        unit_style="us",
        range_layout="combined",
        date_style="mdy",
        flag_style="letters",
        scanned=True,
        patient_id="P-1007",
        patient_name="Devon Achterberg",
        dob=date(1989, 12, 25),
        sex=Sex.FEMALE,
        physician="Dr. Elias Thorne",
        lab_name="Meridian Health Labs",
        report_date=date(2026, 6, 30),
        collection_date=date(2026, 6, 29),
        analytes=["hemoglobin", "glucose", "creatinine", "sodium", "potassium"],
        flagged_key="sodium",
        diagnosis_text="Electrolyte panel; mild hyponatremia, recommend dietary sodium review.",
    ),
    Case(
        doc_id="doc08_panels_scanned",
        template="panels",
        label_style="abbrev",
        unit_style="si",
        range_layout="combined",
        date_style="dmy",
        flag_style="arrows",
        scanned=True,
        patient_id="P-1008",
        patient_name="Sasha Lindqvist",
        dob=date(1973, 6, 11),
        sex=Sex.MALE,
        physician="Dr. Sana Okafor",
        lab_name="Brightpath Diagnostics",
        report_date=date(2026, 7, 1),
        collection_date=date(2026, 6, 30),
        analytes=["total_cholesterol", "hdl", "glucose", "creatinine"],
        flagged_key="total_cholesterol",
        diagnosis_text=(
            "Lipid screening; total cholesterol elevated, lifestyle modification advised."
        ),
    ),
    Case(
        doc_id="doc09_rows_adversarial",
        template="rows",
        label_style="canonical",
        unit_style="us",
        range_layout="combined",
        date_style="iso",
        flag_style="letters",
        scanned=False,
        patient_id="P-1009",
        patient_name="Corin Whitfield",
        dob=date(1980, 2, 17),
        sex=Sex.FEMALE,
        physician=None,  # missing field: no ordering physician printed on the document
        lab_name="Northgate Clinical Labs",
        report_date=date(2026, 7, 2),
        collection_date=date(2026, 7, 1),
        analytes=["hemoglobin", "glucose", "potassium", "alt"],
        row_overrides={
            # out-of-range critical value, correctly flagged critical-high on the page
            "potassium": (6.8, Flag.CRITICAL_HIGH),
            # wrong printed flag: value is clearly high (ref 70-100) but the page prints "N"
            "glucose": (145.0, Flag.NORMAL),
        },
        diagnosis_text=(
            "Acute presentation; critical hyperkalemia flagged for immediate clinician review. "
            "Glucose result requires manual verification against printed flag."
        ),
    ),
]


def main() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    GT_DIR.mkdir(parents=True, exist_ok=True)

    for case in CASES:
        pdf_path = PDF_DIR / f"{case.doc_id}.pdf"
        gt_path = GT_DIR / f"{case.doc_id}.json"

        if case.scanned:
            render_scanned_pdf(case, pdf_path)
        else:
            render_clean_pdf(case, pdf_path)

        report = build_ground_truth(case)
        gt_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

        kind = "scanned" if case.scanned else "clean"
        print(f"wrote {pdf_path.name} + {gt_path.name} ({kind}, {case.template})")


if __name__ == "__main__":
    main()
