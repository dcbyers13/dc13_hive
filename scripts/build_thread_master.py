#!/usr/bin/env python3
"""
build_thread_master.py — Consolidate Apple Messages (iMessage + SMS),
Gmail exports, Mbox exports, and Google Voice data into
THREAD_MASTER JSON (single source of truth for per-contact communications).

DATA SOURCE NOTES:
- Apple Messages export (JSON or HTML) covers iMessage blue-bubble (E2EE)
  AND SMS green-bubble messages received from contacts' Google Voice numbers.
- Gmail .md exports come from Google Takeout.
- Mbox files (standard mboxrd format) come from Google Takeout or Thunderbird.
- Google Voice Text HTML exports come from Google Takeout (Voice/Calls/)
  with filenames containing " - Text - ".

Usage:
    uv run dc13_hive/scripts/build_thread_master.py \
        --contact violette \
        --html-dir 25FA152/COMMS/sms/Violette_HTML \
        --gmail-dir 25FA152/COMMS/unsorted_email \
        --existing 25FA152/COMMS/Violette_Final_Timeline_With_Assets.json \
        --output 25FA152/COMMS/THREAD_MASTER_Violette.json

    uv run dc13_hive/scripts/build_thread_master.py \
        --contact violette \
    --existing 25FA152/COMMS/Violette_Final_Timeline_With_Assets.json \
    --mbox 25FA152/INGEST/Violette_from_dcbyers13.mbox \
    --mbox 25FA152/INGEST/Violette_from_baddod13.mbox \
    --output 25FA152/COMMS/THREAD_MASTER_Violette.json

    uv run dc13_hive/scripts/build_thread_master.py \
        --contact pauletta \
        --gmail-dir 25FA152/COMMS/unsorted_email \
        --output 25FA152/COMMS/THREAD_MASTER_Pauletta.json

    uv run dc13_hive/scripts/build_thread_master.py
        --contact pauletta
        --gmail-dir 25FA152/COMMS/unsorted_email
        --output 25FA152/COMMS/THREAD_MASTER_Pauletta.json

    uv run dc13_hive/scripts/build_thread_master.py
        --contact pauletta
        --existing 25FA152/COMMS/Pauletta_some_export.json
        --gmail-dir 25FA152/COMMS/unsorted_email
        --tp-dir 25FA152/COMMS  # TalkingParents records (future)
        --output 25FA152/COMMS/THREAD_MASTER_Pauletta.json

    uv run dc13_hive/scripts/build_thread_master.py \
        --contact violette \
        --gv-dir 25FA152/INGEST/Violette_from_myGV/Takeout/Voice/Calls \
        --existing 25FA152/COMMS/THREAD_MASTER_Violette.json \
        --output 25FA152/COMMS/THREAD_MASTER_Violette.json

Schema (each entry):
    {
        "timestamp": "YYYY-MM-DD HH:MM:SS",
        "sender": "Me" | "ContactName" | "email@example.com" | "+17735551234",
        "message": "text content",
        "attachment": "filename.ext"  // optional
    }
"""

import argparse
import email
import email.policy
import json
import os
import re
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

try:
    from bs4 import BeautifulSoup

    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


# ---------------------------------------------------------------------------
# 1. Apple Messages HTML Export Parser (iMessage blue-bubble + SMS green-bubble)
# ---------------------------------------------------------------------------
# Channel taxonomy for trial-ready forensic classification:
#   imessage     — Apple iMessage network (End-to-End Encrypted, blue bubble)
#   sms          — Cellular carrier SMS (Unencrypted plain text, green bubble)
#   google_voice — Google Voice account (VOIP gateway, server-side logged)
#   gmail_mbox   — Gmail Takeout .mbox (Standard IMAP/SMTP email)
#   gmail_md     — Legacy markdown email export (pre-processed, no raw headers)
#   unknown      — Seed data where original metadata was discarded

# Deduplication channel hierarchy (strict overwrite, no merging):
#   imessage > sms > google_voice > gmail_mbox > gmail_md > unknown
CHANNEL_PRIORITY = {
    "imessage": 1,
    "sms": 2,
    "google_voice": 3,
    "gmail_mbox": 4,
    "gmail_md": 5,
    "unknown": 6,
}

# Received message attribution rules based on contact identifier:
#   - Email address → imessage (Apple ID routing, push network only)
#   - Phone number → inferred from thread's outgoing bubble pattern
#       (100% iMessage outgoing → imessage; 100% SMS outgoing → sms;
#        mixed or no data → unknown)
CONTACT_CHANNEL_OVERRIDE = {
    # Hard-coded exceptions if automatic detection fails
}

SENDER_NORMALIZATION = {
    # Maps raw sender strings to canonical display names
    # Used for dedup key normalization so entries from different sources
    # with the same person can be matched and channel-healed.
    "violettemichele@icloud.com": "Violette Donatello",
    "violette@iyou.me": "Violette Donatello",
    "+18157614877": "Violette Donatello",
    "+18152068357": "Violette Donatello",
    "Violette Donatello": "Violette Donatello",
    "Violette Michele": "Violette Donatello",
    "+16307018735": "Pauletta Donatello",
    "Pauletta": "Pauletta Donatello",
    "+18159013610": "Jake Pisarski",
    "zadynneill@icloud.com": "Zadyn Neill",
    "zadyn@iyou.me": "Zadyn Neill",
    "Zadyn Neill": "Zadyn Neill",
    "Jakebroth": "Jake Pisarski",
}


def normalize_sender(sender: str) -> str:
    """Normalize a sender string to its canonical display name."""
    return SENDER_NORMALIZATION.get(sender, sender)


class SMSHTMLParser(HTMLParser):
    """Parse the SMS export HTML files into structured messages.

    Extracts per-message channel directly from bubble CSS class:
      class="sent iMessage" → channel="imessage"
      class="sent SMS"      → channel="sms"
      class="received"      → channel left unset (attributed post-parse
                              via contact-level rules)
    """

    def __init__(self):
        super().__init__()
        self.messages = []
        self._in_message = False
        self._in_sent = False
        self._in_received = False
        self._in_timestamp = False
        self._in_sender = False
        self._in_bubble = False
        self._in_app = False
        self._in_app_header_name = False
        self._in_app_footer_caption = False
        self._app_name = ""
        self._app_caption = ""
        self._current = {}
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "")
        class_list = classes.split()

        if tag == "div":
            # Track ALL div nesting depth for correct message boundary detection
            if "message" in class_list:
                if self._depth == 0:
                    self._in_message = True
                    self._current = {}
            self._depth += 1

        if self._in_message:
            if tag == "div":
                if "sent" in class_list:
                    self._in_sent = True
                    # Extract channel from bubble CSS class
                    if "iMessage" in class_list:
                        self._current["channel"] = "imessage"
                    elif "SMS" in class_list:
                        self._current["channel"] = "sms"
                elif "received" in class_list:
                    self._in_received = True
                    # Channel left unset — attributed in post-processing
                elif "app" in class_list:
                    self._in_app = True
                    self._app_name = ""
                    self._app_caption = ""
                elif self._in_app:
                    if "name" in class_list and not self._in_app_header_name:
                        self._in_app_header_name = True
                    elif "caption" in class_list and not self._in_app_footer_caption:
                        self._in_app_footer_caption = True

            if "timestamp" in class_list and tag == "span":
                self._in_timestamp = True

            if "sender" in class_list and tag == "span":
                self._in_sender = True

            if "bubble" in class_list and tag == "span":
                self._in_bubble = True

    def handle_endtag(self, tag):
        if self._in_message and tag == "div":
            # Reset app sub-element flags when closing their container divs
            if self._in_app_header_name:
                self._in_app_header_name = False
            elif self._in_app_footer_caption:
                self._in_app_footer_caption = False

            self._depth -= 1
            if self._depth == 0:
                self._in_message = False
                # Build app extension message if app data was collected
                if self._app_name and not self._current.get("message"):
                    msg = f"[App Extension: {self._app_name}]"
                    if self._app_caption:
                        msg += f" — {self._app_caption}"
                    self._current["message"] = msg
                if (
                    self._current.get("timestamp")
                    and self._current.get("sender") is not None
                ):
                    self.messages.append(self._current)
                self._current = {}
                self._in_sent = False
                self._in_received = False
                self._in_app = False
                self._in_app_header_name = False
                self._in_app_footer_caption = False
                self._app_name = ""
                self._app_caption = ""

    def handle_data(self, data):
        if self._in_timestamp:
            # Extract date like "May 23, 2024  7:36:52 AM"
            ts_match = re.search(
                r"(\w+ \d{1,2}, \d{4})\s+(\d{1,2}:\d{2}:\d{2}\s*[AP]M)", data
            )
            if ts_match:
                raw = f"{ts_match.group(1)} {ts_match.group(2)}"
                for fmt in ("%B %d, %Y %I:%M:%S %p", "%b %d, %Y %I:%M:%S %p"):
                    try:
                        dt = datetime.strptime(raw, fmt)
                        self._current["timestamp"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                        break
                    except ValueError:
                        continue
                self._in_timestamp = False

        if self._in_sender:
            sender = data.strip()
            if sender:
                self._current["sender"] = normalize_sender(sender)
            self._in_sender = False

        if self._in_app_header_name:
            text = data.strip()
            if text:
                self._app_name = (self._app_name + " " + text).strip()

        if self._in_app_footer_caption:
            text = data.strip()
            if text:
                self._app_caption = (self._app_caption + " " + text).strip()

        if self._in_bubble:
            text = data.strip()
            if text:
                if "message" in self._current:
                    self._current["message"] += "\n" + text
                else:
                    self._current["message"] = text
                self._in_bubble = False


def _get_contact_channel(messages: list[dict], contact_id: str) -> str:
    """Determine the attribution channel for received messages in a thread.

    Rules from the architecture blueprint:
      - Email-based contact → imessage (Apple ID routing)
      - Phone number → inferred from outgoing bubble pattern:
          100% imessage outgoing → imessage
          100% sms outgoing      → sms
          mixed / no outgoing    → unknown
    """
    if contact_id in CONTACT_CHANNEL_OVERRIDE:
        return CONTACT_CHANNEL_OVERRIDE[contact_id]

    if "@" in contact_id:
        return "imessage"

    # Phone number: check outgoing message pattern
    outgoing = [
        m["channel"] for m in messages if m.get("channel") in ("imessage", "sms")
    ]
    if not outgoing:
        return "unknown"
    if all(ch == "imessage" for ch in outgoing):
        return "imessage"
    if all(ch == "sms" for ch in outgoing):
        return "sms"
    return "unknown"


def _get_primary_contact(stem: str) -> str:
    """Extract primary contact identifier from an HTML filename stem.

    For group chats (comma-separated), returns the first non-.DS_Store
    identifier that contains the contact filter string.
    """
    parts = [p.strip() for p in stem.split(",") if p.strip()]
    return parts[0] if parts else stem


def _attribute_received_channels(messages: list[dict], contact_id: str) -> list[dict]:
    """Apply attributed channel to received messages that lack a direct signal."""
    contact_channel = _get_contact_channel(messages, contact_id)
    for msg in messages:
        if "channel" not in msg:
            msg["channel"] = contact_channel
    return messages


def parse_sms_html(filepath: str) -> list[dict]:
    """Parse a single SMS HTML export file into message dicts.

    Post-processes received messages by applying attribution rules
    based on the contact identifier derived from the filename.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    parser = SMSHTMLParser()
    parser.feed(content)

    stem = Path(filepath).stem
    contact_id = _get_primary_contact(stem)
    # Detect group chat from comma-separated filename; store canonical
    # participant names for transcript labeling.
    participants = [normalize_sender(p.strip()) for p in stem.split(",") if p.strip()]
    is_group = len(participants) > 1
    for msg in parser.messages:
        msg["_source_file"] = stem
        if is_group:
            msg["group_chat"] = ", ".join(participants)

    _attribute_received_channels(parser.messages, contact_id)

    return parser.messages


def parse_sms_html_dir(html_dir: str, contact_filter: str = None) -> list[dict]:
    """Parse all HTML files in a directory into sorted message dicts."""
    all_msgs = []
    html_dir = Path(html_dir)

    if not html_dir.exists():
        print(f"  [WARN] HTML directory not found: {html_dir}", file=sys.stderr)
        return all_msgs

    for f in sorted(html_dir.glob("*.html")):
        if contact_filter and contact_filter not in f.stem:
            continue
        # Skip group chats with other contacts (e.g. files with commas)
        if (
            "," in f.stem
            and contact_filter
            and not all(c in f.stem for c in contact_filter.split(","))
        ):
            continue
        print(f"  Parsing: {f.name}", file=sys.stderr)
        msgs = parse_sms_html(str(f))
        all_msgs.extend(msgs)

    # Sort by timestamp
    all_msgs.sort(key=lambda m: m.get("timestamp", ""))
    return all_msgs


# ---------------------------------------------------------------------------
# 2. Gmail .md Export Parser
# ---------------------------------------------------------------------------


def parse_gmail_md(
    filepath: str, our_email: str = "dcbyers13@gmail.com", known_contacts: dict = None
) -> list[dict]:
    """
    Parse a Gmail .md export file into message dicts using line-by-line
    parsing (more robust than page-break splitting).

    Format:
        Line 2: Gmail - Subject URL
        Line 3: Sender Name <email>
        Line 4: Subject
        Line 5: "N messages"
        Then each message:
            Sender Name <email> Day, Mon DD, YYYY at HH:MM AM/PM
            To: Recipient <email>
            message body (may span multiple lines)
            N of M ...
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if known_contacts is None:
        known_contacts = {}

    messages = []
    lines = content.split("\n")

    # Header pattern: ends with day-of-week, date, and time
    header_pattern = re.compile(
        r"^(.+?)\s*<([^>]+)>\s+"
        r"(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+)?"
        r"(\w+)\s+(\d{1,2}),\s+(\d{4})\s+at\s+(\d{1,2}:\d{2})\s*(AM|PM)"
    )

    i = 0
    while i < len(lines):
        line = lines[i]
        header_match = header_pattern.match(line)

        if header_match:
            sender_name = header_match.group(1).strip()
            sender_email = header_match.group(2).strip()
            month = header_match.group(3)
            day = header_match.group(4)
            year = header_match.group(5)
            time_str = header_match.group(6)
            ampm = header_match.group(7)

            # Parse datetime
            dt_str = f"{month} {day}, {year} {time_str} {ampm}"
            try:
                dt = datetime.strptime(dt_str, "%B %d, %Y %I:%M %p")
            except ValueError:
                try:
                    dt = datetime.strptime(dt_str, "%b %d, %Y %I:%M %p")
                except ValueError:
                    i += 1
                    continue

            # Collect body: skip "To:" line, then collect until next header
            # or page break or end
            i += 1
            body_lines = []
            while i < len(lines):
                next_line = lines[i].strip()
                # Stop at next header
                if header_pattern.match(lines[i]):
                    break
                # Stop at page breaks
                if next_line.startswith("--- Page Break"):
                    i += 1
                    break
                # Skip "To:" lines and quoted text markers and N of M lines
                if (
                    next_line.startswith("To:")
                    or next_line.startswith("[Quoted text hidden]")
                    or re.match(r"^\d+\s+of\s+\d+", next_line)
                    or next_line == ""
                ):
                    i += 1
                    continue
                # Skip quoted text (lines starting with >)
                if next_line.startswith(">"):
                    i += 1
                    continue
                body_lines.append(lines[i])
                i += 1

            body = " ".join(line.strip() for line in body_lines if line.strip())
            body = re.sub(r"\s+", " ", body).strip()

            if not body:
                continue

            # Normalize sender
            if sender_email.lower() == our_email.lower():
                sender = "Me"
            else:
                sender = known_contacts.get(sender_email, sender_name)

            messages.append(
                {
                    "timestamp": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "sender": sender,
                    "message": body,
                    "_source_file": Path(filepath).stem,
                }
            )
        else:
            i += 1

    return messages


def parse_gmail_dir(
    gmail_dir: str,
    our_email: str = "dcbyers13@gmail.com",
    known_contacts: dict = None,
    contact_filter: str = None,
) -> list[dict]:
    """Parse all Gmail .md files in a directory, filtering by contact."""
    all_msgs = []
    gmail_dir = Path(gmail_dir)

    if not gmail_dir.exists():
        print(f"  [WARN] Gmail directory not found: {gmail_dir}", file=sys.stderr)
        return all_msgs

    for f in sorted(gmail_dir.glob("*.md")):
        msgs = parse_gmail_md(str(f), our_email, known_contacts)
        for msg in msgs:
            msg["channel"] = "gmail_md"
        if contact_filter:
            contact_lower = contact_filter.lower()
            msgs = [
                m
                for m in msgs
                if contact_lower in m.get("sender", "").lower()
                or contact_lower in m.get("message", "").lower()
            ]
        all_msgs.extend(msgs)

    all_msgs.sort(key=lambda m: m.get("timestamp", ""))
    return all_msgs


# ---------------------------------------------------------------------------
# 3a. Mbox Email Parser (Gmail Takeout mbox format)
# ---------------------------------------------------------------------------

# Our own email addresses — always map to "Me"
OUR_EMAILS = {"dcbyers13@gmail.com", "baddod13@gmail.com"}
# Default contact mapping for known addresses
KNOWN_CONTACT_EMAILS = {
    "violettesunshine716@gmail.com": "Violette Donatello",
    "violette@iyou.me": "Violette Donatello",
    "violettemichele@icloud.com": "Violette Donatello",
}


def _decode_header_value(val: str) -> str:
    """Decode an email header value, handling encoded-words like =?UTF-8?Q?...?=."""
    if not val:
        return ""
    decoded_parts = email.header.decode_header(val)
    result = []
    for part, encoding in decoded_parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(encoding or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                result.append(part.decode("utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result).strip()


def _get_text_body(msg: email.message.Message) -> str:
    """Extract text/plain content from an email message tree."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        return payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        return payload.decode("utf-8", errors="replace")
        # Fallback: try text/html
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        text = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        text = payload.decode("utf-8", errors="replace")
                    # Strip HTML tags
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()
                    return text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                return payload.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                return payload.decode("utf-8", errors="replace")
    return ""


def _normalize_sender(from_header: str) -> tuple[str, str]:
    """Extract (email, display_name) from a From header."""
    if not from_header:
        return "", ""
    addr = email.utils.parseaddr(from_header)
    return addr[1].lower().strip(), addr[0].strip()


def parse_mbox(
    filepath: str,
    our_emails: set = None,
    known_contacts: dict = None,
    contact_filter: str = None,
) -> list[dict]:
    """
    Parse an mbox file (Gmail Takeout format) into THREAD_MASTER entries.

    Handles multipart/alternative, quoted-printable, base64, and
    encoded-word headers. Sender mapping:
        - Our own emails → "Me"
        - Known contacts → display name from contact map
        - Others → display name from From header

    When contact_filter is set, only messages from "Me" or the contact
    are kept (drops system notifications, unrelated third parties).
    """
    if our_emails is None:
        our_emails = OUR_EMAILS
    if known_contacts is None:
        known_contacts = KNOWN_CONTACT_EMAILS

    filepath = Path(filepath)
    if not filepath.exists():
        print(f"  [WARN] Mbox file not found: {filepath}", file=sys.stderr)
        return []

    raw = filepath.read_bytes()
    text = raw.decode("utf-8", errors="replace")

    messages = []
    # Split by mbox From_ line (at start of line)
    raw_msgs = re.split(r"(?m)^From\s", text)

    for i, raw_msg in enumerate(raw_msgs):
        if not raw_msg.strip():
            continue

        # Restore the "From " prefix (except for the first split element
        # which is a preamble)
        if i > 0:
            raw_msg = "From " + raw_msg

        try:
            msg = email.message_from_string(raw_msg, policy=email.policy.compat32)
        except Exception:
            continue

        # --- Parse headers ---
        date_str = msg.get("Date", "")
        from_hdr = msg.get("From", "")
        subject = _decode_header_value(msg.get("Subject", ""))
        msg_id = msg.get("Message-ID", "")

        # Parse timestamp
        try:
            dt = parsedate_to_datetime(date_str)
            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue

        # Parse sender
        sender_email, sender_name = _normalize_sender(from_hdr)
        if sender_email in our_emails:
            sender = "Me"
        elif sender_email in known_contacts:
            sender = known_contacts[sender_email]
        elif sender_name:
            sender = sender_name
        else:
            sender = sender_email

        # Contact filter: only keep "Me" and the contact person
        if contact_filter:
            contact_lower = contact_filter.lower()
            if sender != "Me" and contact_lower not in sender.lower():
                continue

        # Extract body text
        body = _get_text_body(msg)

        # Clean up body
        if body:
            # Remove excessive blank lines
            body = re.sub(r"\n{3,}", "\n\n", body)
            # Strip quoted text (lines starting with >)
            body = "\n".join(
                line for line in body.split("\n") if not line.startswith(">")
            )
            body = body.strip()

        if not body:
            continue

        entry = {
            "timestamp": timestamp,
            "sender": sender,
            "message": body,
            "channel": "gmail_mbox",
        }
        if subject:
            entry["subject"] = subject
        if msg_id:
            entry["_msg_id"] = msg_id.strip("<>")

        messages.append(entry)

    messages.sort(key=lambda m: m.get("timestamp", ""))
    return messages


# ---------------------------------------------------------------------------
# 3b. Google Voice Text HTML Parser (Google Takeout format)
# ---------------------------------------------------------------------------

# Phone number → display name mapping for Google Voice messages
GV_CONTACT_MAP = {
    "+18153221013": "Me",  # David's GV number 815-322-1013
    "+18153242175": "Violette Donatello",  # Violette's number 815-324-2175
    "+16306186165": "Violette Donatello",  # Also Violette (alternate/old number)
    "+18152068357": "Violette Donatello",  # Violette's "Violette NEW" number in GV
}

GV_TEXT_MARKER = " - Text - "


def parse_gv_text_html(filepath: str) -> list[dict]:
    """
    Parse a single Google Voice Text HTML file from Google Takeout.

    HTML structure:
        <div class="hChatLog hfeed">
          <div class="message">
            <abbr class="dt" title="ISO_TIMESTAMP">Human Date</abbr>:
            <cite class="sender vcard">
              <a class="tel" href="tel:+NNNN">
                <span class="fn">Contact Name</span>
              </a>
            </cite>:
            <q>message body</q>
          </div>
          ...
        </div>
    """
    if not HAS_BS4:
        print(
            "  [ERROR] BeautifulSoup4 (bs4) required for --gv-dir. "
            "Install with: pip install beautifulsoup4",
            file=sys.stderr,
        )
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    messages = []
    for msg_div in soup.find_all("div", class_="message"):
        # Timestamp
        dt_abbr = msg_div.find("abbr", class_="dt")
        if not dt_abbr or not dt_abbr.get("title"):
            continue
        try:
            ts = dt_abbr["title"]
            dt = datetime.fromisoformat(ts)
            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue

        # Sender: extract phone from tel: link, then map to display name
        cite = msg_div.find("cite", class_="sender")
        if not cite:
            continue
        tel_link = cite.find("a", class_="tel")
        if not tel_link:
            continue
        phone = tel_link.get("href", "").replace("tel:", "")
        sender = GV_CONTACT_MAP.get(phone, phone)

        # Message text
        q_tag = msg_div.find("q")
        text = q_tag.get_text(" ", strip=True) if q_tag else ""

        # Look for inline image attachments
        img_tag = msg_div.find("img")
        attachment = ""
        if img_tag and img_tag.get("src"):
            src = img_tag["src"].strip()
            # Only include meaningful attachment references (jpg/png/gif)
            if src.lower().endswith((".jpg", ".jpeg", ".png", ".gif")):
                attachment = src

        entry = {
            "timestamp": timestamp,
            "sender": sender,
            "message": text,
            "channel": "google_voice",
        }
        if attachment:
            entry["attachment"] = attachment

        messages.append(entry)

    return messages


def parse_gv_text_dir(gv_dir: str, contact_name: str = None) -> list[dict]:
    """
    Parse all Google Voice Text HTML files in a directory.

    Only processes files containing GV_TEXT_MARKER in their name
    (skips call records like Missed/Placed/Received).
    When contact_name is given, only processes files containing that name.
    """
    all_msgs = []
    gv_dir = Path(gv_dir)

    if not gv_dir.exists():
        print(f"  [WARN] GV directory not found: {gv_dir}", file=sys.stderr)
        return all_msgs

    for f in sorted(gv_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".html", ".htm"):
            continue
        if GV_TEXT_MARKER not in f.name:
            continue
        if contact_name and contact_name.lower() not in f.name.lower():
            continue

        print(f"  Parsing GV text: {f.name}", file=sys.stderr)
        try:
            msgs = parse_gv_text_html(str(f))
            all_msgs.extend(msgs)
        except Exception as e:
            print(f"  [WARN] Error parsing {f.name}: {e}", file=sys.stderr)

    all_msgs.sort(key=lambda m: m.get("timestamp", ""))
    return all_msgs


# ---------------------------------------------------------------------------
# 3c. Merge & Deduplicate (Strict Channel Hierarchy)
# ---------------------------------------------------------------------------


def merge_and_deduplicate(existing: list[dict], new: list[dict]) -> list[dict]:
    """
    Merge two message lists with strict channel hierarchy overwrite.

    Dedup key: timestamp + sender + message (first 200 chars) + attachment.
    On collision, the channel with higher priority wins:
      imessage > sms > google_voice > gmail_mbox > gmail_md > unknown
    No channel merging ever occurs — single-value strings only.
    """
    seen = {}
    merged = []

    for msg in existing + new:
        ts = msg.get("timestamp", "")
        sender = msg.get("sender", "")
        message = msg.get("message", "")[:200]
        att = msg.get("attachment", "")
        ch = msg.get("channel", "unknown")
        ch_priority = CHANNEL_PRIORITY.get(ch, 99)
        key = (ts, sender, message, att)

        if key in seen:
            idx = seen[key]
            existing_ch = merged[idx].get("channel", "unknown")
            existing_priority = CHANNEL_PRIORITY.get(existing_ch, 99)
            if ch_priority < existing_priority:
                merged[idx]["channel"] = ch
        else:
            seen[key] = len(merged)
            clean = {k: v for k, v in msg.items() if not k.startswith("_")}
            merged.append(clean)

    merged.sort(key=lambda m: m.get("timestamp", ""))
    return merged


# ---------------------------------------------------------------------------
# 4. Contact Configurations
# ---------------------------------------------------------------------------

CONTACT_CONFIGS = {
    "violette": {
        "gmail_contacts": {
            "violettesunshine716@gmail.com": "Violette Donatello",
            "violette@iyou.me": "Violette Donatello",
            "violettemichele@icloud.com": "Violette Donatello",
        },
        "gmail_filter": "violette",
        "output_name": "THREAD_MASTER_Violette.json",
    },
    "pauletta": {
        "gmail_contacts": {
            "paulettadonatello@gmail.com": "Pauletta Donatello",
        },
        "gmail_filter": "pauletta",
        "output_name": "THREAD_MASTER_Pauletta.json",
    },
}


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Build THREAD_MASTER JSON from SMS HTML exports + Gmail .md files"
    )
    parser.add_argument(
        "--contact",
        required=True,
        choices=list(CONTACT_CONFIGS.keys()),
        help="Contact to build thread master for",
    )
    parser.add_argument(
        "--html-dir", default=None, help="Directory containing SMS HTML export files"
    )
    parser.add_argument(
        "--gmail-dir", default=None, help="Directory containing Gmail .md export files"
    )
    parser.add_argument(
        "--existing", default=None, help="Existing JSON file to merge with"
    )
    parser.add_argument("--output", required=True, help="Output JSON file path")
    parser.add_argument(
        "--mbox",
        action="append",
        default=[],
        help="Mbox file(s) to parse (may be repeated)",
    )
    parser.add_argument(
        "--gv-dir",
        default=None,
        help="Directory containing Google Voice Text HTML files (Google Takeout)",
    )
    parser.add_argument(
        "--dedup-only",
        action="store_true",
        help="Only deduplicate existing JSON, don't parse sources",
    )

    args = parser.parse_args()
    config = CONTACT_CONFIGS[args.contact]

    all_messages = []

    # --- Source 1: Existing JSON (seed data) ---
    if args.existing and os.path.exists(args.existing):
        print(f"Loading existing: {args.existing}", file=sys.stderr)
        with open(args.existing, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
        # Seed data has no channel signal — mark as "unknown".
        # Channel healing loop (timestamp+message match against HTML/GV
        # sources) will upgrade these during dedup.
        for msg in existing_data:
            if "channel" not in msg:
                msg["channel"] = "unknown"
            elif "," in msg["channel"]:
                # Clean up any remaining merged strings from prior runs
                msg["channel"] = "unknown"
        print(f"  -> {len(existing_data)} entries", file=sys.stderr)
        all_messages.extend(existing_data)

    if args.dedup_only and args.existing:
        all_messages.sort(key=lambda m: m.get("timestamp", ""))
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(all_messages, f, indent=2, ensure_ascii=False)
        print(f"Deduplicated existing JSON -> {args.output}", file=sys.stderr)
        return

    # --- Source 2: HTML SMS exports ---
    if args.html_dir:
        print(f"Parsing SMS HTML: {args.html_dir}", file=sys.stderr)
        html_msgs = parse_sms_html_dir(args.html_dir)
        print(f"  -> {len(html_msgs)} entries", file=sys.stderr)
        all_messages.extend(html_msgs)

    # --- Source 3: Gmail .md exports ---
    if args.gmail_dir:
        print(f"Parsing Gmail MD: {args.gmail_dir}", file=sys.stderr)
        gmail_msgs = parse_gmail_dir(
            args.gmail_dir,
            known_contacts=config["gmail_contacts"],
            contact_filter=config["gmail_filter"],
        )
        print(f"  -> {len(gmail_msgs)} entries", file=sys.stderr)
        all_messages.extend(gmail_msgs)

    # --- Source 4: Mbox files ---
    if args.mbox:
        for mbox_file in args.mbox:
            print(f"Parsing mbox: {mbox_file}", file=sys.stderr)
            mbox_msgs = parse_mbox(
                mbox_file,
                contact_filter=config.get("gmail_filter"),
            )
            print(f"  -> {len(mbox_msgs)} entries", file=sys.stderr)
            all_messages.extend(mbox_msgs)

    # --- Source 5: Google Voice Text HTML ---
    if args.gv_dir:
        print(f"Parsing Google Voice Text: {args.gv_dir}", file=sys.stderr)
        gv_msgs = parse_gv_text_dir(
            args.gv_dir,
            contact_name=args.contact,
        )
        print(f"  -> {len(gv_msgs)} entries", file=sys.stderr)
        all_messages.extend(gv_msgs)

    # --- Normalize sender labels for cross-source dedup matching ---
    # Seed data uses raw addresses (violettemichele@icloud.com), HTML uses
    # resolved names (Violette Donatello). Normalize so channel healing works.
    # raw_sender is kept as a public field (no _ prefix) to survive dedup.
    for msg in all_messages:
        s = msg.get("sender", "")
        normalized = normalize_sender(s)
        if normalized != s:
            msg["raw_sender"] = s
            msg["sender"] = normalized

    # --- Merge & Deduplicate (Strict Channel Hierarchy) ---
    if args.existing or (args.html_dir or args.gmail_dir or args.mbox or args.gv_dir):
        print(
            f"Merging & deduplicating with strict channel hierarchy...", file=sys.stderr
        )
        # Dedup key: timestamp + sender + message (first 200 chars) + attachment.
        # On collision, higher-priority channel overwrites lower (never merged).
        # This enables channel healing: seed "unknown" entries matched by
        # timestamp+text against HTML/GV entries get upgraded automatically.
        seen = {}
        deduped = []
        for msg in all_messages:
            ts = msg.get("timestamp", "")
            sender = msg.get("sender", "")
            message = msg.get("message", "")[:200]
            att = msg.get("attachment", "")
            ch = msg.get("channel", "unknown")
            ch_priority = CHANNEL_PRIORITY.get(ch, 99)
            key = (ts, sender, message, att)

            if key in seen:
                idx = seen[key]
                existing_ch = deduped[idx].get("channel", "unknown")
                existing_priority = CHANNEL_PRIORITY.get(existing_ch, 99)
                if ch_priority < existing_priority:
                    deduped[idx]["channel"] = ch
            else:
                seen[key] = len(deduped)
                clean = {k: v for k, v in msg.items() if not k.startswith("_")}
                deduped.append(clean)

        deduped.sort(key=lambda m: m.get("timestamp", ""))
        all_messages = deduped

    # --- Write Output ---
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_messages, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(all_messages)} entries to {args.output}", file=sys.stderr)

    # Summary stats
    senders = {}
    for msg in all_messages:
        s = msg.get("sender", "Unknown")
        senders[s] = senders.get(s, 0) + 1

    print(f"\nSender breakdown:", file=sys.stderr)
    for s, c in sorted(senders.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}", file=sys.stderr)

    # Date range
    if all_messages:
        print(
            f"\nDate range: {all_messages[0]['timestamp']} to {all_messages[-1]['timestamp']}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
