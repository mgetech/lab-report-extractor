"""Streamlit UI: upload a lab report, view extracted fields/confidence/flags, browse the review queue.

Talks only to the C# API (never the Python extractor directly), matching the production flow:
Streamlit -> C# API -> Python extractor -> C# API -> Postgres -> UI.
"""

import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_URL = os.environ.get("API_URL", "http://localhost:5005")

FLAG_LABELS = {
    "N": "Normal",
    "H": "High",
    "L": "Low",
    "HH": "Critical High",
    "LL": "Critical Low",
}


def upload_document(file) -> dict:
    response = requests.post(
        f"{API_URL}/documents",
        files={"file": (file.name, file.getvalue(), file.type or "application/octet-stream")},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def fetch_documents(needs_review_only: bool) -> list[dict]:
    params = {"needsReview": "true"} if needs_review_only else {}
    response = requests.get(f"{API_URL}/documents", params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_document(report_id: int) -> dict:
    response = requests.get(f"{API_URL}/documents/{report_id}", timeout=30)
    response.raise_for_status()
    return response.json()


def flag_badge(flag: str | None) -> str:
    if flag is None:
        return "—"
    label = FLAG_LABELS.get(flag, flag)
    if flag in ("HH", "LL"):
        return f"🔴 {label}"
    if flag in ("H", "L"):
        return f"🟠 {label}"
    return f"🟢 {label}"


def confidence_badge(confidence: float) -> str:
    pct = f"{confidence:.0%}"
    if confidence >= 0.9:
        return f"🟢 {pct}"
    if confidence >= 0.7:
        return f"🟡 {pct}"
    return f"🔴 {pct}"


def render_report(report: dict) -> None:
    patient = report["patient"]
    col1, col2, col3 = st.columns(3)
    col1.metric("Patient", patient["name"])
    col2.metric("Report date", report.get("report_date") or "—")
    col3.metric("Needs review", "Yes" if report["needs_review"] else "No")

    with st.expander("Patient & report details"):
        st.write(
            {
                "Patient ID": patient["patient_id"],
                "DOB": patient.get("dob") or "—",
                "Sex": patient.get("sex") or "—",
                "Collection date": report.get("collection_date") or "—",
                "Ordering physician": report.get("ordering_physician") or "—",
                "Lab name": report.get("lab_name") or "—",
                "Source file": report["source_file"],
                "Extraction model": report["extraction_model"],
                "Extracted at": report["extracted_at"],
            }
        )

    results = report.get("results", [])
    if results:
        st.subheader("Results")
        st.dataframe(
            [
                {
                    "Analyte": r["analyte"],
                    "Value": r["value"],
                    "Unit": r.get("unit") or "",
                    "Reference range": r.get("ref_range_raw") or "",
                    "Printed flag": flag_badge(r.get("printed_flag")),
                    "Computed flag": flag_badge(r.get("computed_flag")),
                    "Confidence": confidence_badge(r["confidence"]),
                    "Needs review": "⚠️ Yes" if r["needs_review"] else "No",
                }
                for r in results
            ],
            use_container_width=True,
            hide_index=True,
        )

    diagnoses = report.get("diagnoses", [])
    if diagnoses:
        st.subheader("Diagnoses")
        st.dataframe(
            [
                {"Diagnosis": d["text"], "Confidence": confidence_badge(d["confidence"])}
                for d in diagnoses
            ],
            use_container_width=True,
            hide_index=True,
        )


def upload_tab() -> None:
    st.subheader("Upload a lab report")
    uploaded = st.file_uploader("PDF", type=["pdf"])
    if uploaded is not None and st.button("Extract", type="primary"):
        with st.spinner("Extracting..."):
            try:
                report = upload_document(uploaded)
            except requests.HTTPError as exc:
                st.error(f"Extraction failed: {exc.response.text}")
                return
            except requests.RequestException as exc:
                st.error(f"Could not reach the API: {exc}")
                return
        st.success(f"Extracted report #{report['id']}")
        render_report(report)


def review_queue_tab() -> None:
    st.subheader("Review")
    needs_review_only = st.checkbox("Needs review only", value=True)
    try:
        summaries = fetch_documents(needs_review_only)
    except requests.RequestException as exc:
        st.error(f"Could not reach the API: {exc}")
        return

    if not summaries:
        st.info("No documents.")
        return

    st.dataframe(
        [
            {
                "ID": s["id"],
                "Patient": s["patient_name"],
                "Source file": s["source_file"],
                "Report date": s.get("report_date") or "—",
                "Extracted at": s["extracted_at"],
                "Needs review": "⚠️ Yes" if s["needs_review"] else "No",
                "Flagged results": s["results_needing_review_count"],
            }
            for s in summaries
        ],
        use_container_width=True,
        hide_index=True,
    )

    ids = [s["id"] for s in summaries]
    selected_id = st.selectbox("View report", ids, format_func=lambda i: f"#{i}")
    if selected_id is not None:
        try:
            report = fetch_document(selected_id)
        except requests.RequestException as exc:
            st.error(f"Could not reach the API: {exc}")
            return
        render_report(report)


def main() -> None:
    st.set_page_config(page_title="Lab Report Extractor", page_icon="🧪", layout="wide")
    _, center, _ = st.columns([1, 4, 1])
    with center:
        st.title("🧪 Lab Report Extractor")
        tab_upload, tab_queue = st.tabs(["Upload", "Review"])
        with tab_upload:
            upload_tab()
        with tab_queue:
            review_queue_tab()


if __name__ == "__main__":
    main()