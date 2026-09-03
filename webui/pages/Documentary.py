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
from app.services.documentary import images as images_service
from app.services.documentary import pipeline, scriptwriter, store
from app.utils import utils

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
    store.STATUS_SOURCING_IMAGES: "🖼 Sourcing images…",
    store.STATUS_IMAGE_REVIEW: "🖼 Images awaiting review",
    store.STATUS_RENDERING: "🎞 Rendering…",
    store.STATUS_DONE: "🏁 Done",
    store.STATUS_FAILED: "❌ Failed",
}

serpapi_ready = bool(str(config.documentary.get("serpapi_api_key", "")).strip())
if not serpapi_ready:
    st.warning(
        "`documentary.serpapi_api_key` is empty in config.toml — research "
        "will fail until it is set.",
        icon="🔑",
    )

# ------------------------------------------------------------ voice settings
with st.expander("🎙 Narration voice settings"):
    from app.services import voice as voice_service

    current_voice = str(
        config.documentary.get("voice_name", "en-GB-RyanNeural-Male")
    )
    st.caption(f"Current narration voice: `{current_voice}`")

    key_col, fetch_col = st.columns([3, 1], vertical_alignment="bottom")
    elevenlabs_key = key_col.text_input(
        "ElevenLabs API key",
        value=str(config.elevenlabs.get("api_key", "") or ""),
        type="password",
        help="Stored in config.toml under [elevenlabs]. Favorite voices in "
        "your ElevenLabs voice library are the ones listed here.",
    )
    if elevenlabs_key != str(config.elevenlabs.get("api_key", "") or ""):
        config.elevenlabs["api_key"] = elevenlabs_key
        config.save_config()
    if fetch_col.button("Fetch voices", disabled=not elevenlabs_key.strip()):
        with st.spinner("Fetching your ElevenLabs voices…"):
            st.session_state["doc_el_voices"] = voice_service.get_elevenlabs_voices(
                elevenlabs_key.strip()
            )
        if not st.session_state["doc_el_voices"]:
            st.error(
                "No voices returned — check the API key, and note only "
                "voices marked as favorites in ElevenLabs are listed."
            )

    edge_voices = [
        "en-GB-RyanNeural-Male",
        "en-GB-ThomasNeural-Male",
        "en-GB-SoniaNeural-Female",
        "en-US-GuyNeural-Male",
        "en-US-ChristopherNeural-Male",
        "en-NG-AbeoNeural-Male",
        "en-NG-EzinneNeural-Female",
    ]
    voice_options = edge_voices + st.session_state.get("doc_el_voices", [])
    if current_voice not in voice_options:
        voice_options.insert(0, current_voice)
    chosen_voice = st.selectbox(
        "Narration voice (Edge TTS voices, plus ElevenLabs after fetching)",
        voice_options,
        index=voice_options.index(current_voice),
        format_func=lambda v: (
            f"ElevenLabs · {v.split(':', 2)[2]}"
            if v.startswith("elevenlabs:")
            else f"Edge · {v}"
        ),
    )
    if chosen_voice != current_voice:
        config.documentary["voice_name"] = chosen_voice
        config.save_config()
        st.success(f"Narration voice saved: {chosen_voice}")

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
        target_minutes = st.slider(
            "Target length (minutes of narration)",
            min_value=3.0,
            max_value=20.0,
            value=10.0,
            step=0.5,
        )
        col_a, col_b, col_c = st.columns(3)
        auto_factsheet = col_a.checkbox("Auto-approve fact sheet", value=False)
        auto_script = col_b.checkbox("Auto-approve script", value=False)
        auto_images = col_c.checkbox(
            "Auto-approve images",
            value=False,
            help="The vision model scores every candidate and the best one "
            "is used without review; rendering follows automatically.",
        )
        if st.form_submit_button("Create project", type="primary"):
            if not topic.strip():
                st.error("Topic is required.")
            else:
                project = store.create_project(
                    topic=topic,
                    user_notes=user_notes,
                    auto_approve_factsheet=auto_factsheet,
                    auto_approve_script=auto_script,
                    auto_approve_images=auto_images,
                    target_minutes=target_minutes,
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

elif status in (
    store.STATUS_RESEARCHING,
    store.STATUS_SCRIPTING,
    store.STATUS_SOURCING_IMAGES,
    store.STATUS_RENDERING,
):
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
            "Script approved. Next: source candidate images for every "
            "paragraph (Wikimedia Commons, Openverse, Pexels, Pixabay)."
        )
        source_col, download_col = st.columns(2)
        if source_col.button("🖼 Source images", type="primary"):
            _run_with_spinner(
                "Sourcing candidate images for every paragraph — searching "
                "four providers and downloading candidates. This can take a "
                "few minutes…",
                pipeline.run_image_sourcing_stage,
                project,
            )
        download_col.download_button(
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

elif status == store.STATUS_IMAGE_REVIEW:
    images = store.load_images(selected_id) or {"items": []}
    items = images.get("items", [])
    st.subheader("Image review")
    unresolved = sum(
        1 for item in items if not images_service.selected_image_path(item)
    )
    if unresolved:
        st.warning(
            f"{unresolved} paragraph(s) still need an image — pick a candidate, "
            "re-search with a better query, or upload your own."
        )
    else:
        st.success("Every paragraph has an image selected.")

    for item_idx, item in enumerate(items):
        item_key = item["key"]
        has_image = bool(images_service.selected_image_path(item))
        with st.expander(
            f"{'🟢' if has_image else '🔴'} {item['section']} · {item['cue'][:70]}",
            expanded=not has_image,
        ):
            st.caption(item["text_preview"])
            candidates = item.get("candidates", [])
            if candidates:
                cols = st.columns(min(len(candidates), 3))
                for cand_idx, candidate in enumerate(candidates):
                    with cols[cand_idx % len(cols)]:
                        if os.path.exists(candidate.get("local_path", "")):
                            st.image(candidate["local_path"])
                        score = candidate.get("score")
                        score_text = (
                            f" · ⭐ {score:g}" if isinstance(score, (int, float))
                            else ""
                        )
                        st.caption(
                            f"{candidate['provider']} · "
                            f"{candidate.get('license', '?')}{score_text}"
                            + (
                                f" · [source]({candidate['page_url']})"
                                if candidate.get("page_url")
                                else ""
                            )
                        )
                        if candidate.get("score_reason"):
                            st.caption(f"_{candidate['score_reason'][:90]}_")
                current = item.get("selected")
                options = list(range(len(candidates)))
                selection = st.radio(
                    "Use candidate",
                    options,
                    index=current if isinstance(current, int) else 0,
                    format_func=lambda i, c=candidates: (
                        f"#{i + 1} ({c[i]['provider']})"
                    ),
                    horizontal=True,
                    key=f"img_sel_{item_key}",
                )
                if selection != current and isinstance(selection, int):
                    item["selected"] = selection
                    store.save_images(selected_id, images)
            else:
                st.info("No candidates found for this cue.")

            search_col, upload_col = st.columns(2)
            with search_col:
                new_query = st.text_input(
                    "Re-search query",
                    value=item.get("queries", {}).get("archival", ""),
                    key=f"img_q_{item_key}",
                )
                if st.button("🔎 Re-search", key=f"img_rs_{item_key}"):
                    with st.spinner("Searching providers…"):
                        images_service.research_cue(
                            selected_id, item_key, new_query
                        )
                    st.rerun()
            with upload_col:
                uploaded = st.file_uploader(
                    "Or upload your own image",
                    type=["jpg", "jpeg", "png"],
                    key=f"img_up_{item_key}",
                )
                if uploaded is not None:
                    custom_path = os.path.join(
                        store.images_dir(selected_id),
                        f"{item_key}-custom-{uploaded.name}",
                    )
                    with open(custom_path, "wb") as f:
                        f.write(uploaded.getbuffer())
                    if item.get("selected") != {"custom": custom_path}:
                        item["selected"] = {"custom": custom_path}
                        store.save_images(selected_id, images)
                        st.rerun()
                if isinstance(item.get("selected"), dict):
                    st.caption("✅ Using uploaded image")

    approve_col, resource_col = st.columns(2)
    if approve_col.button(
        "✅ Approve images & render", type="primary", disabled=unresolved > 0
    ):
        _run_with_spinner(
            "Rendering — narration TTS, Ken Burns segments, final mux. "
            "A 10-minute film can take a while; leave this page open…",
            pipeline.approve_images,
            project,
        )
    if resource_col.button("🔁 Re-source all images"):
        _run_with_spinner(
            "Re-sourcing images for all paragraphs…",
            pipeline.run_image_sourcing_stage,
            project,
        )

elif status == store.STATUS_DONE:
    st.subheader("🏁 Finished film")
    final_path = os.path.join(utils.task_dir(selected_id), "final-1.mp4")
    if os.path.exists(final_path):
        st.video(final_path)
        st.caption(
            "The film is also in the Video Library, so the existing YouTube "
            "upload and scheduling flows can use it."
        )
        srt_path = os.path.join(utils.task_dir(selected_id), "final-1.srt")
        if os.path.exists(srt_path):
            with open(srt_path, "r", encoding="utf-8") as f:
                st.download_button(
                    "⬇️ Download subtitles (.srt)",
                    f.read(),
                    file_name=f"{selected_id}.srt",
                )
    else:
        st.error("Final video not found on disk.")
        if st.button("🔁 Re-render"):
            _run_with_spinner(
                "Re-rendering…", pipeline.approve_images, project
            )
