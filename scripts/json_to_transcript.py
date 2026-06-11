#!/usr/bin/env python3
"""
json_to_transcript.py — Transform THREAD_MASTER JSON → polished legal transcript HTML.

Purpose:
  Generate print-optimized, forensically-labeled communication transcripts for
  use as exhibits in case 25FA152 (Byers v. Donatello). The transcript HTML
  preserves full metadata while being page-break-safe and legible in black and
  white or color.

Pipeline position — last step of THREAD_MASTER workflow:
  SMS/HTML exports + Gmail mbox + Google Voice HTML + Apple Messages
    → build_thread_master.py (dedup + channel healing + sender normalization)
    → THREAD_MASTER_<Contact>.json (entries across all channel types)
    → json_to_transcript.py (collapse + classify + render)
    → THREAD_MASTER_<Contact>_Transcript.html (print-ready HTML blocks)

Supports THREAD_MASTER files for any contact (Violette, Pauletta, etc.).
Sender styles and channel mappings are defined at the top of the module.

Key transformations:
  1. Collapse: Group (timestamp, sender, message[:200]) to block duplicate
     sends. Different messages at the same second (e.g. an app share + a text)
     produce separate blocks — they are NOT merged.
  2. Reclassify: Detect tapback reactions → "imessage_tapback" channel.
     Detect .pluginPayloadAttachment → "imessage_extension" channel.
  3. Suppress: U+FFFC placeholders (media/sticker artifacts), "[no text content]"
     shells, and empty-shell blocks (no message, no attachment, no raw_sender)
     are removed from transcript but preserved in JSON.
  4. Style: Per-sender background/border/name colors. Gmail mbox blocks get
     cream background (#fffdf6) with amber border (#d4af37). Group-chat labels
     appended to metadata row. Raw_sender shown as muted sub-text.
  5. page-break-inside: avoid on every block for booklet/notebook printing.

Usage:
    uv run dc13_hive/scripts/json_to_transcript.py \
        -i 25FA152/COMMS/THREAD_MASTER_Violette.json \
        -o 25FA152/COMMS/THREAD_MASTER_Violette_Transcript.html

    uv run dc13_hive/scripts/json_to_transcript.py \
        -i 25FA152/COMMS/THREAD_MASTER_Violette.json \
        -o /tmp/transcript.html \
        --title "Byers v. Donatello — Communication Transcript (v2)"

Output:
  - Print-optimized HTML with inline CSS (no external dependencies)
  - Every block is numbered (e.g. #1/4912)
  - Metadata line: sender | timestamp | channel (with color-coded dot) | group-chat
  - Forensic trace line (muted): raw_sender(s); attachment filenames
  - Console summary: blocks, date range, channel distribution (count + %)
"""

import argparse
import json
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Channel label mapping (forensic display names)
# ---------------------------------------------------------------------------
CHANNEL_LABELS = {
    "imessage": "iMessage (Encrypted)",
    "sms": "SMS (Unencrypted)",
    "SMS": "SMS (Unencrypted)",
    "google_voice": "Google Voice",
    "gmail_mbox": "Gmail (mbox)",
    "gmail_md": "Gmail (markdown export)",
    "TalkingParents": "TalkingParents",
    "Email": "Email",
    "unknown": "Unknown Channel",
    "imessage_tapback": "iMessage Tapback (Reaction)",
    "imessage_extension": "iMessage Extension (App Data)",
}

CHANNEL_DOT_COLORS = {
    "imessage": "#1982FC",
    "sms": "#65c466",
    "SMS": "#65c466",
    "google_voice": "#dddddd",
    "gmail_mbox": "#d4af37",
    "gmail_md": "#bbbbbb",
    "TalkingParents": "#9b59b6",
    "Email": "#3498db",
    "unknown": "#aaaaaa",
    "imessage_tapback": "#ff9500",
    "imessage_extension": "#af52de",
}

# Priority: lower number = higher priority, strict single-value overwrite.
# Tapback/Extension reclassification happens AFTER priority merge (see
# _collapse_groups "Signature extrapolation"), so they always win.
CHANNEL_PRIORITY = {
    "imessage_tapback": 1,
    "imessage_extension": 2,
    "imessage": 3,
    "sms": 4,
    "SMS": 4,
    "google_voice": 5,
    "gmail_mbox": 6,
    "TalkingParents": 6,
    "Email": 7,
    "gmail_md": 7,
    "unknown": 8,
}

# iOS system strings for iMessage tapback reactions — these prefix the quoted
# message text in the Apple Messages export, e.g. "Loved “Good morning daddy ”"
TAPBACK_VERBS = ("Loved", "Liked", "Disliked", "Laughed at", "Emphasized", "Questioned")

# Sender display colors
SENDER_STYLES = {
    "Me": {
        "bg": "#f0f4f8",
        "border": "#dde3ed",
        "name_color": "#1a4971",
        "label": "Me (David)",
    },
    "Violette Donatello": {
        "bg": "#ffffff",
        "border": "#e0e0e0",
        "name_color": "#8b2252",
        "label": "Violette Donatello",
    },
    "David C. Byers": {
        "bg": "#f0f4f8",
        "border": "#dde3ed",
        "name_color": "#1a4971",
        "label": "David C. Byers",
    },
    "Pauletta Donatello": {
        "bg": "#fff8f0",
        "border": "#f0e0d0",
        "name_color": "#a0522d",
        "label": "Pauletta Donatello",
    },
}

DEFAULT_SENDER_STYLE = {
    "bg": "#fafafa",
    "border": "#e8e8e8",
    "name_color": "#555555",
    "label": None,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_sender_style(sender: str) -> dict:
    return SENDER_STYLES.get(sender, DEFAULT_SENDER_STYLE)


def _fmt_ts(ts: str) -> str:
    if not ts:
        return "Unknown date"
    try:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(ts, fmt)
                return dt.strftime("%b %d, %Y  %I:%M:%S %p").replace(" 0", " ").lstrip("0")
            except ValueError:
                continue
        return ts
    except Exception:
        return ts


def _channel_display(ch: str) -> str:
    return CHANNEL_LABELS.get(ch, ch)


def _escape_html(text: str) -> str:
    if not text:
        return ""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace("\n", "<br>")
    return text


def _is_placeholder(msg: str) -> bool:
    """Return True if the message text is a placeholder to suppress."""
    if not msg:
        return True
    stripped = msg.strip()
    if not stripped:
        return True
    if stripped == "[no text content]":
        return True
    # Object replacement character U+FFFC (media/sticker placeholder)
    if stripped == "\ufffc" or stripped == "\ufffc\ufffc":
        return True
    return False


def _is_tapback(msg: str) -> bool:
    """Detect iMessage tapback reaction from message text."""
    if not msg:
        return False
    stripped = msg.strip()
    for verb in TAPBACK_VERBS:
        if stripped.startswith(verb):
            return True
    return False


def _is_plugin_attachment(attachment: str, message: str) -> bool:
    """Detect iMessage extension (app data) from attachment or message."""
    if attachment and ".pluginPayloadAttachment" in attachment:
        return True
    if message and ".pluginPayloadAttachment" in message:
        return True
    return False


# Email domains that route through Apple's iMessage network.
# Messages from these addresses are always blue-bubble (E2EE) iMessages.
_IMESSAGE_DOMAINS = ("icloud.com", "iyou.me", "me.com")


def _infer_channel_from_raw_sender(raw_senders: list[str]) -> str | None:
    """Infer channel from raw_sender when no direct channel signal exists.

    - Email addresses on Apple domains (icloud.com, iyou.me, me.com) → imessage
    - Phone numbers starting with + → sms
    - Other email addresses → None (don't guess, e.g. gmail is ambiguous)

    This is a conservative fallback: it only fires for entries where every
    group member has channel="unknown" and there's recoverable metadata.
    """
    if not raw_senders:
        return None
    for raw in raw_senders:
        if "@" in raw:
            domain = raw.split("@", 1)[1].lower().strip()
            if domain in _IMESSAGE_DOMAINS:
                return "imessage"
        elif raw.startswith("+"):
            return "sms"
    return None


# ---------------------------------------------------------------------------
# Near-Duplicate Detection & Merge
# ---------------------------------------------------------------------------

def _strip_emoji(text: str) -> str:
    """Remove emoji and other symbolic Unicode characters (category So)."""
    return "".join(ch for ch in text if unicodedata.category(ch) != "So")


def _normalize_for_compare(text: str) -> str:
    """Normalize message text for fuzzy near-duplicate comparison.

    Strips trailing whitespace/punctuation, removes emoji, collapses
    whitespace, lowercases. The result is a clean string that can be
    compared for prefix/equality matching.
    """
    text = text.rstrip().rstrip(".,!?;:)'\"")
    text = _strip_emoji(text)
    text = " ".join(text.split())
    return text.lower()


def _is_near_duplicate(msg1: str, msg2: str) -> bool:
    """Check if two messages are near-duplicates (differ only by emoji/punctuation/trailing words).

    Rules:
      1. After normalization, equal → yes.
      2. One is a prefix of the other and the longer is <2× the shorter → yes.
      3. Otherwise → no.
    """
    if not msg1 or not msg2:
        return False
    n1 = _normalize_for_compare(msg1)
    n2 = _normalize_for_compare(msg2)
    if n1 == n2:
        return True
    if n1.startswith(n2) or n2.startswith(n1):
        shorter = min(len(n1), len(n2))
        longer = max(len(n1), len(n2))
        if shorter > 0 and longer / shorter < 2.0:
            return True
    return False


def _merge_near_duplicates(blocks: list[dict]) -> list[dict]:
    """Merge adjacent blocks with same (timestamp, sender) and near-identical messages.

    Keeps the longer message and the higher-priority channel. Also merges
    raw_sender lists so forensic traceability is preserved.
    """
    if not blocks:
        return blocks
    merged = [blocks[0]]
    for block in blocks[1:]:
        last = merged[-1]
        if (
            block.get("timestamp") == last.get("timestamp")
            and block.get("sender") == last.get("sender")
            and _is_near_duplicate(
                block.get("message", ""), last.get("message", "")
            )
        ):
            # Keep longer message (more complete version)
            if len(block.get("message", "")) > len(last.get("message", "")):
                last["message"] = block["message"]
            # Merge raw_senders
            last_raw = last.get("raw_sender", "")
            block_raw = block.get("raw_sender", "")
            if block_raw and block_raw not in last_raw:
                last["raw_sender"] = "; ".join(
                    filter(None, [last_raw, block_raw])
                )
            # Channel priority: prefer higher-priority channel
            existing_prio = CHANNEL_PRIORITY.get(
                last.get("channel", "unknown"), 99
            )
            incoming_prio = CHANNEL_PRIORITY.get(
                block.get("channel", "unknown"), 99
            )
            if incoming_prio < existing_prio:
                last["channel"] = block["channel"]
        else:
            merged.append(block)
    return merged


# ---------------------------------------------------------------------------
# Group Collapse
# ---------------------------------------------------------------------------

def _collapse_groups(entries: list[dict]) -> list[dict]:
    """Collapse entries sharing the same (timestamp, sender, message) into blocks.

    For each group:
      - Suppress placeholder-only entries (empty, U+FFFC, [no text content])
      - Collect all unique non-placeholder messages
      - Detect tapback reactions and reclassify channel
      - Detect plugin attachments and reclassify channel
      - Merge attachment filenames into a list
      - Preserve raw_sender from any member
      - Use highest-priority channel across group members

    NOTE: Message content is part of the grouping key so that distinct
    messages sent within the same second (e.g. an app share + a text)
    produce separate transcript blocks rather than being merged.
    """
    groups = defaultdict(list)
    for m in entries:
        key = (m.get("timestamp", ""), m.get("sender", ""),
               m.get("message", "")[:200])
        groups[key].append(m)

    collapsed = []
    for (ts, sender, _msg_prefix), group in groups.items():
        merged = {
            "timestamp": ts,
            "sender": sender,
            "channel": "unknown",
            "messages": [],
            "attachments": [],
            "raw_senders": [],
        }

        for m in group:
            msg_text = m.get("message", "") or ""
            att = m.get("attachment", "") or ""
            ch = m.get("channel", "unknown")
            raw = m.get("raw_sender", "")

            # Track channel priority
            existing_prio = CHANNEL_PRIORITY.get(merged["channel"], 99)
            incoming_prio = CHANNEL_PRIORITY.get(ch, 99)
            if incoming_prio < existing_prio:
                merged["channel"] = ch

            # Track group chat participants
            gc = m.get("group_chat", "")
            if gc and not merged.get("group_chat"):
                merged["group_chat"] = gc

            # Track subject (email / TalkingParents threads)
            subj = m.get("subject", "") or m.get("subject_header", "")
            if subj:
                merged["subject"] = subj

            # Track raw_sender
            if raw and raw not in merged["raw_senders"]:
                merged["raw_senders"].append(raw)

            # Collect non-placeholder messages
            if not _is_placeholder(msg_text):
                if msg_text not in merged["messages"]:
                    merged["messages"].append(msg_text)

            # Collect attachments
            if att and att not in merged["attachments"]:
                merged["attachments"].append(att)

        # --- Signature extrapolation (overrides base channel) ---
        # After priority merge, reclassify by content signature:
        #   - imessage_tapback: messages starting with iOS tapback verbs
        #     (Loved, Liked, etc.) — highest priority (1)
        #   - imessage_extension: messages/attachments containing
        #     .pluginPayloadAttachment refs (app shares, Digital Touch, etc.)
        #     — second-highest priority (2)
        # Check tapback first (more specific)
        has_tapback = any(_is_tapback(msg) for msg in merged["messages"])
        has_plugin = any(
            _is_plugin_attachment(att, "")
            for att in merged["attachments"]
        ) or any(
            _is_plugin_attachment("", msg)
            for msg in merged["messages"]
        )

        if has_tapback:
            merged["channel"] = "imessage_tapback"
        elif has_plugin:
            merged["channel"] = "imessage_extension"

        # --- Raw sender channel inference ---
        # If channel is still unknown and we have raw_sender metadata,
        # conservatively infer the channel from the sender identity:
        #   icloud.com/iyou.me/me.com email  → imessage
        #   +1... phone number                → sms
        if merged["channel"] == "unknown":
            inferred = _infer_channel_from_raw_sender(merged.get("raw_senders", []))
            if inferred:
                merged["channel"] = inferred

        build = {
            "timestamp": ts,
            "sender": sender,
            "message": "\n".join(merged["messages"]),
            "channel": merged["channel"],
        }
        if merged.get("group_chat"):
            build["group_chat"] = merged["group_chat"]
        if merged.get("subject"):
            build["subject"] = merged["subject"]
        if merged["raw_senders"]:
            build["raw_sender"] = "; ".join(merged["raw_senders"])
        if merged["attachments"]:
            build["attachment"] = "; ".join(merged["attachments"])

        # Empty shell blocks: entries with no message text, no attachment, and
        # no raw_sender. These are iMessage artifacts (read receipts, typing
        # indicators, delivery confirmations) that have no recoverable content.
        # They remain in the THREAD_MASTER JSON for audit completeness but are
        # suppressed from the transcript — they convey no communication content.
        if (not build.get("message")
                and not merged.get("attachments")
                and not merged.get("raw_senders")):
            continue

        collapsed.append(build)

    collapsed.sort(key=lambda m: m.get("timestamp", ""))
    collapsed = _merge_near_duplicates(collapsed)
    return collapsed


# ---------------------------------------------------------------------------
# HTML Message Block
# ---------------------------------------------------------------------------

def _build_message_block(msg: dict, idx: int, total: int) -> str:
    """Render a single message block as self-contained HTML.

    Each block includes:
      - Index number (1-based, e.g. #1/4912) for cross-reference
      - Sender display name (color-coded per SENDER_STYLES)
      - Formatted timestamp
      - Channel label with color-coded dot
      - Optional group-chat participant label
      - Optional email subject line
      - Message body (HTML-escaped)
      - Traceability sub-text: raw_sender + attachment filenames (muted)
    """
    ts = msg.get("timestamp", "")
    sender = msg.get("sender", "Unknown")
    channel = msg.get("channel", "unknown")
    group_chat = msg.get("group_chat", "")
    subject = msg.get("subject", "")
    raw_sender = msg.get("raw_sender", "")
    attachment = msg.get("attachment", "")
    message = msg.get("message", "")

    style = _get_sender_style(sender)
    sender_display = style.get("label") or sender
    formatted_ts = _fmt_ts(ts)

    # Channel-specific styling overrides
    if channel == "gmail_mbox":
        block_bg = "#fffdf6"
        block_border = "#d4af37"
    else:
        block_bg = style["bg"]
        block_border = style["border"]

    # Build metadata line (top of block)
    meta_parts = [f"Channel: {_channel_display(channel)}"]
    meta_str = " | ".join(meta_parts)

    # Subject sub-header (email only)
    subject_html = (
        f'<div class="msg-subject" style="font-weight:700; font-size:13px; '
        f'color:#8b6914; margin-bottom:4px;">'
        f'{_escape_html(subject)}</div>'
    ) if subject else ""

    # Message content
    body_html = _escape_html(message) if message else (
        "<em style='color: #999;'>[no text content]</em>"
    )

    # Traceability sub-text (muted, below message)
    trace_parts = []
    if raw_sender:
        trace_parts.append(f"Original sender: {_escape_html(raw_sender)}")
    if attachment:
        trace_parts.append(f"Attachments: {_escape_html(attachment)}")
    trace_html = (
        '<div class="msg-trace" style="color:#999; font-size:10px; margin-top:6px; '
        'border-top:1px solid #eee; padding-top:4px;">'
        + " | ".join(trace_parts)
        + "</div>"
    ) if trace_parts else ""

    channel_dot = CHANNEL_DOT_COLORS.get(channel, "#aaaaaa")

    return f"""\
    <div class="msg msg-{idx % 2}" style="background:{block_bg}; border-left:4px solid {block_border};">
      <div class="msg-meta" style="color:#666; font-size:11px; margin-bottom:6px;">
        <span class="msg-index" style="color:#aaa; margin-right:8px;">#{idx+1}/{total}</span>
        <strong style="color:{style['name_color']};">{sender_display}</strong>
        — {formatted_ts}
        <span class="msg-channel" style="margin-left:8px; font-style:italic;">
          <span class="channel-dot" style="display:inline-block; width:8px; height:8px; border-radius:50%;
                background:{channel_dot}; margin-right:3px;"></span>
          {_escape_html(meta_str)}
        </span>
        {'<span class="msg-group" style="color:#999; font-size:10px; margin-left:8px;">[Group: ' + _escape_html(group_chat) + ']</span>' if group_chat else ''}
      </div>
      {subject_html}
      <div class="msg-body" style="font-size:14px; line-height:1.55; color:#333;">
        {body_html}
      </div>
      {trace_html}
    </div>
"""


# ---------------------------------------------------------------------------
# HTML Document Assembly
# ---------------------------------------------------------------------------

def _generate_html(all_messages: list[dict], title: str, original_count: int = 0) -> str:
    total = len(all_messages)
    blocks = []
    for i, msg in enumerate(all_messages):
        blocks.append(_build_message_block(msg, i, total))
    messages_html = "\n".join(blocks)

    # Build legend items dynamically from channels present
    channels_present = sorted(set(m.get("channel", "unknown") for m in all_messages))
    legend_items = ""
    for ch in channels_present:
        dot = CHANNEL_DOT_COLORS.get(ch, "#aaaaaa")
        label = CHANNEL_LABELS.get(ch, ch)
        legend_items += (
            f'<span class="legend-item">'
            f'<span class="legend-dot" style="background:{dot};"></span> {label}</span>\n  '
        )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape_html(title)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: Helvetica, Arial, system-ui, sans-serif;
    background: white;
    color: #333;
    max-width: 800px;
    margin: 0 auto;
    padding: 40px 30px;
    font-size: 13px;
    line-height: 1.5;
  }}
  .header {{
    text-align: center;
    margin-bottom: 40px;
    padding-bottom: 20px;
    border-bottom: 2px solid #222;
  }}
  .header h1 {{ font-size: 18px; font-weight: 700; margin-bottom: 4px; }}
  .header .subtitle {{ color: #666; font-size: 12px; }}
  .header .stats {{ color: #888; font-size: 11px; margin-top: 6px; }}
  .legend {{
    display: flex; flex-wrap: wrap; gap: 8px 18px;
    margin-bottom: 30px; padding: 10px 14px;
    background: #f8f8f8; border-radius: 6px; font-size: 11px;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 5px; }}
  .legend-dot {{
    display: inline-block; width: 10px; height: 10px; border-radius: 50%;
  }}
  .msg {{
    page-break-inside: avoid;
    padding: 12px 16px;
    margin-bottom: 10px;
    border-radius: 6px;
  }}
  .msg:last-child {{ margin-bottom: 0; }}
  @media print {{
    body {{ padding: 20px 15px; }}
    .header {{ margin-bottom: 30px; }}
  }}
  .footer {{
    margin-top: 40px; padding-top: 16px;
    border-top: 1px solid #ddd;
    text-align: center; font-size: 10px; color: #999;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>Communication Transcript</h1>
  <div class="subtitle">{_escape_html(title)}</div>
  <div class="stats">
    {total} message blocks
    (collapsed from {original_count} raw entries)
    | Generated {datetime.now().strftime("%B %d, %Y")}
  </div>
</div>

<div class="legend">
  <span style="font-weight:600; margin-right:4px;">Channel Legend:</span>
  {legend_items}
</div>

{messages_html}

<div class="footer">
  Case 25FA152 — Byers v. Donatello &nbsp;|&nbsp; Generated by json_to_transcript.py
</div>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Transform THREAD_MASTER JSON → polished legal transcript HTML"
    )
    parser.add_argument("-i", "--input", required=True)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument(
        "--title",
        default="Byers v. Donatello — Communication Transcript",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[ERROR] Input not found: {input_path}", file=__import__('sys').stderr)
        return 1

    with open(input_path, "r", encoding="utf-8") as f:
        raw_entries = json.load(f)

    if not raw_entries:
        print("[ERROR] Empty message list", file=__import__('sys').stderr)
        return 1

    print(f"Read {len(raw_entries)} raw entries from {args.input}")

    # Sort before collapsing
    raw_entries.sort(key=lambda m: m.get("timestamp", ""))

    # Collapse concurrent timestamp+sender groups
    collapsed = _collapse_groups(raw_entries)
    print(f"Collapsed into {len(collapsed)} message blocks "
          f"(removed {len(raw_entries) - len(collapsed)} redundant rows)")

    # Generate HTML
    html = _generate_html(collapsed, args.title, original_count=len(raw_entries))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Wrote {len(html):,} bytes to {output_path}")
    print(f"  Blocks: {len(collapsed)}")
    print(f"  Date range: {collapsed[0].get('timestamp','?')} to {collapsed[-1].get('timestamp','?')}")

    channels = Counter(m.get("channel", "unknown") for m in collapsed)
    for ch, ct in channels.most_common():
        print(f"    {ch}: {ct} ({ct/len(collapsed)*100:.1f}%)")

    return 0


if __name__ == "__main__":
    main()
