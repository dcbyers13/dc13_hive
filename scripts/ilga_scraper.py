#!/usr/bin/env -S uv run --script

# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "beautifulsoup4",
#     "certifi",
#     "markdown",
# ]
# ///

"""
ILGA.gov Illinois Compiled Statutes Scraper

Downloads sections of the Illinois Compiled Statutes (ILCS) from ILGA.gov
and saves them as formatted Markdown files in LAW_LIBRARY/ and optionally
GUIDING_LIGHTS/.

Usage:
    uv run ilga_scraper.py <chapter> <act> <section> [--guiding-lights]
    uv run ilga_scraper.py list <chapter> <act>
    uv run ilga_scraper.py batch <config.json>

Examples:
    uv run ilga_scraper.py 750 5 602.7
    uv run ilga_scraper.py 750 5 602.7 --guiding-lights
    uv run ilga_scraper.py list 750 5
    uv run ilga_scraper.py list 750 30

Uses ILGA.gov FTP directory listing for section discovery (no blocking).
Each chapter/act has an FTP directory from which we extract the document
code and list all available sections.
"""

from datetime import date
import re
import sys
import json
import html
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
LAW_LIBRARY = Path(__file__).resolve().parent.parent.parent / "LAW_LIBRARY"
GUIDING_LIGHTS = Path(__file__).resolve().parent.parent.parent / "GUIDING_LIGHTS"
FTP_BASE = "https://www.ilga.gov/ftp/ILCS"
DOCUMENTS_BASE = "https://www.ilga.gov/Documents/legislation/ilcs/documents"

# Popular section titles for display purposes
SECTION_TITLES = {
    # 750 ILCS 5 - IMDMA
    "602.5": "Allocation of Parental Responsibilities: Decision-Making",
    "602.6": "Relocation",
    "602.7": "Allocation of Parental Responsibilities: Parenting Time",
    "602.8": "Modification of Allocation Judgments",
    "602.9": "Restrictions on Parenting Time",
    "602.10": "Parenting Plan",
    "603.10": "Enforcement of Parenting Time",
    "609.2": "Relocation Notice Requirements",
    "610": "Modification of Orders",
    "611": "Attorney's Fees",
    "505": "Child Support",
    "513": "Educational Expenses",
    # 750 ILCS 30 - Parentage Act
    "101": "Short Title",
    "102": "Definitions",
    "801": "Parentage Order",
    "802": "Allocation of Parental Responsibilities",
    "803": "Parenting Time",
    "804": "Child Support",
    "805": "Modification",
    # 750 ILCS 36 - UCCJEA
    "201": "Jurisdiction",
    "202": "Exclusive Continuing Jurisdiction",
    "203": "Jurisdiction to Modify",
    "204": "Temporary Emergency Jurisdiction",
    "205": "Notice",
    "206": "Simultaneous Proceedings",
    # 750 ILCS 60 - IDVA
    "101": "Short Title",
    "102": "Definitions",
    "103": "Commencement of Action",
    "201": "Orders of Protection",
    "202": "Emergency Orders",
    "203": "Plenary Orders",
    "204": "Interim Orders",
    "214": "Remedies",
    "220": "Law Enforcement Duties",
    "222": "Enforcement",
    # 750 ILCS 46 - Hague Convention
    "101": "Short Title",
    "102": "Definitions",
    "301": "Judicial Enforcement",
    "302": "Measures to Locate Child",
    "303": "Return Order",
    "304": "Rights of Petitioner",
    # 750 ILCS 47 - Child Abduction Prevention
    "101": "Short Title",
    "102": "Definitions",
    "201": "Factors",
    "202": "Provisions in Orders",
    "203": "Warrant for Taking Physical Custody",
    "301": "Cooperation with Law Enforcement",
    "302": "Reporting Requirements",
    # 735 ILCS 5 - Code of Civil Procedure
    "1-109": "Verification by Certification",
    "2-608": "Counterclaims",
    "2-1402": "Contempt Sanctions",
    # 755 ILCS 5 - Probate Act
    "11-5.4": "Short-Term Guardian",
    "11-13.2": "Duties of Short-Term Guardian",
}


def ftp_list_url(chapter: int, act: int) -> str:
    """Build FTP directory URL for a chapter/act."""
    return f"{FTP_BASE}/Ch%20{chapter:04d}/Act%20{act:04d}/"


def ftp_file_url(chapter: int, act: int, filename: str) -> str:
    """Build FTP file URL for a specific file."""
    return f"{FTP_BASE}/Ch%20{chapter:04d}/Act%20{act:04d}/{filename}"


def doc_url(code: str, section: str) -> str:
    """Build the ILGA documents URL for a code/section."""
    return f"{DOCUMENTS_BASE}/{code}K{section}.htm"


def fetch_url(url: str, timeout: int = 15) -> str:
    import certifi
    import ssl
    context = ssl.create_default_context(cafile=certifi.where())
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout, context=context) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        raise
    except URLError as e:
        raise


def parse_ftp_listing(raw: str) -> dict | None:
    """Parse FTP directory listing HTML to extract document code and sections.

    Returns dict with 'code', 'sections' (list of section numbers).
    Returns None if no section files found.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, "html.parser")

    code = None
    sections = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        # Match files like {code}K{section}.html (handles dashes: 1-109, dots: 602.5, letters: 11a-1)
        m = re.search(r"/(\d{9})K([\w.-]+)\.html$", href)
        if m:
            file_code = m.group(1)
            section = m.group(2)
            if code is None:
                code = file_code
            sections.append(section)

    if not sections:
        return None
    return {"code": code, "sections": sorted(set(sections), key=_section_sort_key)}


def _section_sort_key(s: str) -> list:
    """Sort sections naturally: 101 < 201 < 602.5 < 602.10 < 801."""
    parts = re.split(r"[.\s-]", s)
    return [float("inf") if not x.isdigit() else int(x) for x in parts]


def clean_html_to_text(raw: str) -> str:
    """Strip HTML tags, decode entities, normalize whitespace."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<h(\d)[^>]*>", r"\n\n### \n", text, flags=re.IGNORECASE)
    text = re.sub(r"</h\d>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def extract_statute_text(raw: str) -> str:
    """Extract statute text from HTML page body."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, "html.parser")
    body = soup.find("body") or soup
    text = body.get_text(separator="\n")

    lines = []
    skip_phrases = [
        "Illinois General Assembly", "Home | Legislation & Laws",
        "Senate | House", "My Legislation", "Site Map",
        "Bills & Resolutions", "Compiled Statutes", "Public Acts",
        "ILCS Listing", "Search ILCS", "Printer Friendly", "Legislation & Laws",
    ]
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if any(p in line for p in skip_phrases):
            continue
        if re.match(r"^[A-Z /|]{3,60}$", line) and len(line) < 60:
            continue
        lines.append(line)
    return "\n\n".join(lines)


def parse_statute_metadata(raw: str) -> dict:
    """Extract metadata from statute page."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, "html.parser")
    title_text = soup.title.string if soup.title else ""

    statute_ref = ""
    m = re.search(r"\(?(\d+ ILCS \d+/\d+[.\d]*)\)?", title_text)
    if m:
        statute_ref = m.group(1)

    section_title = ""
    m = re.search(r"Sec\.\s*[\d.\-a-zA-Z]+\.?\s*([^<]+)", raw[:5000])
    if m:
        section_title = html.unescape(m.group(1).strip())

    source = ""
    m = re.search(r"\(Source:\s*(.*?)\)", raw)
    if m:
        source = m.group(1).strip()

    return {"statute_ref": statute_ref, "section_title": section_title, "source": source}


def discover_code(chapter: int, act: int, verbose: bool = True) -> str | None:
    """Discover the document code for a chapter/act via FTP listing.

    Returns the 9-digit code, or None if the FTP directory doesn't exist.
    """
    url = ftp_list_url(chapter, act)
    try:
        raw = fetch_url(url, timeout=10)
    except (HTTPError, URLError):
        if verbose:
            print(f"  FTP directory not found: {url}", file=sys.stderr)
        return None

    parsed = parse_ftp_listing(raw)
    if parsed is None:
        if verbose:
            print(f"  No section files found in FTP listing", file=sys.stderr)
        return None
    return parsed["code"]


def list_sections(chapter: int, act: int, verbose: bool = True) -> list[dict]:
    """List all sections for a chapter/act via FTP directory listing.

    Returns a list of dicts with 'number' and 'title' keys.
    """
    url = ftp_list_url(chapter, act)
    if verbose:
        print(f"Listing sections for {chapter} ILCS {act}...")
        print(f"  {url}")

    try:
        raw = fetch_url(url, timeout=10)
    except (HTTPError, URLError) as e:
        if verbose:
            print(f"  FTP directory not found: {e}", file=sys.stderr)
        return []

    parsed = parse_ftp_listing(raw)
    if parsed is None:
        if verbose:
            print(f"  No section files found", file=sys.stderr)
        return []

    if verbose:
        print(f"  Document code: {parsed['code']}")
        print(f"  Found {len(parsed['sections'])} sections:")

    sections = []
    for sec_num in parsed["sections"]:
        title = SECTION_TITLES.get(sec_num, "")
        sections.append({"number": sec_num, "title": title})
        if verbose:
            t = f" — {title}" if title else ""
            print(f"    {chapter} ILCS {act}/{sec_num}{t}")

    return sections


def download_statute(chapter: int, act: int, section: str,
                     guiding_lights: bool = False,
                     verbose: bool = True) -> Path | None:
    """Download a statute section and save to LAW_LIBRARY.

    Discovers the document code via FTP, then downloads via FTP.
    Returns the path to the saved file, or None on failure.
    """
    ref = f"{chapter} ILCS {act}/{section}"

    code = discover_code(chapter, act, verbose=False)
    if code is None:
        if verbose:
            print(f"  Cannot discover document code for {chapter} ILCS {act}", file=sys.stderr)
        return None

    # Try FTP URL first (no blocking), fall back to documents URL
    ftp_file = f"{code}K{section}.html"
    ftp_url = ftp_file_url(chapter, act, ftp_file)
    doc_url_val = doc_url(code, section)

    if verbose:
        desc = SECTION_TITLES.get(section, "")
        desc_str = f" — {desc}" if desc else ""
        print(f"Fetching {ref}{desc_str}")

    raw = None
    used_url = None
    try:
        raw = fetch_url(ftp_url, timeout=10)
        used_url = ftp_url
    except (HTTPError, URLError):
        try:
            raw = fetch_url(doc_url_val, timeout=10)
            used_url = doc_url_val
        except (HTTPError, URLError):
            if verbose:
                print(f"  Failed: {ref}", file=sys.stderr)
            return None

    if verbose:
        print(f"  Downloaded {len(raw)} bytes")

    # Parse metadata
    metadata = parse_statute_metadata(raw)
    statute_ref = metadata.get("statute_ref") or ref
    section_title = metadata.get("section_title") or SECTION_TITLES.get(section, "")
    source = metadata.get("source") or ""

    # Extract text
    statute_text = extract_statute_text(raw)
    if len(statute_text) < 100:
        statute_text = clean_html_to_text(raw)

    # Build markdown
    title_line = f"# {statute_ref}"
    if section_title:
        title_line += f" — {section_title}"

    source_footer = f"\n\n*Source: {source}*" if source else ""

    md_content = f"""{title_line}

**Source:** {used_url}
**Retrieved:** {date.today().isoformat()}

---

{statute_text}{source_footer}
"""

    # Build filename
    title_part = ""
    t = SECTION_TITLES.get(section, "")
    if t:
        title_part = "_" + re.sub(r"[^a-zA-Z0-9]+", "_", t).strip("_").upper()

    filename = f"{chapter}_ILCS_{act}_{section}{title_part}.md"

    # Save to LAW_LIBRARY
    lib_path = LAW_LIBRARY / filename
    lib_path.parent.mkdir(parents=True, exist_ok=True)
    lib_path.write_text(md_content, encoding="utf-8")

    if verbose:
        print(f"  Saved to LAW_LIBRARY/{filename}")

    if guiding_lights:
        gl_path = GUIDING_LIGHTS / filename
        gl_path.write_text(md_content, encoding="utf-8")
        if verbose:
            print(f"  Also saved to GUIDING_LIGHTS/{filename}")

    return lib_path


def batch_download(config_path: str | Path):
    """Download multiple statutes from a JSON config file.

    Config format:
        {"statutes": [
            {"chapter": 750, "act": 5, "section": "602.7", "guiding_lights": true},
        ]}
    """
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    results = {"success": [], "failed": []}

    for entry in config.get("statutes", []):
        try:
            path = download_statute(
                chapter=entry["chapter"],
                act=entry["act"],
                section=entry["section"],
                guiding_lights=entry.get("guiding_lights", False),
            )
            if path:
                results["success"].append(entry)
            else:
                results["failed"].append(entry)
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            results["failed"].append(entry)

    print(f"\nBatch complete: {len(results['success'])} succeeded, {len(results['failed'])} failed")
    return results


def generate_config_template():
    print(json.dumps({
        "statutes": [
            {"chapter": 750, "act": 5, "section": "602.5", "guiding_lights": False},
            {"chapter": 750, "act": 5, "section": "602.7", "guiding_lights": True},
            {"chapter": 750, "act": 5, "section": "602.10", "guiding_lights": False},
            {"chapter": 750, "act": 5, "section": "603.10", "guiding_lights": False},
            {"chapter": 750, "act": 5, "section": "505", "guiding_lights": False},
            {"chapter": 750, "act": 30, "section": "801", "guiding_lights": False},
        ]
    }, indent=2))


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print(__doc__)
        print("\nCommands:")
        print("  uv run ilga_scraper.py <chapter> <act> <section> [--guiding-lights]")
        print("  uv run ilga_scraper.py list <chapter> <act>")
        print("  uv run ilga_scraper.py batch <config.json>")
        print("  uv run ilga_scraper.py template")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "template":
        generate_config_template()
        return

    if cmd == "list":
        if len(sys.argv) < 4:
            print("Usage: uv run ilga_scraper.py list <chapter> <act>", file=sys.stderr)
            sys.exit(1)
        list_sections(int(sys.argv[2]), int(sys.argv[3]))
        return

    if cmd == "batch":
        if len(sys.argv) < 3:
            print("Usage: uv run ilga_scraper.py batch <config.json>", file=sys.stderr)
            sys.exit(1)
        batch_download(sys.argv[2])
        return

    # Default: download individual statute
    try:
        chapter = int(sys.argv[1])
        act = int(sys.argv[2])
        section = sys.argv[3]
    except (IndexError, ValueError):
        print("Usage: uv run ilga_scraper.py <chapter> <act> <section> [--guiding-lights]", file=sys.stderr)
        sys.exit(1)

    guiding_lights = "--guiding-lights" in sys.argv

    path = download_statute(chapter, act, section, guiding_lights=guiding_lights)
    if path:
        print(f"\nDone. File saved.")
    else:
        print(f"\nFailed to download {chapter} ILCS {act}/{section}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
