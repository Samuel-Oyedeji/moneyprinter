# Analytics Assistant

A chat on the **Analytics** page (tab **💬 Assistant**) for working through
your numbers. Ask which animation styles work, why a batch flopped, or for
title ideas based on your best performers. It answers from your own data
and says how many videos each claim rests on.

## Setup

None, if the Animation studio already works. The assistant uses the same
OpenRouter key and client (`[app] openrouter_api_key`). Without a key, the
tab shows a box to paste one (<https://openrouter.ai/settings/keys>).

## Metric tags: what the assistant can see

A **metric tag** is a named slice of your analytics. You attach tags to a
chat with **📎 Data the assistant can see**, and their data is sent with
every question.

**Built-in tags** are generated from your data. There's one for every
metric the studios record today:

| Tag | What it holds |
|---|---|
| Studio vs studio | each studio's results side by side |
| Best & weakest videos | top 15 / bottom 10 by views per day, with titles |
| Batches | every generation batch with its best and weakest video |
| Topic categories | results per topic category |
| *Studio* · every video | each video's title, numbers and style, best first |
| *Studio* · what stands out | the groups that clearly beat or trail the typical video |
| Animations · Main setting, Characters, Transitions, Scenes, Settings per video, Planned length, Voice, … | one row per value, with median views, views/day, views at 7 days, % viewed, engagement, subscribers |
| Shorts · Footage source, Voice, Music, Subtitles, … | the same, per Shorts setting |
| Documentaries · Planned length, Made from, … | the same, per documentary setting |
| *Studio* · Topic category, Batch or single, Publish day, Publish hour, Length, How it was posted | the shared dimensions, per studio |

When a studio starts recording a new style setting (a new animation look,
say), its tag shows up on its own; nothing to configure.

**Your own tags** (**🏷 Metric tags: see and create your own**):

1. Name it, e.g. "Space animations".
2. Pick a studio (or all).
3. Optionally narrow it down, with up to two filters: *Main setting is
   space*, *Characters is any of animal, person*.
4. Choose what to show: each video, or a breakdown by another setting
   (e.g. *broken down by Characters*).
5. Optionally add a note the assistant will read ("my new cut-out style").
6. **👁 Preview what the assistant sees**, then **💾 Save tag**.

Your tags are marked 🏷 in the picker and live in
`storage/analytics/tags.json`.

**The assistant can look things up too.** On models that support tool
calling (most current ones), it can list every tag, load any of them, and
search videos by title, topic and studio, sorted by any metric. Each reply
says what it looked at. Models without tool support answer from the
attached tags only, so attach what the question needs.

**Data range:** *Videos published* limits everything (attached tags and
lookups) to the last 30 days, 90 days, year, or all time.

The caption under the picker shows roughly how many tokens the attached
data adds to each question. Attachments over about 60,000 characters are
cut, and the assistant is told to fetch the rest itself.

## Models

Pick any model from OpenRouter's list (with its price per million tokens),
or type a model ID. The choice is saved on the chat and becomes the default
for new chats (`[assistant] model` in `config.toml`; empty = the Animation
studio's writer model). Each reply shows the model and its cost; the chat
header shows the running total.

## Chat history

Every chat is saved as `storage/analytics/chats/<id>.json`: messages,
model, attached tags, data range and cost.

- **＋ New chat** starts fresh with the same attached tags.
- Click a chat in the list to reopen it and carry on.
- **⋯** renames or deletes a chat. **🗑 Delete all chats** clears the list.
- A chat is named after its first question.
- The assistant gets the last 30 messages of the conversation. A failed
  reply stays visible but isn't sent to the model again.

## Good questions to start with

The empty chat offers four, and each attaches the tags it needs:

- Which animation styles get the most views?
- Suggest 10 titles for my next videos, based on what works.
- Which kinds of topics should I make more of, and which less?
- Do batches do better than one-off videos?

Others that work well:

- "Compare space and forest animations on retention, not just views."
- "My last batch underperformed. What's different about it?"
- "Write 5 titles for a fable about honesty in the style of my top 3."
- "Which publish hour works best for Shorts? Is that a real effect or
  too few videos?"
