"""Documentary studio page: research → fact sheet review → script review.

Phase 1 of the long-form documentary pipeline. Each project pauses at human
checkpoints (fact sheet, script); approving moves it forward. Image sourcing
and rendering attach after script approval in phase 2.
"""
import os
import sys
from datetime import datetime

import pandas as pd
import streamlit as st

# Same as webui/Main.py: make sure the project root wins over any third-party
# package that happens to be named "app".
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

from app.config import config
from app.services.documentary import pipeline, scriptwriter, store

st.set_page_config(page_title="Documentary Studio", page_icon="🎬", layout="wide")

st.page_link("Main.py", label="Back to generator", icon=":material/arrow_back:")
st.title("🎬 Documentary Studio")
st.caption(
    "Long-form still-image documentaries: web-grounded research, a sourced "
    "fact sheet you review, then a script in a restrained archival register."
)

STATUS_LABELS = {
    store.STATUS_CREATED: "🆕 Ready to research",
    store.STATUS_RESEARCHING: "🔎 Researching…",
    store.STATUS_FACTSHEET_REVIEW: "📋 Fact sheet awaiting review",
    store.STATUS_SCRIPTING: "✍️ Writing script…",
    store.STATUS_SCRIPT_REVIEW: "📜 Script awaiting review",
    store.STATUS_SCRIPT_APPROVED: "✅ Script approved",
    store.STATUS_FAILED: "❌ Failed",
}

serpapi_ready = bool(str(config.documentary.get("serpapi_api_key", "")).strip())
if not serpapi_ready:
    st.warning(
        "`documentary.serpapi_api_key` is empty in config.toml — research "
        "will fail until it is set.",
        icon="🔑",
    )

# ---------------------------------------------------------------- new project
with st.expander("➕ New documentary project", expanded=not store.list_projects()):
    with st.form("new_project"):
        topic = st.text_input(
            "Topic",
            placeholder="e.g. The 2002 Lagos armoury explosion",
        )
        user_notes = st.text_area(
            "Background notes / research you already have (optional)",
            height=120,
            help="Treated as a privileged source during research.",
        )
        col_a, col_b = st.columns(2)
        auto_factsheet = col_a.checkbox("Auto-approve fact sheet", value=False)
        auto_script = col_b.checkbox("Auto-approve script", value=False)
        if st.form_submit_button("Create project", type="primary"):
            if not topic.strip():
                st.error("Topic is required.")
            else:
                project = store.create_project(
                    topic=topic,
                    user_notes=user_notes,
                    auto_approve_factsheet=auto_factsheet,
                    auto_approve_script=auto_script,
                )
                st.session_state["doc_selected"] = project["project_id"]
                st.rerun()

projects = store.list_projects()
if not projects:
    st.info("No documentary projects yet — create one above.")
    st.stop()

# ------------------------------------------------------------ project picker
labels = {
    p["project_id"]: (
        f"{p['topic'][:60]}  ·  {STATUS_LABELS.get(p['status'], p['status'])}"
    )
    for p in projects
}
default_id = st.session_state.get("doc_selected", projects[0]["project_id"])
project_ids = [p["project_id"] for p in projects]
selected_id = st.selectbox(
    "Project",
    project_ids,
    index=project_ids.index(default_id) if default_id in project_ids else 0,
    format_func=lambda pid: labels[pid],
)
st.session_state["doc_selected"] = selected_id
project = store.load_project(selected_id)
if not project:
    st.error("Project metadata missing on disk.")
    st.stop()

status = project["status"]
created = datetime.fromtimestamp(project["created_at"]).strftime("%b %d, %Y %H:%M")
meta_col, del_col = st.columns([5, 1], vertical_alignment="center")
meta_col.markdown(
    f"**{project['topic']}**  \n"
    f"{STATUS_LABELS.get(status, status)} · created {created}"
)
with del_col.popover("🗑 Delete"):
    st.caption("Removes this project's research, fact sheet and script from disk.")
    if st.button("Delete permanently", type="primary", key="doc_delete"):
        store.delete_project(selected_id)
        st.session_state.pop("doc_selected", None)
        st.rerun()

if project.get("user_notes"):
    with st.expander("Producer notes"):
        st.text(project["user_notes"])


def _run_with_spinner(label: str, fn, *args):
    try:
        with st.spinner(label):
            fn(*args)
    except Exception as exc:
        st.error(f"{exc}")
    st.rerun()


# ----------------------------------------------------------------- by status
if status == store.STATUS_CREATED:
    st.markdown(
        "Research will search the web (SerpApi), fetch the most relevant "
        "sources, and distill a fact sheet with per-claim sources for review."
    )
    if st.button("🔎 Start research", type="primary", disabled=not serpapi_ready):
        _run_with_spinner(
            "Researching — searching, fetching sources, distilling facts. "
            "This can take a few minutes…",
            pipeline.run_research_stage,
            project,
        )

elif status in (store.STATUS_RESEARCHING, store.STATUS_SCRIPTING):
    st.info(
        "This project shows an in-progress stage. If the page was closed "
        "mid-run, the stage was interrupted — restart it below."
    )
    if st.button("↩️ Restart interrupted stage"):
        _run_with_spinner("Restarting stage…", pipeline.retry_failed, project)

elif status == store.STATUS_FAILED:
    st.error(f"Stage failed: {project.get('error', 'unknown error')}")
    if st.button("🔁 Retry", type="primary"):
        _run_with_spinner("Retrying failed stage…", pipeline.retry_failed, project)

elif status == store.STATUS_FACTSHEET_REVIEW:
    factsheet = store.load_factsheet(selected_id) or {}
    st.subheader("Fact sheet review")
    if factsheet.get("summary"):
        st.markdown(f"> {factsheet['summary']}")

    source_index = factsheet.get("source_index", [])
    with st.expander(f"Sources ({len(source_index)})"):
        for source in source_index:
            st.markdown(
                f"- **{source['label']}** · [{source['title'] or source['url']}]"
                f"({source['url']}) · `{source['domain']}`"
            )

    # Flatten facts for tabular editing; edits are written back on save.
    url_by_id = {}
    rows = []
    for section, facts in (factsheet.get("sections") or {}).items():
        for fact in facts:
            url_by_id[fact["id"]] = fact.get("source_urls", [])
            rows.append(
                {
                    "keep": True,
                    "id": fact["id"],
                    "section": section,
                    "claim": fact["claim"],
                    "quote": fact.get("quote", ""),
                    "confidence": fact.get("confidence", "medium"),
                    "sources": ", ".join(fact.get("sources", [])),
                }
            )
    edited = st.data_editor(
        pd.DataFrame(rows),
        num_rows="dynamic",
        use_container_width=True,
        height=440,
        column_config={
            "keep": st.column_config.CheckboxColumn("keep", width="small"),
            "id": st.column_config.TextColumn("id", disabled=True, width="small"),
            "section": st.column_config.SelectboxColumn(
                "section", options=list(factsheet.get("sections", {}).keys())
            ),
            "claim": st.column_config.TextColumn("claim", width="large"),
            "confidence": st.column_config.SelectboxColumn(
                "confidence", options=["high", "medium", "low"], width="small"
            ),
        },
        key="factsheet_editor",
    )

    if factsheet.get("conflicting_reports"):
        with st.expander("⚖️ Conflicting reports", expanded=True):
            for conflict in factsheet["conflicting_reports"]:
                st.markdown(f"**{conflict.get('issue', '')}**")
                for version in conflict.get("versions", []):
                    st.markdown(
                        f"- {version.get('claim', '')} "
                        f"({', '.join(version.get('sources', []))})"
                    )
    if factsheet.get("open_questions"):
        with st.expander("❓ Open questions"):
            for question in factsheet["open_questions"]:
                st.markdown(f"- {question}")

    def _save_factsheet_edits() -> dict:
        sections: dict[str, list] = {
            name: [] for name in factsheet.get("sections", {})
        }
        counter = 0
        for _, row in edited.iterrows():
            if not row.get("keep", True) or not str(row.get("claim", "")).strip():
                continue
            counter += 1
            section = str(row.get("section") or "background")
            fact_id = str(row.get("id") or f"F{counter}")
            sections.setdefault(section, []).append(
                {
                    "id": fact_id,
                    "claim": str(row["claim"]).strip(),
                    "quote": str(row.get("quote", "") or "").strip(),
                    "sources": [
                        s.strip()
                        for s in str(row.get("sources", "") or "").split(",")
                        if s.strip()
                    ]
                    or ["producer"],
                    "source_urls": url_by_id.get(fact_id, []),
                    "confidence": str(row.get("confidence", "medium")),
                }
            )
        factsheet["sections"] = sections
        store.save_factsheet(selected_id, factsheet)
        return factsheet

    save_col, approve_col, rerun_col = st.columns(3)
    if save_col.button("💾 Save edits"):
        _save_factsheet_edits()
        st.success("Fact sheet saved.")
    if approve_col.button("✅ Approve & write script", type="primary"):
        _save_factsheet_edits()
        _run_with_spinner(
            "Writing the script from the approved fact sheet…",
            pipeline.approve_factsheet,
            project,
        )
    if rerun_col.button("🔁 Re-run research"):
        _run_with_spinner(
            "Re-running research from scratch…",
            pipeline.run_research_stage,
            project,
        )

elif status in (store.STATUS_SCRIPT_REVIEW, store.STATUS_SCRIPT_APPROVED):
    script = store.load_script(selected_id) or {}
    approved = status == store.STATUS_SCRIPT_APPROVED
    st.subheader("Script" + (" (approved)" if approved else " review"))
    st.markdown(
        f"**{script.get('title', project['topic'])}** · "
        f"{script.get('word_count', 0)} words · "
        f"~{script.get('word_count', 0) // 150} min narration"
    )

    for section_idx, section in enumerate(script.get("sections", [])):
        with st.expander(
            f"{section.get('name', f'section {section_idx + 1}').replace('_', ' ').title()}",
            expanded=section_idx == 0,
        ):
            for para_idx, paragraph in enumerate(section.get("paragraphs", [])):
                key = f"doc_para_{section_idx}_{para_idx}"
                if approved:
                    st.markdown(paragraph.get("text", ""))
                    st.caption(f"🖼 {paragraph.get('image_cue', '')}")
                else:
                    st.text_area(
                        "Narration",
                        value=paragraph.get("text", ""),
                        key=f"{key}_text",
                        height=110,
                        label_visibility="collapsed",
                    )
                    cue_col, facts_col = st.columns([3, 1])
                    cue_col.text_input(
                        "Image cue",
                        value=paragraph.get("image_cue", ""),
                        key=f"{key}_cue",
                    )
                    facts_col.caption(
                        "Facts: " + (", ".join(paragraph.get("fact_ids", [])) or "—")
                    )

    youtube_meta = script.get("youtube", {})
    with st.expander("YouTube metadata"):
        st.markdown(
            f"**Title:** {youtube_meta.get('title', '')}  \n"
            f"**Description:** {youtube_meta.get('description', '')}  \n"
            f"**Tags:** {', '.join(youtube_meta.get('tags', []))}"
        )

    if approved:
        st.success(
            "Script approved. Image sourcing and rendering arrive in phase 2 — "
            "meanwhile you can download the narration below."
        )
        st.download_button(
            "⬇️ Download narration text",
            scriptwriter.full_narration_text(script),
            file_name=f"{selected_id}-narration.txt",
        )
    else:

        def _save_script_edits():
            for section_idx, section in enumerate(script.get("sections", [])):
                for para_idx, paragraph in enumerate(section.get("paragraphs", [])):
                    key = f"doc_para_{section_idx}_{para_idx}"
                    text_value = st.session_state.get(f"{key}_text")
                    cue_value = st.session_state.get(f"{key}_cue")
                    if text_value is not None:
                        paragraph["text"] = text_value.strip()
                    if cue_value is not None:
                        paragraph["image_cue"] = cue_value.strip()
            script["word_count"] = len(
                scriptwriter.full_narration_text(script).split()
            )
            store.save_script(selected_id, script)

        save_col, approve_col, regen_col = st.columns(3)
        if save_col.button("💾 Save edits"):
            _save_script_edits()
            st.success("Script saved.")
        if approve_col.button("✅ Approve script", type="primary"):
            _save_script_edits()
            pipeline.approve_script(project)
            st.rerun()
        if regen_col.button("🔁 Regenerate from fact sheet"):
            _run_with_spinner(
                "Regenerating the script…", pipeline.approve_factsheet, project
            )
