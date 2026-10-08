"""The 💬 Assistant tab of the Analytics page.

Left: saved chats (open, rename, delete, delete all). Right: the open chat,
its model, data range and attached metric tags, the conversation and the
input box. Runs as a fragment, so chatting doesn't redraw the charts on the
other tabs.
"""
from datetime import datetime

import pandas as pd
import streamlit as st

from app.config import config
from app.services.analytics import assistant, catalog, report, tags
from app.services.animation import llm as anim_llm

_CHAT = "assistant_chat"
_PENDING = "assistant_pending"
_PREVIEW = "assistant_tag_preview"
_STUDIO_CHOICES = ["", *catalog.STUDIOS]


def _studio_label(studio: str) -> str:
    return catalog.STUDIO_LABELS.get(studio, "All studios") if studio else "All studios"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _catalogue() -> list[dict]:
    return anim_llm.openrouter_models(timeout=8)


def _price(value) -> str:
    return "?" if value is None else "free" if value == 0 else f"${value:g}"


def _current_chat() -> dict:
    chat = st.session_state.get(_CHAT)
    if not chat:
        chat = assistant.new_chat()
        st.session_state[_CHAT] = chat
    return chat


def _open(chat: dict) -> None:
    st.session_state[_CHAT] = chat
    st.session_state.pop(_PENDING, None)


def _persist(chat: dict) -> None:
    """Settings changes are saved only for chats that already exist on disk."""
    if chat.get("messages"):
        assistant.save_chat(chat)


# ------------------------------------------------------------------ history
def _history_panel(chat: dict) -> None:
    if st.button("＋ New chat", type="primary", use_container_width=True, key="assistant_new"):
        _open(assistant.new_chat(refs=chat.get("refs"), data_range=chat.get("range", assistant.DEFAULT_RANGE)))
        st.rerun(scope="fragment")
    chats = assistant.list_chats()
    st.caption(f"{len(chats)} saved chat{'s' if len(chats) != 1 else ''}")
    with st.container(height=520, border=False):
        for saved in chats:
            active = saved["id"] == chat["id"]
            open_col, menu_col = st.columns([5, 1], vertical_alignment="center")
            when = datetime.fromtimestamp(saved.get("updated_at") or 0).strftime("%b %d, %H:%M")
            if open_col.button(
                ("▸ " if active else "") + (saved["title"] or assistant.NEW_CHAT_TITLE)[:42],
                key=f"assistant_open_{saved['id']}",
                use_container_width=True,
                type="secondary",
                help=f"{saved['messages']} messages · {when} · {saved.get('model', '')}",
            ):
                loaded = assistant.load_chat(saved["id"])
                if loaded:
                    _open(loaded)
                    st.rerun(scope="fragment")
            with menu_col.popover("⋯"):
                title = st.text_input("Rename", value=saved["title"], key=f"assistant_rename_{saved['id']}")
                if st.button("Save name", key=f"assistant_rename_btn_{saved['id']}"):
                    renamed = assistant.rename_chat(saved["id"], title)
                    if active:
                        _open(renamed)
                    st.rerun(scope="fragment")
                if st.button("🗑 Delete chat", key=f"assistant_delete_{saved['id']}", type="primary"):
                    assistant.delete_chat(saved["id"])
                    if active:
                        _open(assistant.new_chat(refs=chat.get("refs")))
                    st.rerun(scope="fragment")
    if chats:
        with st.popover("🗑 Delete all chats", use_container_width=True):
            st.caption(f"Deletes all {len(chats)} saved chats. This can't be undone.")
            if st.button("Delete them all", type="primary", key="assistant_delete_all"):
                assistant.delete_all_chats()
                _open(assistant.new_chat(refs=chat.get("refs")))
                st.rerun(scope="fragment")


# ------------------------------------------------------------------- models
def _model_picker(chat: dict) -> None:
    try:
        catalogue = _catalogue()
    except Exception:
        catalogue = []
    by_id = {m["id"]: m for m in catalogue}
    current = chat.get("model") or assistant.default_model()
    options = list(by_id) if current in by_id else [current, *by_id]

    def label(model_id: str) -> str:
        m = by_id.get(model_id)
        return f"{model_id} · {_price(m['prompt'])} in / {_price(m['completion'])} out per 1M" if m else f"{model_id} · custom ID"

    pick_col, type_col = st.columns([3, 2])
    chosen = pick_col.selectbox(
        "Model", options, index=options.index(current), format_func=label,
        key=f"assistant_model::{chat['id']}::{current}",
        help="Any OpenRouter model. Your pick becomes the default for new chats.",
    )
    typed = type_col.text_input("…or type a model ID", key=f"assistant_model_typed::{chat['id']}", placeholder="e.g. anthropic/claude-sonnet-5")
    chosen = typed.strip() or chosen
    if chosen != current:
        chat["model"] = chosen
        assistant.set_default_model(chosen)
        _persist(chat)
        st.rerun(scope="fragment")


# --------------------------------------------------------------------- tags
def _filter_text(tag: dict) -> str:
    parts = [f"{report.DIMENSION_LABELS.get(d, d)} = {', '.join(v)}" for d, v in (tag.get("filters") or {}).items()]
    if tag.get("group_by"):
        parts.append(f"by {report.DIMENSION_LABELS.get(tag['group_by'], tag['group_by'])}")
    return " · ".join(parts) or "every video"


def _tag_manager(df: pd.DataFrame) -> None:
    # Widget values can only be reset before the widgets are drawn.
    if st.session_state.pop("assistant_tag_reset", False):
        for key in [k for k in st.session_state if k.startswith(("assistant_tag_name", "assistant_tag_desc", "assistant_tag_dim", "assistant_tag_values", "assistant_tag_group"))]:
            del st.session_state[key]
    built_in = tags.builtin_tags(df)
    custom = tags.custom_tags()
    st.caption(
        f"**{len(built_in)} built-in tags** cover every metric the studios record today: each animation style "
        "setting, each Shorts and documentary setting, topic categories, batches and more. They're built from "
        "the data, so a style setting the studios start recording later shows up here by itself. Create your own "
        "to focus on a slice, like \"Space animations\" or \"Fables with animals\"."
    )
    for tag in custom:
        info_col, del_col = st.columns([6, 1], vertical_alignment="center")
        info_col.markdown(f"🏷 **{tag['name']}** · {_studio_label(tag['studio'])} · {_filter_text(tag)}" + (f"  \n{tag['description']}" if tag.get("description") else ""))
        if del_col.button("🗑", key=f"assistant_tag_del_{tag['id']}", help="Delete this tag"):
            tags.delete_tag(tag["id"])
            st.rerun(scope="fragment")

    st.markdown("**New tag**")
    name_col, studio_col = st.columns([3, 2])
    name = name_col.text_input("Name", key="assistant_tag_name", placeholder="e.g. Space animations")
    studio = studio_col.selectbox("Studio", _STUDIO_CHOICES, format_func=_studio_label, key="assistant_tag_studio")
    dims = assistant.filter_dimensions(df, studio)
    filters = {}
    for n in (1, 2):
        dim_col, values_col = st.columns([2, 3])
        dim = dim_col.selectbox(
            f"Only videos where… ({n})", ["", *dims], format_func=lambda d: report.DIMENSION_LABELS.get(d, d) if d else "(no filter)",
            key=f"assistant_tag_dim{n}::{studio}",
        )
        if dim:
            values = values_col.multiselect("is any of", assistant.dimension_values(df, studio, dim), key=f"assistant_tag_values{n}::{studio}::{dim}")
            if values:
                filters[dim] = values
    group_col, desc_col = st.columns([2, 3])
    group_by = group_col.selectbox(
        "Show", ["", *dims], format_func=lambda d: f"Broken down by {report.DIMENSION_LABELS.get(d, d)}" if d else "Each video (titles & numbers)",
        key=f"assistant_tag_group::{studio}",
    )
    description = desc_col.text_input("Note for the assistant (optional)", key="assistant_tag_desc", placeholder="e.g. my newer cut-out style")
    preview_col, save_col = st.columns(2)
    draft = {"id": "draft", "name": name or "Draft tag", "kind": "breakdown" if group_by else "videos", "studio": studio, "group_by": group_by, "filters": filters, "description": description}
    if preview_col.button("👁 Preview what the assistant sees", use_container_width=True, key="assistant_tag_preview_btn"):
        st.session_state[_PREVIEW] = tags.render(draft, df)["text"]
    if save_col.button("💾 Save tag", type="primary", use_container_width=True, key="assistant_tag_save"):
        try:
            tags.save_tag(name, studio, filters, group_by, description)
            st.session_state.pop(_PREVIEW, None)
            st.session_state["assistant_tag_reset"] = True
            st.toast(f"Tag saved: {name}", icon="🏷")
            st.rerun(scope="fragment")
        except ValueError as exc:
            st.error(str(exc))
    if st.session_state.get(_PREVIEW):
        st.code(st.session_state[_PREVIEW][:6000], language=None)


# --------------------------------------------------------------------- chat
def _reply_caption(message: dict) -> str:
    bits = [message.get("model", "")]
    if message.get("cost"):
        bits.append(f"${message['cost']:.4f}")
    looked = [t["args"].get("tag_id") or t["args"].get("title_contains") or t["name"] for t in message.get("tools") or []]
    if looked:
        bits.append("looked at: " + ", ".join(str(x) for x in looked[:6]))
    return " · ".join(b for b in bits if b)


def _chat_panel(chat: dict, df: pd.DataFrame) -> None:
    head_col, cost_col = st.columns([4, 1], vertical_alignment="bottom")
    head_col.subheader(chat.get("title") or assistant.NEW_CHAT_TITLE, anchor=False)
    if chat.get("cost"):
        cost_col.caption(f"This chat so far: ${chat['cost']:.4f}")

    if not str(config.app.get("openrouter_api_key", "") or "").strip() and anim_llm.provider_id() == "openrouter":
        key = st.text_input("OpenRouter API key", type="password", help="Shared with the Animation studio ([app] openrouter_api_key).", key="assistant_or_key")
        if key.strip():
            config.app["openrouter_api_key"] = key.strip()
            config.save_config()
            st.rerun(scope="fragment")
        st.info("Add your OpenRouter key to start chatting (https://openrouter.ai/settings/keys).", icon="🔑")

    _model_picker(chat)

    all_tags = tags.all_tags(df)
    names = {t["id"]: ("🏷 " if not t["builtin"] else "") + t["name"] for t in all_tags}
    refs_col, range_col = st.columns([4, 1])
    current_refs = [r for r in chat.get("refs") or [] if r in names]
    refs = refs_col.multiselect(
        "📎 Data the assistant can see", list(names), default=current_refs, format_func=names.get,
        key=f"assistant_refs::{chat['id']}::{','.join(current_refs)}",
        placeholder="Pick metric tags to attach (it can also look things up itself)",
    )
    data_range = range_col.selectbox(
        "Videos published", list(assistant.RANGES), index=list(assistant.RANGES).index(chat.get("range", assistant.DEFAULT_RANGE)),
        key=f"assistant_range::{chat['id']}",
    )
    if refs != current_refs or data_range != chat.get("range"):
        chat["refs"], chat["range"] = refs, data_range
        _persist(chat)
    if refs:
        size = len(assistant.context_text(refs, assistant.scope(df, data_range)))
        st.caption(f"{len(refs)} tag(s) attached · about {size // 4:,} tokens sent with each question")

    with st.expander("🏷 Metric tags: see and create your own"):
        _tag_manager(df)

    messages = st.container(height=520)
    with messages:
        if not chat.get("messages"):
            st.caption("Ask anything about your channel's numbers, or start with one of these:")
            starter_cols = st.columns(2)
            for n, (question, starter_refs) in enumerate(assistant.STARTERS):
                if starter_cols[n % 2].button(question, key=f"assistant_starter_{n}", use_container_width=True):
                    chat["refs"] = list(dict.fromkeys([*chat.get("refs", []), *assistant.tag_ids_present(starter_refs, df)]))
                    st.session_state[_PENDING] = question
        for message in chat.get("messages") or []:
            with st.chat_message(message["role"]):
                if message.get("error"):
                    st.error(message["content"])
                else:
                    st.markdown(message["content"])
                if message["role"] == "assistant":
                    st.caption(_reply_caption(message))
                elif message.get("refs"):
                    st.caption("📎 " + ", ".join(names.get(r, r) for r in message["refs"][:6]))

    question = st.chat_input("Ask about your channel…", key=f"assistant_input::{chat['id']}") or st.session_state.pop(_PENDING, None)
    if question:
        with messages:
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                with st.status("Thinking…", expanded=False) as status:
                    try:
                        assistant.ask(chat, question, df, on_step=lambda step: status.update(label=f"🔎 {step}"))
                        status.update(label="Done", state="complete")
                    except assistant.AssistantError as exc:
                        status.update(label="Failed", state="error")
                        st.error(str(exc))
        st.rerun(scope="fragment")


@st.fragment
def render(df: pd.DataFrame) -> None:
    chat = _current_chat()
    history_col, chat_col = st.columns([1, 3], gap="medium")
    with history_col:
        _history_panel(chat)
    with chat_col:
        _chat_panel(chat, df)
