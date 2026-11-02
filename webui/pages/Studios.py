"""Studios: where the autonomous studios report to their owner.

Each studio plans, makes and uploads its own videos (app/services/studios).
This page is the owner's side of that: whether the studios are running, each
studio's timeline, its queue (approve or cancel what's waiting), its results
and beliefs, its rules, and a box to leave it notes.
"""
import os
import sys
import threading
import time
from datetime import datetime, timezone
from datetime import time as time_cls

import pandas as pd
import streamlit as st

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

from app.config import config  # noqa: E402
from app.services import discord_notify, youtube_upload  # noqa: E402
from app.services.animation import store as anim_store  # noqa: E402
from app.services.studios import evaluate, model, notify, planner, runner, store, templates, trial  # noqa: E402

st.set_page_config(page_title="Studios", page_icon="🎛", layout="wide")
st.markdown(
    """
<style>
video[data-testid="stVideo"] { max-height: 300px; width: auto !important; max-width: 100%; border-radius: 10px; background: #000; }
.st-key-timeline p { margin-bottom: 0.15rem; }
.tl-time { opacity: 0.6; font-variant-numeric: tabular-nums; margin-right: 0.5rem; }
</style>
""",
    unsafe_allow_html=True,
)

EVENT_ICONS = {
    "plan": "🗓", "result": "📈", "belief": "💡", "produced": "🎬", "qa_failed": "🚫",
    "uploaded": "⬆️", "vetoed": "✋", "incident": "⚠️", "note": "✉️", "settings": "⚙️",
}
EVENT_LABELS = {
    "plan": "Plans", "result": "Results", "belief": "Beliefs", "produced": "Made", "qa_failed": "QA failures",
    "uploaded": "Uploads", "vetoed": "Cancelled", "incident": "Problems", "note": "Your notes", "settings": "Settings",
}
SLOT_BADGES = {
    model.SLOT_PLANNED: ":gray-badge[Planned]",
    model.SLOT_PRODUCING: ":orange-badge[Being made]",
    model.SLOT_READY: ":blue-badge[Ready · waiting]",
    model.SLOT_UPLOADING: ":orange-badge[Uploading]",
    model.SLOT_UPLOADED: ":green-badge[Uploaded]",
    model.SLOT_CANCELLED: ":gray-badge[Cancelled]",
    model.SLOT_FAILED: ":red-badge[Failed]",
}
ACTIVE = (model.SLOT_PLANNED, model.SLOT_PRODUCING, model.SLOT_READY, model.SLOT_UPLOADING)


# ================================================================== helpers
def _ago(ts: float | None) -> str:
    if not ts:
        return "never"
    seconds = time.time() - ts
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min ago"
    if seconds < 86400 * 2:
        return f"{seconds / 3600:.0f} h ago"
    return f"{seconds / 86400:.0f} days ago"


def _local(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(runner.local_tz())


def _save_setting(key: str, value) -> None:
    config.studios[key] = value
    config.save_config()


def _in_background(target, *args, label: str) -> None:
    threading.Thread(target=target, args=args, daemon=True, name=label).start()


def _week_counts(studio_id: str) -> dict:
    week = model.week_id(runner.local_date(datetime.now(timezone.utc)))
    counts = {status: 0 for status in model.SLOT_STATUSES}
    for slot in store.load_queue(studio_id):
        if slot.get("week") == week and not slot["reserve"]:
            counts[slot["status"]] += 1
    return counts


@st.cache_data(ttl=300, show_spinner="Reading the channel's numbers…")
def _packet(studio_id: str, _stamp: int) -> dict:
    return evaluate.load_packet(studio_id)


# ============================================================= network bar
def render_network_bar() -> None:
    enabled = bool(config.studios.get("enabled", False))
    paused = bool(config.studios.get("paused", False))
    state = notify.load_state()
    last_tick = state.get("last_tick")
    silent = enabled and not paused and (not last_tick or time.time() - last_tick > notify.HEARTBEAT_HOURS * 3600)

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1.2])
        if not enabled:
            c1.markdown("**Status**  \n:gray-badge[Off]")
        elif paused:
            c1.markdown("**Status**  \n:orange-badge[Everything paused]")
        else:
            c1.markdown("**Status**  \n:green-badge[Running]")
        c2.markdown(f"**Last tick**  \n{_ago(last_tick)}" + (" :red-badge[late]" if silent else ""))
        c3.markdown(
            "**YouTube**  \n" + (":green-badge[Connected]" if youtube_upload.youtube_upload_service.is_configured() else ":red-badge[Not set up]")
        )
        c4.markdown("**Discord**  \n" + (":green-badge[Alerts on]" if discord_notify.discord_notify_service.is_configured() else ":gray-badge[No webhook]"))

        t1, t2, t3 = st.columns([1, 1, 1.4])
        new_enabled = t1.toggle("Studios on", value=enabled, help="[studios] enabled. Off: the tick does nothing at all.")
        new_paused = t2.toggle("Pause everything", value=paused, help="[studios] paused. The kill switch: no planning, making or uploading.")
        if new_enabled != enabled:
            _save_setting("enabled", new_enabled)
            st.rerun()
        if new_paused != paused:
            _save_setting("paused", new_paused)
            st.rerun()
        busy = runner.is_running()
        if t3.button(
            "Running a tick…" if busy else "▶ Run a tick now",
            disabled=busy or not enabled,
            help="Runs what is due right now, in this app's process (renders included). The hourly cron does the same.",
        ):
            _in_background(runner.tick, label="studios-tick-manual")
            st.toast("Tick started. Refresh in a minute to see what it did.")
        if silent and last_tick:
            st.warning(
                f"The hourly tick last ran {_ago(last_tick)}. Check the crontab line for POST /api/v1/studios/tick "
                "(docs/studios-pilot-plan.md §10).",
                icon="🛑",
            )
        elif enabled and not last_tick:
            st.info("No tick has run yet. Add the hourly crontab line (docs/studios-pilot-plan.md §10) or run one now.", icon="⏱")


# ============================================================ studio cards
def render_cards(studios: list[dict]) -> None:
    columns = st.columns(min(len(studios), 3) or 1)
    for column, studio in zip(columns * 3, studios):
        counts = _week_counts(studio["id"])
        latest = store.list_events(studio["id"], limit=1)
        with column, st.container(border=True):
            badge = ":orange-badge[Paused]" if studio["paused"] else ":green-badge[Active]"
            if studio.get("shadow"):
                badge += " :violet-badge[Shadow]"
            st.markdown(f"#### {studio['name']} {badge}")
            st.caption(f"{studio['pipeline'].title()} · {studio['cadence']['per_day']} a day · {studio['post_window']['start']}–{studio['post_window']['end']}")
            st.caption("This week")
            m1, m2, m3 = st.columns(3)
            m1.metric("Uploaded", counts[model.SLOT_UPLOADED])
            m2.metric("Waiting", counts[model.SLOT_READY])
            m3.metric("Planned", counts[model.SLOT_PLANNED] + counts[model.SLOT_PRODUCING])
            if latest:
                st.caption(f"{EVENT_ICONS.get(latest[0]['type'], '•')} {_ago(latest[0]['ts'])}: {latest[0]['summary'][:140]}")
            selected = st.session_state.get("studio_id") == studio["id"]
            if st.button("Open" if not selected else "Open ✓", key=f"open_{studio['id']}", use_container_width=True, disabled=selected):
                st.session_state["studio_id"] = studio["id"]
                st.rerun()


# ================================================================= timeline
def render_timeline(studio: dict) -> None:
    with st.form("studio_note", clear_on_submit=True, border=True):
        text = st.text_area(
            "Leave the studio a note",
            placeholder="e.g. Fewer space topics this week, more animals. No videos about sharks until December.",
            help="The agent reads unread notes at its next planning run and answers them here.",
        )
        if st.form_submit_button("Send note") and text.strip():
            store.add_note(studio["id"], text)
            st.toast("Note sent. It's read at the next planning run.")
            st.rerun()
    unread = store.list_notes(studio["id"], unread_only=True)
    if unread:
        st.caption(f"✉️ {len(unread)} note(s) waiting for the next planning run.")

    shown = st.pills(
        "Show", list(EVENT_LABELS), format_func=EVENT_LABELS.get, selection_mode="multi", default=list(EVENT_LABELS), key="tl_types"
    )
    events = store.list_events(studio["id"], limit=300, types=tuple(shown) if shown else None)
    if not events:
        st.info("Nothing has happened yet.")
        return
    with st.container(key="timeline"):
        current_day = None
        for event in events:
            moment = _local(event["ts"])
            day = moment.strftime("%A %d %B")
            if day != current_day:
                st.markdown(f"##### {day}")
                current_day = day
            icon = EVENT_ICONS.get(event["type"], "•")
            st.markdown(f"<span class='tl-time'>{moment.strftime('%H:%M')}</span> {icon} {event['summary']}", unsafe_allow_html=True)
            _event_details(event)


def _event_details(event: dict) -> None:
    data = event.get("data") or {}
    if event["type"] == "plan" and data.get("review"):
        with st.expander("Review, replies and cost"):
            st.markdown(data["review"])
            for reply in data.get("note_replies") or []:
                st.markdown(f"> ✉️ {reply['reply']}")
            st.caption(
                f"Estimated production ${data.get('estimated_cost', 0):.2f} · planning ${data.get('planner_cost', 0):.3f} "
                f"on {data.get('planner_model', '?')} · {data.get('submissions', 1)} submission(s)"
            )
    elif event["type"] == "qa_failed" and data.get("checks"):
        with st.expander("Checks"):
            st.dataframe(
                pd.DataFrame([{"Check": c["name"], "OK": "✅" if c["ok"] else "❌", "Detail": c["detail"]} for c in data["checks"]]),
                hide_index=True, use_container_width=True,
            )
    elif event["type"] == "incident" and data.get("problems"):
        with st.expander("Details"):
            for problem in data["problems"]:
                st.markdown(f"- {problem}")
    elif event["type"] == "uploaded" and data.get("url"):
        st.caption(f"[{data['url']}]({data['url']}) · [YouTube Studio](https://studio.youtube.com/video/{data.get('video_id', '')}/edit)")


# ==================================================================== queue
def render_queue(studio: dict) -> None:
    queue = store.load_queue(studio["id"])
    upcoming = sorted((s for s in queue if s["status"] in ACTIVE and not s["reserve"]), key=runner.slot_utc)
    if not upcoming:
        st.info("Nothing booked. The studio plans on Sundays (and on its first tick), or press Plan now.")
    current_day = None
    for slot in upcoming:
        if slot["date"] != current_day:
            current_day = slot["date"]
            st.markdown(f"##### {datetime.fromisoformat(slot['date']).strftime('%A %d %B')}")
        _slot_card(studio, slot)

    to_rate = sorted(
        (s for s in queue if s["status"] == model.SLOT_UPLOADED and not s["owner_review"] and time.time() - s["uploaded_at"] < 14 * 86400),
        key=runner.slot_utc,
    )
    if to_rate:
        st.markdown("##### Rate finished videos")
        st.caption("Your 👍 / 👎 is how the trial measures whether QA lets through anything you'd have stopped. A 👎 also goes to the studio as a note.")
        for slot in to_rate:
            with st.container(border=True):
                left, right = st.columns([3, 1.2])
                shadow = " :violet-badge[Shadow · private]" if slot["shadow"] else ""
                left.markdown(f"**{slot['date']} {slot['time']}** · {slot['brief']['topic']}{shadow}")
                left.caption(f"[Watch on YouTube](https://youtu.be/{slot['youtube_video_id']})")
                with right:
                    _review_controls(studio, slot)

    reserves = [s for s in queue if s["reserve"] and s["status"] == model.SLOT_PLANNED]
    with st.expander(f"Reserve topics ({len(reserves)})", expanded=False):
        st.caption("Used when a video fails its checks: the reserve takes the failed video's slot.")
        for slot in reserves:
            st.markdown(f"- {slot['brief']['topic']}")

    done = sorted((s for s in queue if s["status"] == model.SLOT_UPLOADED), key=runner.slot_utc, reverse=True)[:30]
    with st.expander(f"Uploaded ({len(done)} most recent)"):
        if done:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Slot": f"{s['date']} {s['time']}",
                            "Topic": s["brief"]["topic"],
                            "Video": f"https://youtu.be/{s['youtube_video_id']}",
                            "Predicted": s["prediction"],
                            "3-day views": (s["checkins"].get("3d") or {}).get("views"),
                            "vs baseline": (s["checkins"].get("3d") or {}).get("vs_baseline_pct"),
                            "7-day views": (s["checkins"].get("7d") or {}).get("views"),
                        }
                        for s in done
                    ]
                ),
                hide_index=True,
                use_container_width=True,
                column_config={"Video": st.column_config.LinkColumn(display_text="watch"), "vs baseline": st.column_config.NumberColumn(format="%+d%%")},
            )
    dropped = sorted((s for s in queue if s["status"] in (model.SLOT_FAILED, model.SLOT_CANCELLED)), key=lambda s: s["updated_at"], reverse=True)[:30]
    with st.expander(f"Dropped ({len(dropped)} most recent)"):
        for slot in dropped:
            st.markdown(f"{SLOT_BADGES[slot['status']]} {slot['date'] or 'reserve'} {slot['time']} · **{slot['brief']['topic']}**  \n{slot['error'] or ''}")


def _slot_card(studio: dict, slot: dict) -> None:
    brief = slot["brief"]
    with st.container(border=True):
        left, right = st.columns([3, 1.2])
        with left:
            st.markdown(f"**{slot['time']}** · {brief['topic']} {SLOT_BADGES[slot['status']]}")
            levers = " · ".join(f"{k.replace('_', ' ')}: {brief[k]}" for k in studio["levers"] if k in brief)
            tags = []
            if slot["experiment"]:
                tags.append(f"🧪 {slot['experiment']}")
            tags.append("exploring" if slot["arm"] == "explore" else "on defaults")
            if slot["prediction"]:
                tags.append(f"predicts {slot['prediction']} baseline")
            st.caption(" · ".join(tags) + f"  \n{levers}")
            if slot["why"]:
                st.caption(f"Why: {slot['why']}")
            if slot["error"]:
                st.caption(f"Last problem: {slot['error'][:200]}")
            if slot["status"] == model.SLOT_READY:
                deadline = runner.upload_after(studio, slot).astimezone(runner.local_tz())
                note = "approved: uploads" if slot["veto_waived"] else "uploads"
                st.markdown(f"⏳ {note} **{deadline.strftime('%a %d %b %H:%M')}** unless you cancel it.")
        with right:
            final = anim_store.final_path(slot["project_id"]) if slot.get("project_id") else ""
            if slot["status"] == model.SLOT_READY and final and os.path.isfile(final):
                st.video(final)
            if slot["status"] == model.SLOT_READY and not slot["veto_waived"]:
                if st.button("✓ Approve now", key=f"approve_{slot['id']}", use_container_width=True, help="Skip the rest of the cancel window."):
                    store.update_slot(studio["id"], slot["id"], veto_waived=True)
                    st.rerun()
            if slot["status"] in (model.SLOT_PLANNED, model.SLOT_READY):
                if st.button("✕ Cancel", key=f"cancel_{slot['id']}", use_container_width=True, help="This video won't be made or uploaded."):
                    store.update_slot(studio["id"], slot["id"], status=model.SLOT_CANCELLED, error="cancelled by the owner")
                    store.append_event(studio["id"], "vetoed", f"You cancelled \"{brief['topic']}\" ({slot['date']} {slot['time']}).", {"slot_id": slot["id"]})
                    st.rerun()
            if slot["status"] == model.SLOT_READY:
                _review_controls(studio, slot)


def _review_controls(studio: dict, slot: dict) -> None:
    review = slot.get("owner_review") or {}
    if review:
        mark = "👍" if review.get("verdict") == "good" else "👎"
        st.caption(f"You rated it {mark} {review.get('note', '')}")
        return
    good, bad = st.columns(2)
    if good.button("👍", key=f"good_{slot['id']}", use_container_width=True, help="You'd publish this."):
        store.review_slot(studio["id"], slot["id"], "good")
        st.rerun()
    with bad.popover("👎"):
        note = st.text_input("What's wrong with it?", key=f"bad_note_{slot['id']}")
        if st.button("Save 👎", key=f"bad_{slot['id']}", disabled=not note.strip()):
            store.review_slot(studio["id"], slot["id"], "bad", note)
            st.rerun()


# ================================================================== results
def render_results(studio: dict) -> None:
    stamp = st.session_state.setdefault("packet_stamp", 0)
    if st.button("↻ Refresh numbers"):
        st.session_state["packet_stamp"] = stamp + 1
        st.rerun()
    try:
        packet = _packet(studio["id"], stamp)
    except Exception as exc:
        st.error(f"Couldn't read the results: {exc}")
        return
    _render_trial_report(studio)
    baseline = packet["baseline"]
    m1, m2, m3, m4 = st.columns(4)
    if packet["calibrating"]:
        m1.metric("Calibrating", f"{baseline['videos']}/{baseline['needed']}", help="No baseline yet: public videos with 3-day views so far, of the number needed before videos are scored.")
    else:
        m1.metric("Baseline (3-day views)", f"{baseline['views_3d']:,.0f}", help=baseline["explained"])
    hits = packet["predictions"]
    m2.metric("Predictions right", f"{hits['hit_rate']:.0%}" if hits["hit_rate"] is not None else "—", help=f"{hits['hits']} of {hits['scored']} scored")
    m3.metric("Spent this week", f"${packet['spend']['this_week']:.2f}", help=f"of ${packet['spend']['weekly_budget']:g}")
    m4.metric("Uploaded", packet["uploads"]["total"])

    st.markdown("##### Experiments")
    if not packet["experiments"]:
        st.caption("No experiments yet.")
    for experiment in packet["experiments"]:
        verdict = experiment["verdict"]
        badge = {"winner": ":green-badge[Winner]", "no_difference": ":gray-badge[No difference]", "pending": ":blue-badge[Waiting]", "too_few": ":orange-badge[Too few]"}.get(verdict["status"], "")
        with st.container(border=True):
            st.markdown(f"**{experiment['id']}** · {experiment['lever']} · {experiment['week']} {badge}")
            if experiment["hypothesis"]:
                st.caption(experiment["hypothesis"])
            st.markdown(verdict["summary"])
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Value": str(a["value"]), "Videos": a["videos"], "Scored": a["scored"], "vs baseline": a["median_vs_baseline_pct"], "% viewed": a["median_avg_view_pct"]}
                        for a in experiment["arms"]
                    ]
                ),
                hide_index=True,
                use_container_width=True,
                column_config={"vs baseline": st.column_config.NumberColumn(format="%+d%%"), "% viewed": st.column_config.NumberColumn(format="%.0f%%")},
            )

    st.markdown("##### Videos")
    if packet["videos"]:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Date": v["date"], "Title": v["title"] or v["topic"], "Experiment": v["experiment"], "Arm": v["arm"],
                        "3-day views": v["views_3d"], "vs baseline": v["vs_baseline_pct"], "Predicted": v["prediction"],
                        "Right?": {True: "✅", False: "❌"}.get(v["prediction_hit"], ""), "State": v["state"],
                    }
                    for v in reversed(packet["videos"])
                ]
            ),
            hide_index=True,
            use_container_width=True,
            column_config={"vs baseline": st.column_config.NumberColumn(format="%+d%%")},
        )
    else:
        st.caption("No uploads yet.")


STATUS_MARKS = {"pass": "✅ pass", "fail": "❌ fail", "not yet": "⏳ not yet", "info": "ℹ️ info"}


def _render_trial_report(studio: dict) -> None:
    try:
        result = trial.report(studio["id"])
    except Exception as exc:
        st.error(f"Couldn't build the trial report: {exc}")
        return
    shadow = result["shadow"]
    title = f"Trial report · live since {result['start']}" if result["live"] else "Trial report · shadow days (nothing published yet)"
    with st.expander(title, expanded=True):
        st.caption("The go/no-go and pass criteria from docs/studios-trial-run.md, counted from the queue and the timeline.")
        st.markdown(
            f"**Shadow:** {shadow['uploaded_unattended']} of {shadow['slots_due']} due videos made and uploaded with no help · "
            f"{shadow['failed']} failed · rated 👍 {shadow['rated_good']} / 👎 {shadow['rated_bad']} / unrated {shadow['unrated']} · "
            f"cost per video {('$' + format(shadow['cost_per_video'], '.2f')) if shadow['cost_per_video'] is not None else '—'}"
        )
        if result["areas"]:
            st.dataframe(
                pd.DataFrame([{"Area": a["area"], "Result": STATUS_MARKS.get(a["status"], a["status"]), "Value": a["value"], "Detail": a["detail"]} for a in result["areas"]]),
                hide_index=True, use_container_width=True,
            )
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Week": w["week"], "Published": w["videos"], "Spend": w["spend"], "Budget": w["budget"], "Median 3-day views": w["median_views_3d"]}
                        for w in result["weeks"]
                    ]
                ),
                hide_index=True, use_container_width=True,
                column_config={"Spend": st.column_config.NumberColumn(format="$%.2f"), "Budget": st.column_config.NumberColumn(format="$%.0f")},
            )


# ================================================================= playbook
def render_playbook(studio: dict) -> None:
    playbook = store.load_playbook(studio["id"])
    defaults = planner.effective_defaults(studio, playbook)
    st.markdown("##### Defaults")
    st.caption("What every video uses unless it is in an experiment. The agent changes these only with an adopted belief.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Lever": name, "Now": str(defaults[name]), "Template default": str(spec["default"]),
                    "Changed": "✳️" if str(defaults[name]) != str(spec["default"]) else "",
                    "Allowed": ", ".join(map(str, spec["values"])),
                }
                for name, spec in studio["levers"].items()
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    st.markdown("##### Beliefs")
    beliefs = playbook.get("beliefs") or []
    if not beliefs:
        st.caption(f"None yet. A belief is adopted only with {model.ADOPT_MIN_VIDEOS_PER_ARM}+ videos per value across {model.ADOPT_MIN_WEEKS}+ weeks.")
    for status, badge in (("adopted", ":green-badge[Adopted]"), ("testing", ":blue-badge[Testing]"), ("rejected", ":gray-badge[Rejected]")):
        for belief in (b for b in beliefs if b.get("status") == status):
            with st.container(border=True):
                st.markdown(f"{badge} **{belief.get('claim', '')}**")
                details = [f"lever {belief['lever']}"] if belief.get("lever") else []
                if belief.get("evidence"):
                    details.append(f"evidence {', '.join(belief['evidence'])}")
                if belief.get("videos_per_arm"):
                    details.append(f"videos per value {belief['videos_per_arm']}")
                if belief.get("weeks"):
                    details.append(f"weeks {', '.join(belief['weeks'])}")
                if belief.get("effect"):
                    details.append(str(belief["effect"]))
                st.caption(" · ".join(details))


# ================================================================= settings
def render_settings(studio: dict) -> None:
    with st.form("studio_settings"):
        name = st.text_input("Name", studio["name"])
        identity = st.text_area("What the studio makes", studio["identity"], height=110, help="The topic territory the agent plans within.")
        rules = st.text_area("Hard rules (one per line)", "\n".join(studio["hard_rules"]), height=150, help="The agent must never break these; the QA critic checks every script against them.")
        c1, c2, c3 = st.columns(3)
        per_day = c1.number_input("Videos a day", 1, 10, studio["cadence"]["per_day"])
        start = c2.time_input("Post from", time_cls.fromisoformat(studio["post_window"]["start"]), step=900)
        end = c3.time_input("Post until", time_cls.fromisoformat(studio["post_window"]["end"]), step=900)
        c4, c5, c6 = st.columns(3)
        veto = c4.number_input("Cancel window (hours)", 0.0, 72.0, float(studio["veto_hours"]), step=1.0, help="How long a finished video waits for you before it may upload.")
        budget = c5.number_input("Weekly budget ($)", 0.5, 500.0, float(studio["weekly_budget_usd"]), step=1.0)
        options = studio.get("pipeline_options") or {}
        aspect = c6.selectbox("Aspect", ["9:16", "16:9"], index=0 if options.get("aspect", "9:16") == "9:16" else 1)
        planner_model = st.text_input(
            "Planner model (OpenRouter ID)",
            studio.get("planner_model", ""),
            placeholder=f"empty = {planner.planner_model({**studio, 'planner_model': ''})}",
            help="Plans the week and runs the QA critic. It runs about once a week, so a strong model is cheap.",
        )
        voice = st.text_input("Voice", options.get("voice", ""), placeholder="empty = the Animation page's voice")
        if st.form_submit_button("Save", type="primary"):
            try:
                store.update_studio(
                    studio["id"],
                    name=name,
                    identity=identity,
                    hard_rules=[r.strip() for r in rules.splitlines() if r.strip()],
                    cadence={"per_day": int(per_day)},
                    post_window={"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")},
                    veto_hours=float(veto),
                    weekly_budget_usd=float(budget),
                    planner_model=planner_model,
                    pipeline_options={**options, "aspect": aspect, "voice": voice},
                )
                st.toast("Saved.")
                st.rerun()
            except model.StudioError as exc:
                for problem in exc.problems:
                    st.error(problem)
    st.markdown("##### Levers")
    st.caption("The choices the agent makes per video. They're fixed by the studio's template.")
    for name, spec in studio["levers"].items():
        st.markdown(f"- **{name}**: {', '.join(map(str, spec['values']))}")


# ===================================================================== page
st.page_link("Main.py", label="Back to generator", icon=":material/arrow_back:")
st.title("🎛 Studios")
st.caption("Each studio plans, makes and uploads its own videos. You watch, cancel what you don't want, and leave notes.")

render_network_bar()

studios = store.list_studios()
if not studios:
    st.info("No studio yet. The first one makes paper-animation explainers; it starts paused so you can check its rules.")
    if st.button("Create the Paper Explainers studio", type="primary"):
        templates.ensure_studio("animation")
        st.rerun()
    st.stop()

if st.session_state.get("studio_id") not in {s["id"] for s in studios}:
    st.session_state["studio_id"] = studios[0]["id"]
render_cards(studios)
studio = next(s for s in studios if s["id"] == st.session_state["studio_id"])

st.divider()
head, actions = st.columns([3, 1.4])
with head:
    st.subheader(studio["name"])
    st.caption(studio["identity"])
with actions:
    paused = st.toggle("Paused", value=studio["paused"], key=f"paused_{studio['id']}", help="A paused studio plans, makes and uploads nothing.")
    if paused != studio["paused"]:
        store.set_paused(studio["id"], paused)
        st.rerun()
    shadow = st.toggle(
        "Shadow", value=bool(studio.get("shadow")), key=f"shadow_{studio['id']}",
        help="Shadow: everything runs, but uploads stay private and never publish, and they don't count as results. Switch off to go live.",
    )
    if shadow != bool(studio.get("shadow")):
        store.update_studio(studio["id"], shadow=shadow)
        st.rerun()
    if st.button("🗓 Plan now", use_container_width=True, help="Plan from tomorrow to the end of that week (only days with free slots)."):
        _in_background(planner.run, studio["id"], label="studio-plan-manual")
        st.toast("Planning started. It takes a minute or two; the plan appears on the timeline.")

section = st.segmented_control(
    "Section", ["Timeline", "Queue", "Results", "Playbook", "Settings"], default="Timeline", key="studio_section", label_visibility="collapsed"
)
{"Timeline": render_timeline, "Queue": render_queue, "Results": render_results, "Playbook": render_playbook, "Settings": render_settings}.get(
    section or "Timeline", render_timeline
)(studio)
