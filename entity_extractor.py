"""
entity_extractor.py
-------------------
Step 3: Extract structured entities from each section.

Input  : sections dict from segmenter.segment()
Output : structured dict ready for JSON serialisation

{
    "header": {
        "name": str,
        "email": str,
        "phone": str,
        "linkedin": str,
        "github": str,
        "location": str
    },
    "education": [
        {
            "degree": str,
            "institution": str,
            "year_start": str,
            "year_end": str,
            "gpa": str,
            "percentage": str
        }
    ],
    "experience": [
        {
            "title": str,
            "company": str,
            "location": str,
            "date_start": str,
            "date_end": str,
            "bullets": [str]
        }
    ],
    "projects": [
        {
            "name": str,
            "tech_stack": [str],
            "description": str
        }
    ],
    "skills": {
        "category_name": [str],
        ...
    },
    "certifications": [
        {
            "name": str,
            "issuer": str,
            "year": str
        }
    ],
    "achievements": [str]
}
"""

import re
from extractor import extract_pdf
from segmenter import segment


# ── helpers ───────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return text.strip().strip("•–-·|").strip()


def _lines_text(lines: list) -> list[str]:
    return [l["text"].strip() for l in lines if l["text"].strip()]


def _is_bullet(text: str) -> bool:
    # Matches bullet chars with optional following punctuation/spaces
    # Handles: "• text", "•:text", "•—text", "- text", "o text" etc.
    return bool(re.match(r"^\s*([•\-\*–—►▪◻●◆▸][:\-–—]?\s*|o\s+|o$)", text))


def _strip_bullet(text: str) -> str:
    return re.sub(r"^\s*([•\-\*–—►▪◻●◆▸][:\-–—]?\s*|o\s+|o$)", "", text).strip()


# ── HEADER ────────────────────────────────────────────────────────────────────

def _parse_header(lines: list) -> dict:
    from segmenter import _looks_like_name

    texts = _lines_text(lines)
    full_text = " ".join(texts)

    email = ""
    phone = ""
    linkedin = ""
    github = ""
    location = ""
    name = ""

    # name: largest-font line that passes _looks_like_name check
    # Falls back to first line passing a simple heuristic
    if lines:
        max_size = max(l.get("font_size", 0) for l in lines)
        for l in lines:
            if l.get("font_size", 0) == max_size and _looks_like_name(l["text"]):
                name = l["text"].strip()
                break
    # fallback: first line with no contact signals and ≤5 words
    if not name:
        for t in texts:
            if not re.search(r"[@/\+\d]", t) and len(t.split()) <= 5:
                name = t
                break

    # email
    m = re.search(r"[\w.\-+]+@[\w.\-]+\.\w+", full_text)
    if m:
        email = m.group()

    # phone — strip cid icon glyphs first, then extract
    _clean_text = re.sub(r"\(cid:\d+\)", " ", full_text)
    m = re.search(r"(\+?91[\s\-]?)?[6-9]\d{9}", _clean_text)
    if m:
        phone = m.group().strip()
    else:
        # Fallback: looser pattern for non-Indian numbers
        m = re.search(r"(\+?\d[\d\s\-]{7,14}\d)", _clean_text)
        if m:
            phone = m.group().strip()

    # linkedin
    m = re.search(r"linkedin\.com/in/[\w\-]+", full_text, re.IGNORECASE)
    if m:
        linkedin = m.group()

    # github
    m = re.search(r"github\.com/[\w\-]+", full_text, re.IGNORECASE)
    if m:
        github = m.group()

    # location — split every line on common separators (|, •, ⋄, ·)
    # and check each segment individually.
    _skip_seg = re.compile(
        r"@|linkedin|github|leetcode|http|<|>|profile|javascript|"
        r"\+\s*\d|\d{6,}",
        re.IGNORECASE
    )
    _place = re.compile(r"^[A-Z][a-zA-Z\s]+(,\s*[A-Z][a-zA-Z\s]+)*$")

    candidates = []
    for line in lines:
        # Split on pipe, bullet, diamond, dot separators
        for part in re.split(r"[|•⋄·]", line["text"]):
            part = part.strip().strip(",").strip()
            if (part
                    and not _skip_seg.search(part)
                    and _place.match(part)
                    and 1 <= len(part.split(",")) <= 4
                    and 1 <= len(part.split()) <= 6):
                candidates.append(part)
    if candidates:
        # Prefer multi-part (City, State, Country) over single word
        candidates.sort(key=lambda x: x.count(","), reverse=True)
        location = candidates[0]

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "github": github,
        "location": location,
    }


# ── EDUCATION ─────────────────────────────────────────────────────────────────

# Patterns that indicate an institution line rather than a degree line
_INSTITUTION_HINTS = re.compile(
    r"\b(university|institute|college|school|iit|nit|bits|iim|iiser|iisc|"
    r"academy|polytechnic|campus|deemed|vidyalaya|"
    r"public school|dps|kendriya|narayana|fiitjee|allen|"
    r"aakash|turito|byju|vidya|mandir|"
    r"anna university|osmania|vtu|jntu|pict|pec|"
    r"bhavan|sri|mount carmel|holy cross|bms|mec|"
    r"symbiosis|amity|manipal|vellore|srm|sastra|"
    r"christ|presidency|ramaiah|rvce|bmsce|pesu|"
    r"dav|kvs|nps|podar|ryan|delhi public|"
    r"junior college|senior secondary|matriculation)\b",
    re.IGNORECASE,
)

# Patterns that look like institution names but are actually board/degree descriptions
_BOARD_PATTERNS = re.compile(
    r"\b(board of|state board|cbse|icse|matriculation board|"
    r"board of intermediate|board of secondary|board of higher secondary)\b",
    re.IGNORECASE,
)

# Patterns that strongly indicate a degree/qualification line (not an institution)
_DEGREE_PATTERNS = re.compile(
    r"\b(bachelor|master|b\.e|b\.tech|m\.tech|b\.sc|m\.sc|phd|ph\.d|"
    r"class x|class xii|class 10|class 12|sslc|hsc|cbse board|icse board|"
    r"higher secondary|secondary school|diploma|b\.com|m\.com|mba|"
    r"dual degree|integrated|honours)\b",
    re.IGNORECASE,
)

_YEAR_RANGE = re.compile(r"(\d{4})\s*[–\-—to]+\s*(\d{4}|present|expected|pursuing)", re.IGNORECASE)
_SINGLE_YEAR = re.compile(r"\b(20\d{2}|19\d{2})\b")
_GPA = re.compile(r"(?:cgpa|gpa|cpi)\s*[:\-]?\s*([\d.]+)\s*(?:/\s*[\d.]+)?", re.IGNORECASE)
_PERCENTAGE = re.compile(r"([\d.]+)\s*%")
_EXPECTED_YEAR = re.compile(r"(?:expected|graduating|graduating in|batch of)\s*(20\d{2})", re.IGNORECASE)


def _parse_education(lines: list) -> list:
    texts = _lines_text(lines)
    entries = []
    current: dict | None = None
    _in_coursework = False  # scoped here so it resets per-parse

    def _flush_entry(entry):
        """Flush coursework buffer and append entry if it has content."""
        if entry is None:
            return
        if entry.get("_cw_buffer"):
            full_cw = " ".join(entry.pop("_cw_buffer"))
            topics = [t.strip() for t in full_cw.split(",")
                      if t.strip() and len(t.strip()) > 2
                      and not _BOARD_PATTERNS.search(t)]
            entry.setdefault("coursework", []).extend(topics)
        if entry.get("degree") or entry.get("institution"):
            entries.append(entry)

    for text in texts:
        # Skip standalone bullet markers and very short non-content lines
        if text in ("o", "•", "-", "*", "–", "●", "⋄", "◆") or len(text) <= 1:
            continue

        has_year = _YEAR_RANGE.search(text) or _SINGLE_YEAR.search(text)
        has_gpa  = _GPA.search(text)
        has_pct  = _PERCENTAGE.search(text)
        has_pipe = "|" in text

        # Institution lines may ALSO contain metrics inline (pipe-separated).
        # Check institution FIRST so we don't consume them as metric-only lines.
        # A pipe+metric line is an institution only if the text before the pipe
        # looks like a name (starts with a capital letter word, not a digit/date)
        _before_pipe = text.split("|")[0].strip() if has_pipe else ""
        _pipe_is_inst = (
            has_pipe
            and (has_gpa or has_pct or has_year)
            and bool(re.match(r"^[A-Za-z]", _before_pipe))
            and not bool(re.match(r"^\d", _before_pipe))
        )
        # A degree pattern always wins over institution hints
        _is_degree_pattern = bool(_DEGREE_PATTERNS.search(text))
        _is_board_line = bool(_BOARD_PATTERNS.search(text))
        _is_inst = (
            not _is_degree_pattern
            and not _is_board_line
            and (
                _INSTITUTION_HINTS.search(text)
                or _pipe_is_inst
                or (current and current.get("degree") and not current.get("institution")
                    and (has_gpa or has_pct or has_year)
                    and not has_pipe)
            )
        )

        if _is_inst:
            if current is not None and current.get("institution"):
                _flush_entry(current)
                _in_coursework = False
                current = _blank_edu()
            if current is None:
                current = _blank_edu()
            # Strip inline location suffix (e.g. "CBIT  Hyderabad, India" → "CBIT")
            inst_raw = text.split("|")[0].strip() if has_pipe else text
            # Remove trailing city/country pattern: multiple spaces + Title Case words
            import re as _re
            inst_clean = _re.sub(r"\s{2,}[A-Z][a-zA-Z,\s]+$", "", inst_raw).strip()
            current["institution"] = inst_clean or inst_raw
            # Extract any inline metrics from the same line
            gm = _GPA.search(text)
            if gm and not current.get("gpa"):
                current["gpa"] = gm.group(1)
            pm = _PERCENTAGE.search(text)
            if pm and not current.get("percentage"):
                current["percentage"] = pm.group(1) + "%"
            yr = _YEAR_RANGE.search(text)
            if yr:
                if not current.get("year_start"): current["year_start"] = yr.group(1)
                if not current.get("year_end"):   current["year_end"]   = yr.group(2)
            else:
                sy = _EXPECTED_YEAR.search(text)
                if sy and not current.get("year_end"):
                    current["year_end"] = sy.group(1)
                else:
                    sy2 = _SINGLE_YEAR.search(text)
                    if sy2 and not current.get("year_end"):
                        current["year_end"] = sy2.group()
            continue

        # Pure metric line (no institution signals) — attach to current entry
        if has_year or has_gpa or has_pct:
            if current is None:
                current = _blank_edu()
            yr = _YEAR_RANGE.search(text)
            if yr:
                current["year_start"] = yr.group(1)
                current["year_end"]   = yr.group(2)
            else:
                sy = _SINGLE_YEAR.search(text)
                if sy:
                    current["year_end"] = sy.group()
            gm = _GPA.search(text)
            if gm:
                current["gpa"] = gm.group(1)
            pm = _PERCENTAGE.search(text)
            if pm:
                current["percentage"] = pm.group(1) + "%"
            continue



        # Coursework line — buffer the raw text for later splitting
        cw_text = _strip_bullet(text)
        cw_match = re.match(r"(relevant|related|core)\s+coursework\s*:\s*(.+)", cw_text, re.IGNORECASE)
        if cw_match:
            if current is None:
                current = _blank_edu()
            current.setdefault("_cw_buffer", []).append(cw_match.group(2))
            _in_coursework = True
            continue
        if re.match(r"(relevant|related|core)\s+coursework", text, re.IGNORECASE):
            continue

        # Coursework continuation — append raw text to buffer, split later
        if (current is not None
                and "_in_coursework" in dir()
                and _in_coursework
                and not has_year and not has_gpa and not has_pct
                and not _DEGREE_PATTERNS.search(text)
                and not _INSTITUTION_HINTS.search(text)
                and not _is_bullet(text)):
            current.setdefault("_cw_buffer", []).append(text)
            continue
        else:
            # End of coursework block
            if _in_coursework and current is not None:
                if current.get("_cw_buffer"):
                    full_cw = " ".join(current.pop("_cw_buffer"))
                    topics = [t.strip() for t in full_cw.split(",")
                              if t.strip() and len(t.strip()) > 2
                              and not _BOARD_PATTERNS.search(t)]
                    current.setdefault("coursework", []).extend(topics)
            _in_coursework = False

        # Board lines (e.g. "Board of Intermediate Education; Score: 98.8%")
        # should attach metrics to current entry, not start a new degree
        if _BOARD_PATTERNS.search(text):
            if current is None:
                current = _blank_edu()
            # Extract any metrics from board line
            gm = _GPA.search(text)
            if gm and not current.get("gpa"):
                current["gpa"] = gm.group(1)
            pm = _PERCENTAGE.search(text)
            if pm and not current.get("percentage"):
                current["percentage"] = pm.group(1) + "%"
            continue

        # Degree line — includes formal degrees AND school-level qualifications
        # e.g. "Class XII", "Class X", "Higher Secondary Certificate", "SSLC"
        if current is not None and current.get("degree"):
            entries.append(current)
            current = _blank_edu()
        else:
            current = _blank_edu()

        current["degree"] = text

    _flush_entry(current)
    return entries[:5]


def _blank_edu():
    return {"degree": "", "institution": "", "year_start": "", "year_end": "", "gpa": "", "percentage": "", "coursework": []}


# ── EXPERIENCE ────────────────────────────────────────────────────────────────

_DATE_RANGE = re.compile(
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s*\d{0,4}\s*[–\-—to]+\s*"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?|present|current|ongoing)\s*\d{0,4}",
    re.IGNORECASE,
)

_TITLE_KEYWORDS = re.compile(
    r"\b(intern(?:ship)?|engineer|developer|analyst|scientist|manager|lead|architect|"
    r"consultant|associate|researcher|specialist|coordinator|director|officer|"
    r"head|president|vice president|vp|sde|swe|"
    r"teaching assistant|research assistant|ta|ra|"
    r"fellow|scholar|trainee|executive|founder|co-founder|"
    r"product manager|pm|tpm|program manager|"
    r"data scientist|ml engineer|ai engineer)\b",
    re.IGNORECASE,
)


def _parse_experience(lines: list) -> list:
    entries = []
    current: dict | None = None

    def flush():
        if current and (current.get("title") or current.get("company")):
            entries.append(current)

    for line_dict in lines:
        text = line_dict["text"].strip() if isinstance(line_dict, dict) else line_dict
        if not text:
            continue
        # Date range line — only if the line is primarily a date (short, no title keywords)
        dm = _DATE_RANGE.search(text)
        if dm and not _TITLE_KEYWORDS.search(text) and len(text.split()) <= 10:
            if current is None:
                current = _blank_exp()
            # Split full date string on separator
            sep = re.search(r"[–\-—]|to\b", text[dm.start():], re.IGNORECASE)
            if sep:
                mid = dm.start() + sep.start()
                current["date_start"] = text[dm.start():mid].strip()
                current["date_end"] = text[mid + 1:dm.end()].strip(" –—-to")
            continue

        # Bullet point — starts a new bullet (skip empty ones)
        if _is_bullet(text):
            stripped = _strip_bullet(text)
            if stripped:  # only add non-empty bullets
                if current is None:
                    current = _blank_exp()
                current["bullets"].append(stripped)
            continue

        # Non-bold, non-bullet continuation line inside an experience block
        # (wrapped bullet text, e.g. "Spring Boot and MySQL." after a cut-off bullet)
        _is_bold_line = line_dict.get("is_bold", False) if isinstance(line_dict, dict) else False
        if (current and current.get("bullets")
                and not _is_bold_line
                and not _DATE_RANGE.search(text)
                and not _TITLE_KEYWORDS.search(text)
                and not _INSTITUTION_HINTS.search(text)):
            current["bullets"][-1] = current["bullets"][-1] + " " + text
            continue

        # Company / location line — usually contains · or , separating company and city
        if current and current.get("title") and not current.get("company"):
            # Split on · or , to separate company from location
            parts = re.split(r"[·,]", text, maxsplit=1)
            current["company"] = parts[0].strip()
            if len(parts) > 1:
                current["location"] = parts[1].strip()
            continue

        # Plain non-bold line after title+company — treat as bullet
        _is_bold_line = line_dict.get("is_bold", False) if isinstance(line_dict, dict) else False
        if current and current.get("title") and current.get("company") and not _is_bold_line:
            if text and len(text.split()) >= 4:
                current["bullets"].append(text)
            continue

        # Title line — contains a known title keyword
        # Exclude personal statement lines starting with "I " even if they have title keywords
        if _TITLE_KEYWORDS.search(text) and not re.match(r"^I\b", text, re.IGNORECASE):
            flush()
            current = _blank_exp()
            import re as _re
            working = text

            # First: handle inline "Title - Company (date)" or "Title | Company (date)"
            _INLINE_SEP = _re.compile(r"\s+[-|]\s+(.+?)\s*(\([^)]*\d{4}[^)]*\))?\s*$")
            _inline_m = _INLINE_SEP.search(working)
            if _inline_m:
                title_clean = working[:_inline_m.start()].strip()
                current["company"] = _inline_m.group(1).strip().rstrip(".,")
                if _inline_m.group(2):
                    date_str = _inline_m.group(2).strip("()")
                    _DATE_SPLIT = _re.compile(r"\s*[-–]\s*")
                    parts = [p.strip() for p in _DATE_SPLIT.split(date_str, 1)]
                    current["date_start"] = parts[0]
                    current["date_end"]   = parts[1] if len(parts) > 1 else "Present"
            else:
                # Extract company from parentheses: "Intern (Company Name)"
                # Only if parens don't look like a date
                paren_match = _re.search(r"\(([^)]{3,50})\)", working)
                if paren_match and not _re.search(r"\d{4}|present|current", paren_match.group(1), _re.IGNORECASE):
                    current["company"] = paren_match.group(1).strip()
                    working = _re.sub(r"\s*\([^)]+\)\s*", " ", working).strip()

                title_clean = _re.sub(r"\s{2,}[A-Z][a-zA-Z\s,]+$", "", working).strip()
                if not title_clean or len(title_clean) < 5:
                    title_clean = working
                _DESC_BLEED = _re.compile(r"\s+(We |I |The team|Our |This )", _re.IGNORECASE)
                bleed_m = _DESC_BLEED.search(title_clean)
                if bleed_m:
                    title_clean = title_clean[:bleed_m.start()].rstrip("\u2013\u2014-,. ")
                elif len(title_clean) > 80:
                    title_clean = title_clean[:80].rsplit(" ", 1)[0].rstrip("\u2013\u2014-,")

            current["title"] = title_clean or working
            continue

        # Fallback: if we have no title yet, treat as title
        # Exclude lines that are clearly personal statements or continuations
        if current is None or not current.get("title"):
            if re.match(r"^I (also|was|have|am|served|worked|helped|built)", text, re.IGNORECASE):
                # Personal statement — treat as description bullet of current entry
                if current and current.get("title"):
                    current["bullets"].append(text)
                continue
            flush()
            current = _blank_exp()
            current["title"] = text

    flush()
    return entries


def _blank_exp():
    return {"title": "", "company": "", "location": "", "date_start": "", "date_end": "", "bullets": []}


# ── PROJECTS ──────────────────────────────────────────────────────────────────

# Tech stack line: short, contains · separators or known tech tokens, no full sentences
_TECH_STACK_LINE = re.compile(
    r"^[\w\s\.\-/+#]+(·[\w\s\.\-/+#]+){1,}$"
)


# Project name detection helpers
_NUMBERED_PREFIX = re.compile(r"^\d+[.):\s]\s*")
_TRAILING_SEP    = re.compile(r"[-–—:]+\s*$")


def _clean_project_name(text: str) -> str:
    text = _NUMBERED_PREFIX.sub("", text).strip()
    text = _TRAILING_SEP.sub("", text).strip()
    return text


# Patterns that indicate a project name line even without bold/size signals
_TECH_AFTER_DASH = re.compile(
    r"[-–—]\s*"
    r"(python|java|javascript|react|node|flask|django|html|css|"
    r"tensorflow|pytorch|opencv|sql|mongodb|mysql|aws|docker|"
    r"c\+\+|ml|ai|nlp|cnn|lstm|bert|yolo|streamlit|fastapi)",
    re.IGNORECASE
)
_TECHNOLOGIES_PREFIX = re.compile(r"^technologies\s*:", re.IGNORECASE)


def _is_project_name_line(line: dict, median_size: float) -> bool:
    """
    Returns True if this line is likely a project name.

    Visual signals (bold/larger font):
      - bold=True, OR font_size > median * 1.05

    Structural signals (for same-size resumes):
      - Short line (<=15 words) that is not a bullet, not a sentence,
        not a date, and optionally followed by a tech keyword after a dash
      - Contains a project-name pattern: title case or ALL CAPS short phrase

    A line starting with a bullet is NEVER a project name.
    """
    text = line["text"].strip()
    if not text or _is_bullet(text):
        return False
    if _TECHNOLOGIES_PREFIX.match(text):
        return False

    words = text.split()
    if len(words) > 15:
        return False

    # Visual signals — check FIRST before any content-based rejections
    # A bold or larger line is almost always a heading/project name even if it ends with "."
    is_bold   = line.get("is_bold", False)
    is_larger = median_size > 0 and line["font_size"] > median_size * 1.05
    if (is_bold or is_larger) and not _DATE_RANGE.search(text[:20]):
        return True

    # For non-bold lines: apply stricter content filters
    if text.endswith(".") and not _TECH_AFTER_DASH.search(text):
        return False

    # Reject lines where a date range appears at the very start
    dm = _DATE_RANGE.search(text)
    if dm and dm.start() < 10:
        return False

    # Structural signals for same-size resumes
    # Signal 1: has tech keywords after a dash separator
    if _TECH_AFTER_DASH.search(text):
        return True

    # Signal 2: title-cased or ALL CAPS (most words start with uppercase)
    # Applies to lines up to 12 words to catch "FortiPay: Real-Time UPI Fraud Detection"
    if len(words) <= 12:
        upper_words = sum(1 for w in words
                          if w and w[0].isupper() and not w.isdigit())
        non_digits = [w for w in words if not w.isdigit()]
        if non_digits and upper_words / len(non_digits) >= 0.65:
            return True

    # Signal 3: line contains 'GitHub' or 'Live' link markers (common project name lines)
    if re.search(r"(github|gitlab|live|demo|link)", text, re.IGNORECASE) and len(words) <= 10:
        return True

    return False


def _parse_projects(lines: list) -> list:
    """
    Handles multiple real-world project formats:
      A) Bold/larger name + optional tech stack line + description bullets
      B) "Project Name | Tech1, Tech2" inline stack
      C) Numbered: "1. Project Name" or "1) Project Name"
      D) Name ending with "-" or ":" separator
      E) Non-bold name (just larger font)
    """
    import statistics
    sizes = [l["font_size"] for l in lines if l["font_size"] > 0]
    median_size = statistics.median(sizes) if sizes else 10.0

    entries = []
    current: dict | None = None
    desc_parts: list[str] = []

    def flush():
        if current:
            current["description"] = " ".join(desc_parts).strip()
            entries.append(current)

    for line in lines:
        text = line["text"].strip()
        if not text:
            continue

        # Skip standalone bullet markers
        if text in ("o", "•", "-", "*", "–"):
            continue

        # Standalone tech stack line — · or • separated, OR "Technologies: x, y, z"
        _is_stack = (
            (("·" in text or "•" in text)
             and len(text.split()) <= 15
             and not text.endswith(".")
             and not _is_bullet(text))
            or _TECHNOLOGIES_PREFIX.match(text)
        )
        if _is_stack:
            if current is not None:
                raw = re.sub(r"^technologies\s*:\s*", "", text, flags=re.IGNORECASE)
                current["tech_stack"] = [t.strip() for t in re.split(r"[·•,]", raw) if t.strip()]
            continue

        # Bullet → description
        if _is_bullet(text):
            desc_parts.append(_strip_bullet(text))
            continue

        # Project name line
        if _is_project_name_line(line, median_size):
            flush()
            clean_name = _clean_project_name(text)
            name, stack = clean_name, []

            if "|" in clean_name:
                parts = clean_name.split("|", 1)
                name = parts[0].strip()
                stack = [t.strip() for t in re.split(r"[,·]", parts[1]) if t.strip()]

            elif " — " in clean_name or " – " in clean_name:
                sep = " — " if " — " in clean_name else " – "
                parts = clean_name.split(sep, 1)
                if re.search(r"[,.]", parts[1]):
                    name = parts[0].strip()
                    stack = [t.strip() for t in re.split(r"[,·]", parts[1]) if t.strip()]

            else:
                # Detect inline tech stack: "Project Name Tech1, Tech2, Tech3"
                # Heuristic: find where a sequence of comma-separated short tokens starts
                # These tokens look like tech names (no spaces within, or known keywords)
                _TECH_SPLIT = re.compile(
                    r"\s+((?:[A-Z][a-zA-Z0-9+#.]*|[a-z][a-zA-Z0-9+#.]+)"
                    r"(?:,\s*(?:[A-Z][a-zA-Z0-9+#.]*|[a-z][a-zA-Z0-9+#.]+))+)\s*$"
                )
                m = _TECH_SPLIT.search(clean_name)
                if m and len(m.group(1).split(",")) >= 2:
                    name = clean_name[:m.start()].strip()
                    stack = [t.strip() for t in m.group(1).split(",") if t.strip()]

            if name:  # only create entry if we have a non-empty name
                current = {"name": name, "tech_stack": stack, "description": ""}
                desc_parts = []
            continue

        desc_parts.append(text)

    flush()
    return entries


# ── SKILLS ────────────────────────────────────────────────────────────────────

def _parse_skills(lines: list) -> dict:
    """
    Handles three skill formats:
      A) Categorised  : "Languages: Python, C++, Go"
      B) Bold label   : bold line "Languages" followed by non-bold "Python, C++"
      C) Flat list    : "Python • C++ • Java" or "Python, C++, Java"
    """
    skills: dict[str, list[str]] = {}
    uncategorised: list[str] = []
    pending_category = None

    for line in lines:
        text = line["text"].strip()
        if not text:
            continue

        # Skip standalone bullet markers used as separators
        if text in ("o", "•", "-", "*"):
            continue

        # Format A: "Category: item1, item2"
        m = re.match(r"^([^:]{2,40}):\s*(.+)$", text)
        if m:
            category = _strip_bullet(m.group(1)).strip()
            items = [s.strip() for s in re.split(r"[,·•]", m.group(2)) if s.strip()]
            skills[category] = items
            pending_category = None
            continue

        # Format B: bold short line = category label, next line(s) = items
        if line.get("is_bold") and len(text.split()) <= 4 and not text.endswith(":"):
            # Could be a category label — hold it
            pending_category = text
            continue

        # Items line following a pending category
        if pending_category:
            items = [s.strip() for s in re.split(r"[,·•]", _strip_bullet(text)) if s.strip()]
            if items:
                skills[pending_category] = items
                pending_category = None
                continue

        # Format C: flat bullet/comma list
        items = [s.strip() for s in re.split(r"[,·•]", _strip_bullet(text)) if s.strip()]
        uncategorised.extend(items)

    if uncategorised:
        # Try to split items that may be merged due to two-column PDF layout
        # e.g. "Machine learningWeb development" → two items
        split_items = []
        for item in uncategorised:
            if len(item) > 20:
                # Split on internal uppercase after lowercase (camelCase boundary)
                parts = re.sub(r"([a-z])([A-Z])", r"\1|\2", item).split("|")
                if len(parts) > 1:
                    split_items.extend(p.strip() for p in parts if p.strip())
                else:
                    split_items.append(item)
            else:
                split_items.append(item)
        skills["Other"] = split_items

    return skills


# ── CERTIFICATIONS ────────────────────────────────────────────────────────────

# Keywords that indicate an entry is an achievement/hackathon, not a certification
# No word boundaries — handles both spaced and no-spaces PDF text
_ACHIEVEMENT_KEYWORDS = re.compile(
    r"(hackathon|prize|winner|finalist|participated|participation|"
    r"competition|award|champion|runnerup|runner.up|"
    r"nominated|scholarship|fellowship|appreciation|certificate of)",
    re.IGNORECASE
)


def _parse_certifications(lines: list) -> tuple[list, list]:
    """
    Parse certifications section.
    Returns (certifications, achievements) — entries that look like
    hackathon awards/participations are routed to achievements.
    """
    texts = _lines_text(lines)
    cert_entries = []
    ach_entries = []
    pending_name = ""   # bold event/cert name waiting for detail line

    for line in lines:
        text = line["text"].strip()
        if not text:
            continue

        is_bold = line.get("is_bold", False)
        stripped = _strip_bullet(text)

        # Bold non-bullet line = event/cert name header
        if is_bold and not _is_bullet(text):
            # Flush any pending name with no detail
            if pending_name:
                if _ACHIEVEMENT_KEYWORDS.search(pending_name):
                    ach_entries.append(pending_name)
                else:
                    _flush_cert(cert_entries, pending_name, "", "")
            pending_name = stripped
            continue

        # Bullet line = detail for the pending name
        if _is_bullet(text) and pending_name:
            detail = stripped
            if _ACHIEVEMENT_KEYWORDS.search(pending_name) or _ACHIEVEMENT_KEYWORDS.search(detail):
                ach_entries.append(f"{pending_name}: {detail}" if detail else pending_name)
            else:
                # Parse "Issuer — Year" or "Year" from detail
                year, issuer = "", detail
                yr_match = re.search(r"\b(20\d{2}|19\d{2})\b", detail)
                if yr_match:
                    year = yr_match.group()
                    issuer = detail[:yr_match.start()].strip(" ·—-|")
                _flush_cert(cert_entries, pending_name, issuer, year)
            pending_name = ""
            continue

        # Plain line (no pending name) — treat as self-contained entry
        stripped_clean = _strip_bullet(stripped)
        if not stripped_clean:
            continue
        if _ACHIEVEMENT_KEYWORDS.search(stripped_clean):
            ach_entries.append(stripped_clean)
        else:
            parts = [p.strip() for p in re.split(r"[·|]", stripped_clean)]
            year, issuer = "", ""
            name = parts[0]
            for part in parts[1:]:
                if re.match(r"^\d{4}$", part):
                    year = part
                else:
                    issuer = part
            if _ACHIEVEMENT_KEYWORDS.search(name):
                ach_entries.append(name)
            else:
                _flush_cert(cert_entries, name, issuer, year)

    # Flush any remaining pending name
    if pending_name:
        if _ACHIEVEMENT_KEYWORDS.search(pending_name):
            ach_entries.append(pending_name)
        else:
            _flush_cert(cert_entries, pending_name, "", "")

    return cert_entries, ach_entries


def _flush_cert(entries, name, issuer, year):
    if name:
        entries.append({"name": name, "issuer": issuer, "year": year})


# ── ACHIEVEMENTS ──────────────────────────────────────────────────────────────

# Patterns to filter out of achievements (personal statements, URLs, hobbies)
_ACH_FILTER = re.compile(
    r"^(https?://|I |My |An |A |The |Fluent|I'm|I am|I love|I enjoy|"
    r"linkedin\.com|github\.com|leetcode\.com)",
    re.IGNORECASE
)


_INCOMPLETE = re.compile(r"\b(for|at|in|with|by|from|of|to|and|the|a|an)\s*$", re.IGNORECASE)


# Institution+date context lines in leadership sections
_INST_DATE_LINE = re.compile(
    r"\b(university|institute|college|school|iit|nit|bits|cbit)\b.{0,60}"
    r"(present|current|\d{4})",
    re.IGNORECASE
)


def _parse_achievements(lines: list) -> list:
    entries = []
    current = ""
    pending_org = ""

    has_bold   = any(l.get("is_bold") for l in lines if l["text"].strip())
    has_bullet = any(_is_bullet(l["text"].strip()) for l in lines if l["text"].strip())
    style_c    = not has_bold and not has_bullet

    for line in lines:
        text = line["text"].strip()
        if not text:
            continue
        is_bold = line.get("is_bold", False)

        if style_c:
            if _ACH_FILTER.search(text):
                continue
            is_cont = (
                entries and len(text.split()) <= 5 and not text[0].isupper()
                or (entries and not entries[-1].endswith(".") and len(text.split()) <= 4)
            )
            if is_cont:
                entries[-1] = entries[-1].rstrip() + " " + text
            else:
                entries.append(text)
            continue

        # Institution+date line — treat as org context, not an entry
        # Check regardless of bold since LaTeX resumes often have no bold
        if _INST_DATE_LINE.search(text) and not _is_bullet(text):
            if current:
                entries.append(current.strip())
                current = ""
            pending_org = re.split(r"\s{2,}|(?:present|current|\d{4})", text, flags=re.IGNORECASE)[0].strip()
            continue

        if _is_bullet(text):
            stripped = _strip_bullet(text)
            if current and _INCOMPLETE.search(current.rstrip()):
                current = (current.rstrip() + " " + stripped).strip()
            else:
                if current:
                    entries.append(current.strip())
                current = stripped

        elif is_bold and current:
            if _INCOMPLETE.search(current.rstrip()):
                current = (current.rstrip() + " " + text).strip()
            else:
                entries.append(current.strip())
                current = f"{pending_org} — {text}" if pending_org else text
                pending_org = ""

        elif is_bold and not current:
            current = f"{pending_org} — {text}" if pending_org else text
            pending_org = ""

        # Non-bold, non-bullet line
        else:
            # If pending_org set, this is the role title following an institution line
            if pending_org:
                if current:
                    entries.append(current.strip())
                current = f"{pending_org} — {text}"
                pending_org = ""
            else:
                current = (current + " " + text).strip() if current else text

    if current:
        entries.append(current.strip())

    return [e for e in entries if e.strip() and not _ACH_FILTER.search(e)]


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_entities(sections: dict) -> dict:
    """
    Run all per-section parsers and return a unified structured dict.

    Parameters
    ----------
    sections : dict
        Output from segmenter.segment()

    Returns
    -------
    dict with keys: header, education, experience, projects, skills,
                    certifications, achievements
    """
    summary_lines = sections.get("PROFILE", [])
    summary = " ".join(l["text"] for l in summary_lines).strip()

    # Certifications parser may route hackathon/award entries to achievements
    _certs, _cert_achievements = _parse_certifications(sections.get("CERTIFICATIONS", []))
    _achievements = _parse_achievements(sections.get("ACHIEVEMENTS", []))

    # Languages — flat list
    _lang_lines = sections.get("LANGUAGES", [])
    _languages = [
        _strip_bullet(l["text"]).strip()
        for l in _lang_lines
        if _strip_bullet(l["text"]).strip() and len(_strip_bullet(l["text"]).split()) <= 5
    ]

    # Extracurriculars and Leadership — treated same as achievements (flat list)
    _extracurriculars = _parse_achievements(sections.get("EXTRACURRICULARS", []))
    _leadership = _parse_achievements(sections.get("LEADERSHIP", []))

    return {
        "header":           _parse_header(sections.get("HEADER", [])),
        "profile":          summary,
        "education":        _parse_education(sections.get("EDUCATION", [])),
        "experience":       _parse_experience(sections.get("EXPERIENCE", [])),
        "projects":         _parse_projects(sections.get("PROJECTS", [])),
        "skills":           _parse_skills(sections.get("SKILLS", [])),
        "certifications":   _certs,
        "achievements":     _achievements + _cert_achievements,
        "languages":        _languages,
        "extracurriculars": _extracurriculars,
        "leadership":       _leadership,
    }


# ── quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    extracted = extract_pdf("synthetic_resume.pdf")
    sections = segment(extracted)
    entities = extract_entities(sections)

    print(json.dumps(entities, indent=2))
