"""Channel analytics: how each studio's videos do once they are on YouTube.

Overview   - headline numbers, studio vs studio, the clearest findings
What works - every style knob of a studio (topic category, setting,
             characters, length, voice, publish time…) ranked by a metric
Batches    - each generation batch and its best / weakest video; batch vs single
Videos     - every video with its numbers; edit topic categories
Reconcile  - which channel video is which app video: hand-posted uploads
             found by title, near-miss titles to confirm, leftovers to link
Assistant  - a chat (OpenRouter) about the numbers, with attachable metric
             tags, a model picker and saved history
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

from app.services.analytics import catalog, reconcile, report, store, sync, topics, youtube_api  # noqa: E402
from webui import analytics_assistant_ui  # noqa: E402

st.set_page_config(page_title="Channel Analytics", page_icon="📈", layout="wide")
st.page_link("Main.py", label="Back to generator", icon=":material/arrow_back:")
st.title("📈 Channel Analytics")
st.caption(
    "What each studio's videos did on YouTube: which topics, styles and batches work, "
    "and which don't. Videos you post by hand are matched to the app by their title."
)

_DARK = getattr(getattr(st.context, "theme", None), "type", "light") == "dark"
# Validated categorical slots 1-3 (blue, orange, aqua), one per studio, the
# same on every chart; videos from outside the app are neutral gray.
STUDIO_COLORS = (
    {"shorts": "#3987e5", "documentary": "#d95926", "animation": "#199e70", "other": "#8a8983"}
    if _DARK
    else {"shorts": "#2a78d6", "documentary": "#eb6834", "animation": "#1baf7a", "other": "#a3a29b"}
)
BAR_COLOR = STUDIO_COLORS["shorts"]
TEXT_SECONDARY = "#c3c2b7" if _DARK else "#52514e"
STUDIO_ORDER = [report.STUDIO_LABELS[s] for s in ("shorts", "documentary", "animation", "other")]
STUDIO_SCALE = alt.Scale(domain=STUDIO_ORDER, range=[STUDIO_COLORS[s] for s in ("shorts", "documentary", "animation", "other")])
METHOD_LABELS = {
    "app upload": "Uploaded by the app",
    "posted link": "Marked posted (with link)",
    "title": "Matched by title",
    "manual": "Linked by you",
}
MIN_GROUP = 3  # groups with fewer videos are shown faded: too few to trust


# ----------------------------------------------------------------- data access
@st.cache_data(ttl=120, show_spinner="Reading your studios…")
def _load():
    items = catalog.build_items()
    videos = store.channel_videos()
    decisions = store.load_links()
    df = report.build_dataset(items, videos, decisions=decisions)
    result = reconcile.reconcile(items, videos, decisions)
    return df, items, videos, result


def _refresh():
    _load.clear()
    st.rerun()


def _ago(ts) -> str:
    if not ts:
        return "never"
    minutes = (datetime.now().timestamp() - float(ts)) / 60
    if minutes < 2:
        return "just now"
    if minutes < 90:
        return f"{minutes:.0f} min ago"
    if minutes < 48 * 60:
        return f"{minutes / 60:.0f} h ago"
    return datetime.fromtimestamp(float(ts)).strftime("%b %d, %Y")


# ------------------------------------------------------------------ status bar
ready, reason = youtube_api.readiness()
last = store.load_sync_status()
status_col, button_col = st.columns([4, 1], vertical_alignment="center")
with status_col:
    if not ready:
        st.warning(reason, icon="🔑")
    elif last.get("error"):
        st.error(f"Last sync failed ({_ago(last.get('finished_at'))}): {last['error']}", icon="⚠️")
    else:
        channel = store.load_channel_info()
        bits = [f"Last synced {_ago(last.get('finished_at'))}"]
        if channel.get("title"):
            bits.insert(0, f"**{channel['title']}**")
        if last.get("metrics_error"):
            bits.append(f"⚠️ watch-time metrics failed: {last['metrics_error'][:120]}")
        st.caption(" · ".join(bits) + ". The daily cron run also syncs before it uploads.")
with button_col:
    if st.button("🔄 Sync now", type="primary", disabled=not ready, use_container_width=True):
        with st.spinner("Fetching your channel, matching videos and pulling metrics…"):
            outcome = sync.run()
        if outcome.get("ok"):
            st.toast(
                f"{outcome.get('videos', 0)} videos · {outcome.get('linked', 0)} matched · "
                f"{outcome.get('marked_posted', 0)} newly marked posted",
                icon="✅",
            )
            _refresh()
        else:
            st.error(outcome.get("error") or "Sync failed.")

if not ready:
    with st.expander("How to turn analytics on (about 2 minutes)", expanded=not store.channel_videos()):
        st.markdown(
            "1. In [Google Cloud Console](https://console.cloud.google.com) → **APIs & Services → Library**, "
            "enable **YouTube Analytics API** (the Data API is already on for uploads).\n"
            "2. On your computer run `.venv/bin/python youtube_auth.py` again and tick every permission: "
            "it now also asks to *view* your channel and its analytics.\n"
            "3. On a VPS, copy the new `storage/youtube/token.json` to the server.\n\n"
            "Uploads keep working the whole time. Full guide: `docs/setup-5-youtube-analytics.md`."
        )

df_all, items, videos, result = _load()
if not videos:
    st.info("No channel data yet. Press **Sync now** once analytics is connected.")
    st.stop()

# --------------------------------------------------------------------- filters
f1, f2, f3 = st.columns([2, 3, 2], vertical_alignment="bottom")
period = f1.segmented_control("Published", ["30 days", "90 days", "1 year", "All time"], default="90 days", key="an_period")
studio_options = [s for s in ("shorts", "documentary", "animation", "other") if (df_all["studio"] == s).any()]
studios = f2.multiselect(
    "Studios",
    studio_options,
    default=[s for s in studio_options if s != "other"] or studio_options,
    format_func=lambda s: report.STUDIO_LABELS.get(s, s),
    key="an_studios",
)
min_age = f3.number_input(
    "Hide videos younger than (days)", 0, 30, 3, key="an_min_age",
    help="Brand-new videos haven't had time to collect views, and watch time / % viewed only "
    "arrive once YouTube has settled a day's numbers (about 3 days).",
)

df = df_all[df_all["live"] & df_all["studio"].isin(studios) & (df_all["age_days"] >= min_age)]
days = {"30 days": 30, "90 days": 90, "1 year": 365}.get(period or "All time")
if days:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    df = df[df["published_at"] >= cutoff]

to_review = len(result["suggestions"]) + len(result["missing_posted"]) + len(result["duplicates"])
tabs = st.tabs(["Overview", "What works", "Batches", "Videos", f"Reconcile{f' ({to_review})' if to_review else ''}", "💬 Assistant"])


# --------------------------------------------------------------------- helpers
def _fmt(value, kind="int") -> str:
    if value is None or pd.isna(value):
        return "–"
    if kind == "pct":
        return f"{value:.1f}%"
    if kind == "float":
        return f"{value:,.1f}"
    return f"{value:,.0f}"


def _group_chart(summary: pd.DataFrame, dim: str, metric_col: str, title: str, color_by_studio: bool = False):
    """Horizontal bars, best first; faded when a group has too few videos."""
    data = summary.dropna(subset=[metric_col]).copy()
    if data.empty:
        st.caption(f"{title}: no data yet.")
        return
    data[dim] = data[dim].astype(str)
    data["Enough videos"] = data["Videos"] >= MIN_GROUP
    data["count_label"] = data["Videos"].map(lambda n: f"{n} video" + ("" if n == 1 else "s"))
    order = data.sort_values(metric_col, ascending=False)[dim].tolist()
    color = (
        alt.Color(f"{dim}:N", scale=STUDIO_SCALE, legend=None)
        if color_by_studio
        else alt.value(BAR_COLOR)
    )
    # A title inside a layered chart collapses its plot in Streamlit, so the
    # title is plain text above it.
    st.markdown(f"**{title}**")
    base = alt.Chart(data)
    bars = base.mark_bar(cornerRadiusEnd=4).encode(
        y=alt.Y(f"{dim}:N", sort=order, title=None, axis=alt.Axis(labelLimit=220)),
        # headroom on the right for the "n videos" label
        x=alt.X(f"{metric_col}:Q", title=metric_col, axis=alt.Axis(grid=True, tickCount=4), scale=alt.Scale(domain=[0, float(data[metric_col].max() or 1) * 1.22])),
        color=color,
        opacity=alt.condition("datum['Enough videos']", alt.value(1.0), alt.value(0.35)),
        tooltip=[
            alt.Tooltip(f"{dim}:N", title=report.DIMENSION_LABELS.get(dim, dim)),
            alt.Tooltip(f"{metric_col}:Q", format=",.1f"),
            alt.Tooltip("Videos:Q"),
            alt.Tooltip("Total views:Q", format=","),
            alt.Tooltip("Avg % viewed:Q", format=".1f"),
        ],
    )
    labels = base.mark_text(align="left", dx=4, fontSize=11, color=TEXT_SECONDARY).encode(
        y=alt.Y(f"{dim}:N", sort=order),
        x=alt.X(f"{metric_col}:Q"),
        text="count_label:N",
    )
    st.altair_chart(bars + labels, width="stretch", height=34 * len(data) + 56)


METRIC_TO_SUMMARY = {
    "views": "Median views",
    "views_per_day": "Median views/day",
    "views_7d": "Median views at 7 days",
    "avg_view_pct": "Avg % viewed",
    "engagement_per_1k": "Engagement /1k",
    "subs_gained": "Subs gained",
    "watch_minutes": "Watch hours",
}


def _insight_lines(found: list[dict], metric: str = "views"):
    if not found:
        st.caption(
            f"No clear winners yet. A finding needs at least {MIN_GROUP} videos per group and a gap of "
            "25% or more from the typical video; it shows up here as more videos are posted."
        )
        return
    kind = {"avg_view_pct": "pct", "views_per_day": "float", "engagement_per_1k": "float", "subs_gained": "float"}.get(metric, "int")
    for f in found:
        times = f["ratio"] if f["positive"] else 1 / max(f["ratio"], 0.01)
        direction = "more" if f["positive"] else "less"
        icon = "▲" if f["positive"] else "▼"
        st.markdown(
            f"{icon} **{f['dimension_label']}: {f['group']}**: {f['metric_label'].lower()} "
            f"{_fmt(f['value'], kind)}, about **{times:.1f}× {direction}** than typical "
            f"({f['videos']} videos)"
        )


# ==================================================================== overview
with tabs[0]:
    if df.empty:
        st.info("No published videos match these filters.")
    else:
        k = st.columns(6)
        k[0].metric("Videos", _fmt(len(df)))
        k[1].metric("Views", _fmt(df["views"].sum()))
        k[2].metric("Median views / video", _fmt(df["views"].median()))
        k[3].metric("Avg % viewed", _fmt(df["avg_view_pct"].mean(), "pct"))
        k[4].metric("Watch hours", _fmt(df["watch_minutes"].sum() / 60, "float"))
        k[5].metric("Subscribers gained", _fmt(df["subs_gained"].sum()))

        st.subheader("Studio vs studio", anchor=False)
        by_studio = report.summarize(df, "studio_label")
        c1, c2 = st.columns(2)
        with c1:
            _group_chart(by_studio, "studio_label", "Median views", "Median views per video", color_by_studio=True)
        with c2:
            _group_chart(by_studio, "studio_label", "Avg % viewed", "Average % of the video watched", color_by_studio=True)
        st.dataframe(by_studio.rename(columns={"studio_label": "Studio"}), hide_index=True, use_container_width=True)

        st.subheader("Views by publish week", anchor=False)
        weekly = df.dropna(subset=["published_at"]).copy()
        weekly["Week"] = weekly["published_at"].dt.tz_convert(None).dt.to_period("W").dt.start_time
        weekly = weekly.groupby(["Week", "studio_label"], as_index=False).agg(Views=("views", "sum"), Videos=("video_id", "count"))
        st.altair_chart(
            alt.Chart(weekly)
            .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2, stroke="transparent")
            .encode(
                x=alt.X("yearmonthdate(Week):T", title="Week published"),
                y=alt.Y("sum(Views):Q", title="Views so far", stack="zero"),
                color=alt.Color("studio_label:N", scale=STUDIO_SCALE, title="Studio", legend=alt.Legend(orient="top")),
                tooltip=[alt.Tooltip("yearmonthdate(Week):T", title="Week of"), alt.Tooltip("studio_label:N", title="Studio"), "Videos:Q", alt.Tooltip("Views:Q", format=",")],
            ),
            width="stretch",
            height=260,
        )
        st.caption("Each bar is the views those weeks' uploads have collected so far, so older weeks have had longer to grow.")

        st.subheader("Clearest findings", anchor=False)
        dims = [d for d in report.feature_dimensions(df) if d in report.COMMON_DIMENSIONS or d == "studio_label"]
        _insight_lines(report.insights(df, dims, metric="views", min_videos=MIN_GROUP))
        st.caption("Per-studio style findings (settings, characters, voices…) are on the **What works** tab.")


# ================================================================== what works
with tabs[1]:
    app_studios = [s for s in studios if s != "other"]
    if df.empty or not app_studios:
        st.info("No published app videos match these filters.")
    else:
        w1, w2 = st.columns([3, 2])
        studio = w1.segmented_control(
            "Studio", app_studios, default=app_studios[0], format_func=lambda s: report.STUDIO_LABELS[s], key="ww_studio"
        ) or app_studios[0]
        metric = w2.selectbox(
            "Rank groups by", list(report.METRICS), format_func=lambda m: report.METRICS[m][0], key="ww_metric",
            help="Views reward older videos; views per day and % viewed compare old and new fairly.",
        )
        sdf = df[df["studio"] == studio]
        st.caption(f"{len(sdf)} published {report.STUDIO_LABELS[studio].lower()} in this period. Faded bars have fewer than {MIN_GROUP} videos: too few to trust yet.")

        dims = report.feature_dimensions(df_all, studio)
        st.markdown("**What stands out**")
        _insight_lines(report.insights(sdf, dims, metric=metric, min_videos=MIN_GROUP), metric)

        summary_col = METRIC_TO_SUMMARY[metric]
        grid = st.columns(2)
        shown = 0
        for dim in dims:
            summary = report.summarize(sdf, dim)
            if len(summary) < 2:
                continue  # one group compares with nothing
            with grid[shown % 2]:
                _group_chart(summary, dim, summary_col, report.DIMENSION_LABELS.get(dim, dim))
            shown += 1
        if not shown:
            st.caption("Every video in this period shares the same settings, so there is nothing to compare yet.")

        with st.expander("Topics, best first"):
            topic_table = (
                sdf.groupby(["category", "topic"], as_index=False)
                .agg(Videos=("video_id", "count"), Views=("views", "sum"), **{"Median views": ("views", "median"), "Avg % viewed": ("avg_view_pct", "mean")})
                .sort_values("Median views", ascending=False)
            )
            st.dataframe(
                topic_table.rename(columns={"category": "Category", "topic": "Topic"}),
                hide_index=True,
                use_container_width=True,
                column_config={"Avg % viewed": st.column_config.NumberColumn(format="%.1f%%")},
            )


# ===================================================================== batches
with tabs[2]:
    app_df = df[df["studio"] != "other"]
    if app_df.empty:
        st.info("No published app videos match these filters.")
    else:
        st.subheader("Batch or single?", anchor=False)
        split = app_df.groupby(["studio_label", "generation"], as_index=False).agg(
            Videos=("video_id", "count"), **{"Median views": ("views", "median"), "Avg % viewed": ("avg_view_pct", "mean")}
        )
        st.dataframe(
            split.rename(columns={"studio_label": "Studio", "generation": "Made as"}),
            hide_index=True,
            use_container_width=True,
            column_config={"Avg % viewed": st.column_config.NumberColumn(format="%.1f%%"), "Median views": st.column_config.NumberColumn(format="%d")},
        )

        st.subheader("Every batch", anchor=False)
        batches = report.batch_summary(app_df)
        if batches.empty:
            st.caption("No batches among these videos yet.")
        else:
            st.caption(
                "A batch is a set of videos generated together: a pasted list on a calendar, the Animation "
                "studio's Batch mode, or several variants of one Shorts topic. \"Guessed\" batches were made "
                "before batches were recorded and are grouped by creation time."
            )
            st.dataframe(
                batches.drop(columns=["batch_id", "studio"]),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Made": st.column_config.DatetimeColumn(format="MMM D, YYYY"),
                    "Median views": st.column_config.NumberColumn(format="%d"),
                    "Avg % viewed": st.column_config.NumberColumn(format="%.1f%%"),
                    "Posted": st.column_config.NumberColumn(help="Videos of the batch on the channel (within the filters)"),
                },
            )
            labels = {f"{r['studio']}|{r['batch_id']}": f"{r['Studio']} · {r['Batch']}" for _, r in batches.iterrows()}
            pick = st.selectbox("Open a batch", list(labels), format_func=labels.get, key="batch_pick")
            if pick:
                studio_key, batch_id = pick.split("|", 1)
                members = app_df[(app_df["studio"] == studio_key) & (app_df["batch_id"] == batch_id)].sort_values("views", ascending=False)
                st.altair_chart(
                    alt.Chart(members)
                    .mark_bar(cornerRadiusEnd=4, color=STUDIO_COLORS.get(studio_key, BAR_COLOR))
                    .encode(
                        y=alt.Y("title:N", sort="-x", title=None, axis=alt.Axis(labelLimit=320)),
                        x=alt.X("views:Q", title="Views"),
                        tooltip=["title:N", alt.Tooltip("views:Q", format=","), alt.Tooltip("avg_view_pct:Q", title="% viewed", format=".1f"), "category:N"],
                    ),
                    width="stretch",
                    height=34 * len(members) + 56,
                )


# ====================================================================== videos
with tabs[3]:
    if df.empty:
        st.info("No published videos match these filters.")
    else:
        table = df.sort_values("published_at", ascending=False)[
            ["url", "title", "studio_label", "category", "topic", "published_at", "views", "views_per_day", "avg_view_pct",
             "likes", "comments", "shares", "subs_gained", "generation", "posted_via"]
        ]
        st.dataframe(
            table,
            hide_index=True,
            use_container_width=True,
            column_config={
                "url": st.column_config.LinkColumn("Link", display_text="▶", width="small"),
                "title": st.column_config.TextColumn("Title", width="large"),
                "studio_label": "Studio",
                "category": "Category",
                "topic": "Topic",
                "published_at": st.column_config.DatetimeColumn("Published", format="MMM D, YYYY"),
                "views": st.column_config.NumberColumn("Views", format="%d"),
                "views_per_day": st.column_config.NumberColumn("Views/day", format="%.1f"),
                "avg_view_pct": st.column_config.ProgressColumn("% viewed", format="%.0f%%", min_value=0, max_value=100),
                "likes": "Likes",
                "comments": "Comments",
                "shares": "Shares",
                "subs_gained": "Subs",
                "generation": "Made as",
                "posted_via": "Posted",
            },
        )
        st.download_button("⬇️ Download as CSV", table.to_csv(index=False).encode("utf-8"), "channel-analytics.csv", "text/csv")

    with st.expander("📁 Data files (CSV)"):
        st.caption(
            f"Everything analytics stores lives in `{store.analytics_dir()}` as CSV. `items.csv` remembers "
            "every video the app made, so videos swept from disk still count. Keep this folder out of "
            "any clean-up job, and in your backups."
        )
        for name in ("items.csv", "channel_videos.csv", "analytics.csv", "daily_stats.csv", "matches.csv", "posted_marks.csv", "topic_categories.csv"):
            path = os.path.join(store.analytics_dir(), name)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    st.download_button(f"⬇️ {name}", f.read(), name, "text/csv", key=f"dl_{name}")

    with st.expander("✏️ Topic categories"):
        st.caption(
            "Categories group one-off topics so \"which kinds of topics work\" has an answer. The app's LLM "
            "assigns them on each sync; correct any here (blank = let the AI pick again)."
        )
        decisions = store.load_links()
        linked_topics = sorted({i["topic"] for i in items if i["key"] in result["links"] and i["topic"]})
        editor = pd.DataFrame({"Topic": linked_topics, "Category": [decisions["categories"].get(t, "") for t in linked_topics]})
        edited = st.data_editor(editor, hide_index=True, use_container_width=True, disabled=["Topic"], key="cat_editor")
        e1, e2 = st.columns(2)
        if e1.button("💾 Save categories"):
            store.set_categories(dict(zip(edited["Topic"], edited["Category"].fillna(""))))
            _refresh()
        if e2.button("✨ Categorize the rest with AI"):
            with st.spinner("Asking the LLM…"):
                added = topics.categorize(linked_topics)
            st.toast(f"{len(added)} topics categorized")
            _refresh()


# =================================================================== reconcile
with tabs[4]:
    by_key = {i["key"]: i for i in items}
    by_video = {v["video_id"]: v for v in videos}
    methods = pd.Series([m["method"] for ms in result["links"].values() for m in ms]).value_counts()
    r = st.columns(5)
    r[0].metric("On the channel", len(videos))
    r[1].metric("Uploaded by the app", int(methods.get("app upload", 0)))
    r[2].metric("Posted by hand, matched", int(methods.get("title", 0) + methods.get("manual", 0) + methods.get("posted link", 0)))
    r[3].metric("To confirm", len(result["suggestions"]))
    r[4].metric("Not from the app", len(result["unmatched_videos"]))
    st.caption(
        "Videos you post by hand are matched to the app's video with the **same title** (case, emoji, "
        "punctuation and hashtags ignored) and marked as posted in their studio, which also takes them "
        "off the upload calendar. Close-but-not-equal titles wait here for you."
    )

    def _item_line(key: str) -> str:
        item = by_key.get(key, {})
        return f"{report.STUDIO_LABELS.get(item.get('studio'), '?')} · **{item.get('label', key)[:90]}**"

    def _video_line(video_id: str) -> str:
        v = by_video.get(video_id, {})
        published = (v.get("published_at") or "")[:10]
        return f"[{v.get('title', video_id)[:90]}](https://youtu.be/{video_id}) · {published} · {v.get('privacy_status', '')}"

    def _relink_and_refresh():
        sync.reconcile_now(videos)
        _refresh()

    if result["suggestions"]:
        st.subheader("Is this the same video?", anchor=False)
        if st.button(f"✅ Accept all {len(result['suggestions'])}"):
            for s in result["suggestions"]:
                store.link(s["item_key"], s["video_id"])
            _relink_and_refresh()
        for s in result["suggestions"]:
            with st.container(border=True):
                info, yes, no = st.columns([6, 1, 1], vertical_alignment="center")
                info.markdown(f"App: {_item_line(s['item_key'])}  \nYouTube: {_video_line(s['video_id'])}  \nTitle similarity {s['score']:.0%}")
                if yes.button("✅ Same", key=f"sug_yes_{s['item_key']}_{s['video_id']}"):
                    store.link(s["item_key"], s["video_id"])
                    _relink_and_refresh()
                if no.button("✖ No", key=f"sug_no_{s['item_key']}_{s['video_id']}"):
                    store.reject(s["item_key"], s["video_id"])
                    _refresh()

    if result["duplicates"]:
        st.subheader("Possible double uploads", anchor=False)
        st.caption("These channel videos have the same title as a video that is already matched. If one is a duplicate, consider removing it in YouTube Studio.")
        for d in result["duplicates"]:
            st.markdown(f"- {_video_line(d['video_id'])}: same title as {_item_line(d['item_key'])}")

    if result["missing_posted"]:
        st.subheader("Marked posted, but not found on the channel", anchor=False)
        st.caption("Usually the title was changed when posting. Link it below, or check it is not still a private draft on another channel.")
        for key in result["missing_posted"]:
            st.markdown(f"- {_item_line(key)}")

    if result["gone"]:
        with st.expander(f"Uploaded by the app but no longer on the channel ({len(result['gone'])})"):
            for g in result["gone"]:
                st.markdown(f"- {_item_line(g['item_key'])} (was `{g['video_id']}`)")

    st.subheader("Link a channel video by hand", anchor=False)
    open_items = [i for i in items if i["key"] not in result["links"]]
    unmatched = [v for v in videos if v["video_id"] in set(result["unmatched_videos"])]
    if not unmatched:
        st.caption("Every channel video is matched. 🎉")
    elif not open_items:
        st.caption(f"{len(unmatched)} channel videos aren't from the app (e.g. older uploads); every app video is already matched.")
    else:
        l1, l2, l3 = st.columns([3, 3, 1], vertical_alignment="bottom")
        vid = l1.selectbox(
            "Channel video", [v["video_id"] for v in unmatched],
            format_func=lambda v: f"{by_video[v]['title'][:70]} ({(by_video[v].get('published_at') or '')[:10]})", key="manual_vid",
        )
        target = reconcile.normalize_title(by_video[vid]["title"]) if vid else ""

        def _closeness(item):
            import difflib

            return max((difflib.SequenceMatcher(None, target, reconcile.normalize_title(t)).ratio() for t in item["titles"]), default=0)

        ranked = sorted(open_items, key=_closeness, reverse=True)
        key = l2.selectbox(
            "Is this app video", [i["key"] for i in ranked],
            format_func=lambda k: f"{report.STUDIO_LABELS[by_key[k]['studio']]} · {by_key[k]['label'][:70]}", key="manual_item",
        )
        if l3.button("🔗 Link", use_container_width=True, disabled=not (vid and key)):
            store.link(key, vid)
            _relink_and_refresh()

    with st.expander("Undo a match"):
        linked = [(k, m) for k, ms in result["links"].items() for m in ms if m["method"] != "app upload"]
        if not linked:
            st.caption("Nothing to undo: only the app's own uploads are matched.")
        else:
            choice = st.selectbox(
                "Match", range(len(linked)),
                format_func=lambda n: f"{by_key[linked[n][0]]['label'][:60]} ↔ {by_video.get(linked[n][1]['video_id'], {}).get('title', '')[:60]} ({METHOD_LABELS.get(linked[n][1]['method'], '')})",
                key="undo_pick",
            )
            st.caption("The pair is never matched again. The studio's \"posted\" mark stays; remove it on the library card if needed.")
            if st.button("Unlink"):
                k, m = linked[choice]
                store.reject(k, m["video_id"])
                _refresh()


# =================================================================== assistant
with tabs[5]:
    # All published videos; the chat has its own data-range picker.
    analytics_assistant_ui.render(df_all)
