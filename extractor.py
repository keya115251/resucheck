"""
extractor.py
------------
Step 1: Extract raw text and layout metadata from a PDF.

Handles both single-column and two-column layouts.
Two-column pages are detected automatically: the left column is read top-to-bottom,
then the right column top-to-bottom, preserving logical reading order.

Output contract (used by all downstream modules):
{
    "raw_text": str,                  # full text, newline-joined
    "lines": [
        {
            "text": str,              # visible text of the line
            "font_size": float,       # largest font size on this line
            "is_bold": bool,          # True if any word on line is bold
            "page": int               # 0-indexed page number
        },
        ...
    ],
    "pages": int                      # total page count
}
"""

import re
import pdfplumber
from collections import Counter
from pathlib import Path

_LABEL_PREFIX = re.compile(
    r"^(name|email|phone|mobile|contact|address|linkedin|github|"
    r"location|visa status|current location|skype)\s*:\s*",
    re.IGNORECASE
)


def _classify_line(chars: list) -> dict:
    """Given a list of pdfplumber char dicts on one line, return line metadata."""
    if not chars:
        return {"text": "", "font_size": 0.0, "is_bold": False}

    # Join chars, inserting spaces where the x-gap between consecutive chars
    # is large enough to represent a word boundary.
    # This handles PDFs with no actual space characters (common in some LaTeX exports).
    if len(chars) > 1:
        avg_char_width = sum(
            c.get("width", c.get("x1", c["x0"]) - c["x0"])
            for c in chars if c["text"].strip()
        ) / max(sum(1 for c in chars if c["text"].strip()), 1)
        word_gap_threshold = avg_char_width * 0.5

        parts = [chars[0]["text"]]
        for i in range(1, len(chars)):
            prev, curr = chars[i - 1], chars[i]
            gap = curr["x0"] - prev.get("x1", prev["x0"] + prev.get("width", avg_char_width))
            if gap > word_gap_threshold and curr["text"].strip() and prev["text"].strip():
                parts.append(" ")
            parts.append(curr["text"])
        text = "".join(parts).strip()
    else:
        text = "".join(c["text"] for c in chars).strip()

    text = text.replace("(cid:127)", "•").replace("\x00", "")

    # strip label prefixes (Name:, Email:, Phone: etc.) from contact lines
    text = _LABEL_PREFIX.sub("", text).strip()

    sizes = [c["size"] for c in chars if c.get("size")]
    font_size = max(sizes) if sizes else 0.0

    fonts = [c.get("fontname", "") for c in chars]
    is_bold = any("Bold" in f or "bold" in f or "-Bd" in f for f in fonts)

    return {"text": text, "font_size": round(font_size, 2), "is_bold": is_bold}


def _group_chars_into_lines(chars: list) -> dict:
    """
    Group characters into lines using font-size-aware y0 tolerance.
    Buckets by top edge (y0 + size) rounded to 2pt grid.
    """
    buckets: dict[int, list] = {}
    for c in chars:
        size = c.get("size", 0) or 0
        top = c["y0"] + size
        y_key = round(top / 2) * 2
        buckets.setdefault(y_key, []).append(c)
    return buckets


def _detect_column_split(chars: list, page_width: float) -> float | None:
    """
    Detect if a page has a two-column layout and return the x-split point.

    Strategy:
    - Build a char-start density histogram in 5pt buckets on body text only
    - Find the largest contiguous zero-density gap between the left and right
      text clusters in the middle portion of the page
    - Return the START of the right cluster (not the mid of the gap), because
      that's the actual boundary between columns
    """
    if not chars:
        return None

    ys = [c.get("y0", 0) for c in chars if c["text"].strip()]
    if not ys:
        return None
    y_max = max(ys)
    # Use bottom 80% of page to exclude full-width headers
    body = [c for c in chars if c["text"].strip() and c.get("y0", 0) < y_max * 0.82]
    if not body:
        return None

    bsize = 5
    x_counts = Counter(int(c["x0"] // bsize) * bsize for c in body)

    # Find all left-cluster chars and right-cluster chars
    # by looking for a significant zero-density band between x=100 and x=page_width-100
    # Search the full page width — don't assume margins
    lo = int(bsize)
    hi = int(page_width)

    occupied = sorted(x for x in range(lo, hi, bsize) if x_counts.get(x, 0) > 0)
    if len(occupied) < 4:
        return None

    # Find the largest gap between consecutive occupied x-buckets
    best_gap = 0
    best_right_start = None
    for i in range(1, len(occupied)):
        gap = occupied[i] - occupied[i - 1]
        if gap > best_gap:
            best_gap = gap
            best_right_start = occupied[i]

    # Valid two-column split:
    # - gap >= 40pt
    # - right column starts between 25% and 75% of page width
    if best_right_start and best_gap >= 40:
        if page_width * 0.25 < best_right_start < page_width * 0.75:
            return float(best_right_start)

    return None


def _extract_page_lines(page, page_num: int) -> list:
    """
    Extract lines from a single page, handling two-column layout.

    For two-column pages:
      - The header is detected as the full-width block at the top:
        lines where ALL chars are within 60pt of the horizontal centre
        OR the line spans the full page width — these are the name/contact lines.
      - Everything below the header is split into left and right columns.
    """
    chars = page.chars
    if not chars:
        return []

    split_x = _detect_column_split(chars, page.width)

    if split_x is None:
        # Single column
        buckets = _group_chars_into_lines(chars)
        lines = []
        for y_key in sorted(buckets.keys(), reverse=True):
            line_chars = sorted(buckets[y_key], key=lambda c: c["x0"])
            meta = _classify_line(line_chars)
            if meta["text"]:
                meta["page"] = page_num
                lines.append(meta)
        return lines

    # Two-column layout
    # Strategy:
    #   1. Detect if there's a full-width header block (name/contact centred above both columns)
    #      by finding y-levels where chars SPAN across the split point.
    #   2. If a full-width header exists, read it first, then left col, then right col.
    #   3. If no full-width header (sidebar style — content starts in columns immediately),
    #      read left col then right col directly.

    buckets_all = _group_chars_into_lines(chars)

    # Classify each y-bucket as: spanning, left-only, right-only
    # "Spanning" means chars are continuously distributed ACROSS the gap,
    # not just present on both sides (which happens accidentally in equal columns).
    # We require >= 5 chars within the inter-column zone (split_x ± 80pt).
    spanning_ys   = []
    left_only_ys  = []
    right_only_ys = []

    for y_key in sorted(buckets_all.keys(), reverse=True):
        y_chars = buckets_all[y_key]
        xs = [c["x0"] for c in y_chars if c["text"].strip()]
        if not xs:
            continue
        has_left  = min(xs) < split_x - 10
        has_right = max(xs) > split_x + 10
        # Chars present in the gap zone = true continuous span
        gap_chars = [x for x in xs if split_x - 80 < x < split_x + 20]
        is_truly_spanning = has_left and has_right and len(gap_chars) >= 5

        if is_truly_spanning:
            spanning_ys.append(y_key)
        elif has_left and not has_right:
            left_only_ys.append(y_key)
        elif has_right and not has_left:
            right_only_ys.append(y_key)

    # Find the header boundary: spanning lines that appear above column-only content
    # Additional constraint: the header can only be the topmost 4 lines max
    # to avoid content-row false positives in equal-column layouts
    all_col_ys = set(left_only_ys + right_only_ys)
    header_y_cutoff = None
    if spanning_ys:
        first_col_y = max(all_col_ys) if all_col_ys else 0
        header_spanning = sorted(
            [y for y in spanning_ys if y > first_col_y],
            reverse=True  # highest y first = top of page first
        )
        # Only include contiguous spanning lines from the top (max 4)
        # Stop if there's a large y-gap between consecutive spanning lines
        if header_spanning:
            selected = [header_spanning[0]]
            for i in range(1, min(len(header_spanning), 4)):
                if header_spanning[i - 1] - header_spanning[i] < 30:  # contiguous
                    selected.append(header_spanning[i])
                else:
                    break
            header_y_cutoff = min(selected)

    lines = []

    if header_y_cutoff is not None:
        # Has a full-width header block
        header_chars = [c for c in chars if c.get("y0", 0) >= header_y_cutoff]
        body_chars   = [c for c in chars if c.get("y0", 0) <  header_y_cutoff]
        first_chars  = [c for c in body_chars if c["x0"] <  split_x]
        second_chars = [c for c in body_chars if c["x0"] >= split_x]

        # 1. Full-width header
        hb = _group_chars_into_lines(header_chars)
        for y_key in sorted(hb.keys(), reverse=True):
            lc = sorted(hb[y_key], key=lambda c: c["x0"])
            meta = _classify_line(lc)
            if meta["text"]:
                meta["page"] = page_num
                lines.append(meta)
    else:
        # No full-width header (sidebar style) — split all chars directly
        left_chars  = [c for c in chars if c["x0"] <  split_x]
        right_chars = [c for c in chars if c["x0"] >= split_x]

        # Detect which column contains the name (largest font size)
        # and read that column first so the name appears first in output
        def _max_font(char_list):
            sizes = [c.get("size", 0) or 0 for c in char_list if c["text"].strip()]
            return max(sizes) if sizes else 0

        name_col_is_right = _max_font(right_chars) >= _max_font(left_chars)
        if name_col_is_right:
            first_chars, second_chars = right_chars, left_chars
        else:
            first_chars, second_chars = left_chars, right_chars

    # Name-containing column first (top-to-bottom)
    fb = _group_chars_into_lines(first_chars)
    for y_key in sorted(fb.keys(), reverse=True):
        lc = sorted(fb[y_key], key=lambda c: c["x0"])
        meta = _classify_line(lc)
        if meta["text"]:
            meta["page"] = page_num
            lines.append(meta)

    # Other column second (top-to-bottom)
    sb = _group_chars_into_lines(second_chars)
    for y_key in sorted(sb.keys(), reverse=True):
        lc = sorted(sb[y_key], key=lambda c: c["x0"])
        meta = _classify_line(lc)
        if meta["text"]:
            meta["page"] = page_num
            lines.append(meta)

    return lines


def extract_pdf(path: str) -> dict:
    """
    Extract text and layout metadata from a PDF file.

    Parameters
    ----------
    path : str
        Absolute or relative path to the PDF.

    Returns
    -------
    dict with keys: raw_text, lines, pages
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    all_lines = []

    with pdfplumber.open(path) as pdf:
        total_pages = len(pdf.pages)
        for page_num, page in enumerate(pdf.pages):
            all_lines.extend(_extract_page_lines(page, page_num))

    all_lines = _merge_split_headers(all_lines)

    return {
        "raw_text": "\n".join(l["text"] for l in all_lines),
        "lines":    all_lines,
        "pages":    total_pages,
    }


_KNOWN_HEADERS_UPPER = [
    "EDUCATION", "EXPERIENCE", "PROJECTS", "SKILLS", "CERTIFICATIONS",
    "ACHIEVEMENTS", "SUMMARY", "PUBLICATIONS", "TECHNICALSKILLS",
    "TECHNICALPROJECTS", "WORKEXPERIENCE", "PROFESSIONALEXPERIENCE",
    "EXTRACURRICULARS", "EXTRACURRICULARS", "CERTIFICATIONSANDAWARDS",
    "SKILLSANDINTERESTS", "ACCOMPLISHMENTS", "LEADERSHIP",
]

_KNOWN_HEADERS_CANONICAL = {h.replace(" ", ""): h for h in [
    "EDUCATION", "EXPERIENCE", "PROJECTS", "SKILLS", "CERTIFICATIONS",
    "ACHIEVEMENTS", "SUMMARY", "PUBLICATIONS", "TECHNICAL SKILLS",
    "TECHNICAL PROJECTS", "WORK EXPERIENCE", "PROFESSIONAL EXPERIENCE",
    "EXTRA CURRICULARS", "CERTIFICATIONS AND AWARDS",
    "SKILLS AND INTERESTS", "ACCOMPLISHMENTS", "LEADERSHIP",
    "PROFESSIONAL SUMMARY", "SKILLS SUMMARY", "CAREER SUMMARY",
    "PROJECTS AND CONTRIBUTIONS", "PROJECTS CONTRIBUTIONS",
]}

# Also map common garbled merges explicitly
_GARBLED_HEADER_MAP = {
    "PSROFESSIONALUMMARY":   "SUMMARY",
    "SSKILSUMMARY":          "SKILLS",
    "SKILLSSUMMARY":         "SKILLS",
    "PCROJECTSONTRIBUTIONS": "PROJECTS",
    "SSUMMARY":              "SUMMARY",
    "EEXPERIENCE":           "EXPERIENCE",
    "EEDUCATION":            "EDUCATION",
    "AACHIEVEMENTS":         "ACHIEVEMENTS",
}


def _canonicalise_merged(text: str) -> str:
    """
    Try to match a merged fragment like TSECHNICAL KILLS to TECHNICAL SKILLS.
    Uses exact match, garbled map, and fuzzy matching.
    """
    stripped = text.replace(" ", "").upper()

    # Check garbled map first
    if stripped in _GARBLED_HEADER_MAP:
        return _GARBLED_HEADER_MAP[stripped]

    # Exact match after stripping spaces
    if stripped in _KNOWN_HEADERS_CANONICAL:
        return _KNOWN_HEADERS_CANONICAL[stripped]

    # Fuzzy: find the known header whose space-stripped form has the most
    # overlap with the stripped input (handles off-by-one splits)
    best_match = None
    best_score = 0
    for key, canonical in _KNOWN_HEADERS_CANONICAL.items():
        # Simple overlap: how many chars of key are in stripped (in order)
        s, k = 0, 0
        while s < len(stripped) and k < len(key):
            if stripped[s] == key[k]:
                k += 1
            s += 1
        score = k / len(key) if key else 0
        if score > best_score:
            best_score = score
            best_match = canonical

    # Only accept if very high overlap (>= 0.85) to avoid false positives
    if best_score >= 0.85 and best_match:
        return best_match

    return text


def _merge_split_headers(lines: list) -> list:
    """
    Merge consecutive short uppercase lines that are a split section header.
    e.g. ["E", "DUCATION"] -> ["EDUCATION"]
         ["P S", "ROFESSIONALUMMARY"] -> "PROFESSIONAL SUMMARY"
         ["P & C", "ROJECTSONTRIBUTIONS"] -> "PROJECTS & CONTRIBUTIONS"

    Handles both bold and non-bold fragments (some PDFs don't mark headers bold).
    """
    # Pre-pass: expand single lines with space-separated letter fragments
    # e.g. "P S" -> ["P", "S"] so they can be merged with the next line
    expanded = []
    for line in lines:
        text = line["text"].strip().rstrip(":;.,")
        # Detect "X Y" pattern: 1-2 uppercase letters separated by spaces/symbols
        # but not normal words — must be all short tokens
        tokens = text.split()
        if (len(tokens) >= 2
                and all(len(t) <= 2 and (t.isupper() or t in ("&", "-", "/")) for t in tokens)
                and any(t.isalpha() and t.isupper() for t in tokens)
                and line["font_size"] > 10):
            # Split into individual token lines
            for tok in tokens:
                if tok.isalpha():
                    new_line = dict(line)
                    new_line["text"] = tok
                    expanded.append(new_line)
                # Skip symbols like & in fragments
        else:
            expanded.append(line)

    merged = []
    i = 0
    while i < len(expanded):
        line = expanded[i]
        text = line["text"].strip()

        # Strip trailing punctuation before fragment check (handles "C:", "TS:")
        text_clean = text.rstrip(":;.,")
        # Fragments can be non-bold if font size is notably larger than body
        is_fragment = (
            len(text_clean) <= 5
            and text_clean.isupper()
            and text_clean.isalpha()
            and (line["is_bold"] or line["font_size"] >= 11)
        )

        if is_fragment and i + 1 < len(lines):
            combined = text_clean
            j = i + 1
            while j < len(expanded):
                nxt = expanded[j]["text"].strip().rstrip(":;.,")
                nxt_is_fragment = (
                    (expanded[j]["is_bold"] or expanded[j]["font_size"] >= 9.5)
                    and len(nxt) <= 20
                    and nxt.isupper()
                    and all(c.isalpha() or c == " " for c in nxt)
                )
                if nxt_is_fragment:
                    combined += nxt
                    j += 1
                else:
                    break
            if j > i + 1 and len(combined) >= 4:
                canonical = _canonicalise_merged(combined)
                merged_line = dict(line)
                merged_line["text"] = canonical
                merged_line["font_size"] = max(
                    expanded[k]["font_size"] for k in range(i, j)
                )
                merged.append(merged_line)
                i = j
                continue

        merged.append(line)
        i += 1
    return merged


# ── quick test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    pdf = sys.argv[1] if len(sys.argv) > 1 else "synthetic_resume.pdf"
    result = extract_pdf(pdf)

    print(f"Pages     : {result['pages']}")
    print(f"Lines     : {len(result['lines'])}")
    print()
    print(f"{'FONT':>6}  {'BOLD':>4}  TEXT")
    print("-" * 70)
    for line in result["lines"]:
        bold_flag = "✓" if line["is_bold"] else ""
        print(f"{line['font_size']:>6.1f}  {bold_flag:>4}  {line['text'][:80]}")
