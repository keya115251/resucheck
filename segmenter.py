"""
segmenter.py
------------
Step 2: Identify section headers and split lines into named sections.

Input  : output dict from extractor.extract_pdf()
Output :
{
    "HEADER":          [line, ...],   # name + contact info
    "EDUCATION":       [line, ...],
    "EXPERIENCE":      [line, ...],
    "PROJECTS":        [line, ...],
    "SKILLS":          [line, ...],
    "CERTIFICATIONS":  [line, ...],
    "ACHIEVEMENTS":    [line, ...],
    "PROFILE":         [line, ...],
    "UNKNOWN":         [line, ...],   # unrecognised sections
}

Each line is the same dict from extractor:
    {"text": str, "font_size": float, "is_bold": bool, "page": int}
"""

import re
import statistics
from extractor import extract_pdf


# ── 1. Canonical section name mapping ────────────────────────────────────────

SECTION_ALIASES = {
    # Education
    "education": "EDUCATION",
    "academic background": "EDUCATION",
    "academic qualifications": "EDUCATION",
    "qualifications": "EDUCATION",
    "academic history": "EDUCATION",

    # Experience
    "experience": "EXPERIENCE",
    "work experience": "EXPERIENCE",
    "professional experience": "EXPERIENCE",
    "professionalexperience": "EXPERIENCE",
    "professionalbackground": "EXPERIENCE",
    "workexperience": "EXPERIENCE",
    "technicalskills": "SKILLS",
    "coreskills": "SKILLS",
    "professionalObjective": "PROFILE",
    "professionalobjective": "PROFILE",
    "certifications&awards": "CERTIFICATIONS",
    "leadership&activities": "ACHIEVEMENTS",

    "professional experience:": "EXPERIENCE",
    "employment history": "EXPERIENCE",
    "work history": "EXPERIENCE",
    "internship": "EXPERIENCE",
    "internships": "EXPERIENCE",
    "internship experience": "EXPERIENCE",
    "industry experience": "EXPERIENCE",
    "relevant experience": "EXPERIENCE",
    "career history": "EXPERIENCE",
    "professional background": "EXPERIENCE",

    # Projects
    "projects": "PROJECTS",
    "key projects": "PROJECTS",
    "personal projects": "PROJECTS",
    "academic projects": "PROJECTS",
    "technical projects": "PROJECTS",
    "keyprojects": "PROJECTS",
    "selected projects": "PROJECTS",
    "what i've built": "PROJECTS",
    "things i've built": "PROJECTS",
    "portfolio": "PROJECTS",

    # Skills
    "skills": "SKILLS",
    "skill": "SKILLS",
    "technical skills": "SKILLS",
    "technical skill": "SKILLS",
    "skills and interests": "SKILLS",
    "skills & interests": "SKILLS",
    "core competencies": "SKILLS",
    "competencies": "SKILLS",
    "technologies": "SKILLS",
    "tech stack": "SKILLS",
    "tools & technologies": "SKILLS",
    "tools and technologies": "SKILLS",
    "areas of expertise": "SKILLS",
    "information": "SKILLS",

    # Certifications
    "certifications": "CERTIFICATIONS",
    "certificates": "CERTIFICATIONS",
    "certifications & awards": "CERTIFICATIONS",
    "certifications&awards": "CERTIFICATIONS",
    "achievements and certifications": "CERTIFICATIONS",
    "certifications & courses": "CERTIFICATIONS",
    "licenses & certifications": "CERTIFICATIONS",
    "licenses and certifications": "CERTIFICATIONS",
    "courses": "CERTIFICATIONS",
    "online courses": "CERTIFICATIONS",

    # Hackathons (map to ACHIEVEMENTS — same display section)
    "hackathons": "ACHIEVEMENTS",
    "hackathon": "ACHIEVEMENTS",
    "hackathons and projects": "ACHIEVEMENTS",
    "awards and hackathons": "ACHIEVEMENTS",
    "awards & hackathons": "ACHIEVEMENTS",
    "competitions": "ACHIEVEMENTS",
    "competitions and hackathons": "ACHIEVEMENTS",

    # Achievements — broad set to catch common variants
    "achievements": "ACHIEVEMENTS",
    "awards": "ACHIEVEMENTS",
    "honors": "ACHIEVEMENTS",
    "honours": "ACHIEVEMENTS",
    "awards & achievements": "ACHIEVEMENTS",
    "achievements & awards": "ACHIEVEMENTS",
    "extracurriculars": "ACHIEVEMENTS",
    "extra-curriculars": "ACHIEVEMENTS",
    "extra curricular activities": "EXTRACURRICULARS",
    "extra-curricular activities": "EXTRACURRICULARS",
    "extra curriculars": "EXTRACURRICULARS",
    "co-curricular activities": "EXTRACURRICULARS",
    "co curricular activities": "EXTRACURRICULARS",
    "websites & portfolios": "ACHIEVEMENTS",
    "leadership & experience": "LEADERSHIP",
    "leadership & activities": "LEADERSHIP",
    "leadership&activities": "LEADERSHIP",
    "leadership & extracurricular": "LEADERSHIP",
    "leadership & extracurriculars": "LEADERSHIP",
    "leadership and extracurricular": "LEADERSHIP",
    "positions of responsibility": "LEADERSHIP",
    "achievements&activities": "ACHIEVEMENTS",
    "achievements & activities": "ACHIEVEMENTS",
    "achievements & extracurriculars": "ACHIEVEMENTS",
    "extracurriculars & achievements": "ACHIEVEMENTS",
    "interests & achievements": "ACHIEVEMENTS",
    "activities & achievements": "ACHIEVEMENTS",
    "achievements & activities": "ACHIEVEMENTS",
    "achievements & extra circular": "ACHIEVEMENTS",
    "achievements & extra curricular": "ACHIEVEMENTS",
    "achievements & extracircular": "ACHIEVEMENTS",
    "hackathons and achievements": "ACHIEVEMENTS",
    "hackathons ,achievements and projects": "ACHIEVEMENTS",
    "hackathons, achievements and projects": "ACHIEVEMENTS",
    "hackathons ,achievements & projects": "ACHIEVEMENTS",
    "hackathons & achievements": "ACHIEVEMENTS",
    "hackathons participated": "ACHIEVEMENTS",
    "accomplishments": "ACHIEVEMENTS",
    "activities": "ACHIEVEMENTS",
    "campus involvement": "ACHIEVEMENTS",
    "leadership": "ACHIEVEMENTS",
    "leadership & activities": "ACHIEVEMENTS",
    "leadership&activities": "ACHIEVEMENTS",
    "positions of responsibility": "ACHIEVEMENTS",
    "co-curricular activities": "ACHIEVEMENTS",
    "co-curriculars": "ACHIEVEMENTS",
    "hobbies & interests": "EXTRACURRICULARS",
    "interests": "EXTRACURRICULARS",
    "hobbies": "EXTRACURRICULARS",
    "hobbies and interests": "EXTRACURRICULARS",
    "volunteering": "ACHIEVEMENTS",
    "strengths & personal traits": "ACHIEVEMENTS",
    "key strengths": "ACHIEVEMENTS",
    "additional information": "ACHIEVEMENTS",
    "research work": "PUBLICATIONS",
    "technical skills": "SKILLS",

    # Publications
    "publications": "PUBLICATIONS",
    "research": "PUBLICATIONS",
    "papers": "PUBLICATIONS",
    "research papers": "PUBLICATIONS",
    "research & publications": "PUBLICATIONS",
    "publications & research": "PUBLICATIONS",
    "journal publications": "PUBLICATIONS",
    "conference papers": "PUBLICATIONS",
    "research experience": "PUBLICATIONS",

    # Summary / objective
    "summary": "PROFILE",
    "summary:": "PROFILE",
    "objective": "PROFILE",
    "objective:": "PROFILE",
    "career objective": "PROFILE",
    "career objective:": "PROFILE",
    "about me": "PROFILE",
    "profile": "PROFILE",
    "profile summary": "PROFILE",
    "profile summary:": "PROFILE",
    "professional summary": "PROFILE",
    "professional summary:": "PROFILE",
    "professional profile": "PROFILE",
    "about": "PROFILE",
    "overview": "PROFILE",
    "personal statement": "PROFILE",
}


# ── 2. Name detection helpers ─────────────────────────────────────────────────

# Patterns that strongly suggest a line is contact info, not a name
_CONTACT_PATTERNS = re.compile(
    r"@|linkedin|github|leetcode|http|www\.|"
    r"\+\d|\d{10}|gmail|yahoo|hotmail|"
    r"profile|hyderabad|bangalore|mumbai|delhi|india|"
    r"\|.*\|",   # multiple pipes = contact line
    re.IGNORECASE,
)

def _looks_like_name(text: str) -> bool:
    """
    Returns True if a line looks like a person's name.
    Heuristics: short (≤5 words), no contact signals, title/mixed case.
    """
    if _CONTACT_PATTERNS.search(text):
        return False
    words = text.strip().split()
    if not (1 <= len(words) <= 5):
        return False
    # At least one word starts with uppercase
    if not any(w[0].isupper() for w in words if w):
        return False
    return True


# ── 3. Scoring signals ────────────────────────────────────────────────────────

def _median_font_size(lines: list) -> float:
    sizes = [l["font_size"] for l in lines if l["font_size"] > 0]
    return statistics.median(sizes) if sizes else 10.0


def _score_line(line: dict, median_size: float) -> tuple[float, str]:
    """
    Score a line on 7 signals. Returns (score, canonical_section_name_or_empty).
    Score >= HEADER_THRESHOLD → treat as section header.
    """
    text = line["text"].strip()
    if not text:
        return 0.0, ""

    score = 0.0
    canonical = ""

    # Signal 1: relatively larger font than body text
    if median_size > 0 and line["font_size"] > median_size * 1.1:
        score += 1.0

    # Signal 2: bold
    if line["is_bold"]:
        score += 0.75

    # Signal 3: ALL CAPS or Title Case on a short line (≤6 words)
    words = text.split()
    is_short = len(words) <= 6
    if is_short and text.isupper():
        score += 1.0
    elif is_short and text.istitle():
        score += 0.5

    # Signal 4: matches known header keyword (strongest signal)
    normalised = text.lower().strip("•:-_|/ ")
    if normalised in SECTION_ALIASES:
        score += 2.0
        canonical = SECTION_ALIASES[normalised]

    # Signal 5: short line (≤6 words)
    if is_short:
        score += 0.25

    # Signal 6: no sentence-ending punctuation
    if not text.endswith((".", ",", ";", ":", "?")):
        score += 0.25

    # Signal 7: no bullet at start
    if not text.startswith(("•", "-", "*", "–")):
        score += 0.25

    # Veto: lines that look like date ranges are never section headers
    _DATE_RANGE_LINE = re.compile(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|"
        r"march|april|june|july|august|september|october|november|december)"
        r"(\s+\d{4}|\s*[-–]\s*)",
        re.IGNORECASE,
    )
    if _DATE_RANGE_LINE.search(text):
        return 0.0, ""

    # Veto: unknown section (no canonical match) that contains a job title keyword
    # e.g. "Machine Learning Intern", "Senior Software Engineer"
    # These are experience/role title lines, not section headers
    _TITLE_KW = re.compile(
        r"\b(intern|engineer|developer|analyst|scientist|manager|lead|architect|"
        r"consultant|associate|researcher|specialist|coordinator|director|officer|"
        r"fellow|scholar|trainee|executive|teaching assistant|research assistant)\b",
        re.IGNORECASE,
    )
    if not canonical and _TITLE_KW.search(text):
        return 0.0, ""

    return score, canonical


# ── 4. Main segmenter ─────────────────────────────────────────────────────────

HEADER_THRESHOLD = 2.5
UNKNOWN_SECTION_THRESHOLD = 3.0  # higher bar for unrecognised section names


def segment(extracted: dict) -> dict:
    """
    Split extracted lines into named sections.

    Name detection strategy:
      - Scan the first few lines of the document for the candidate name.
      - A name is a short line (1–5 words) with no contact signals.
      - It may appear BEFORE or AFTER contact info depending on resume layout.
      - Once found, it's placed into HEADER; the search stops.
      - All other high-scoring lines before the first real section header
        also go into HEADER (contact info, summary, etc.).
    """
    lines = extracted["lines"]
    if not lines:
        return {}

    median_size = _median_font_size(lines)

    # ── Pass 1: find the candidate name in the first 10 lines ────────────────
    # We look for the largest-font or _looks_like_name line near the top.
    # This is robust to name appearing before OR after contact info.
    name_idx = None
    top_lines = lines[:10]

    # First preference: largest font size in first 10 lines
    max_size = max((l["font_size"] for l in top_lines), default=0)
    for i, l in enumerate(top_lines):
        if l["font_size"] == max_size and _looks_like_name(l["text"]):
            name_idx = i
            break

    # Fallback: first line that looks like a name
    if name_idx is None:
        for i, l in enumerate(top_lines):
            if _looks_like_name(l["text"]):
                name_idx = i
                break

    # ── Pass 2: segment ───────────────────────────────────────────────────────
    sections: dict[str, list] = {"HEADER": []}
    current_section = "HEADER"
    first_real_section_seen = False

    for i, line in enumerate(lines):
        score, canonical = _score_line(line, median_size)

        # Always put the name line into HEADER regardless of its score
        if i == name_idx:
            sections["HEADER"].append(line)
            continue

        # Unknown sections need a higher score to avoid short bold lines
        # like "Languages" or "Tools" being mistaken for section headers
        effective_threshold = HEADER_THRESHOLD if canonical else UNKNOWN_SECTION_THRESHOLD

        if score >= effective_threshold:
            if not first_real_section_seen and not canonical:
                sections["HEADER"].append(line)
            else:
                first_real_section_seen = True
                if canonical:
                    section_name = canonical
                else:
                    # No alias match — try embedding classifier for unknown headers
                    try:
                        from section_classifier import classify_header
                        predicted = classify_header(line["text"].strip())
                        section_name = predicted if predicted else line["text"].upper().strip()
                    except Exception:
                        section_name = line["text"].upper().strip()
                current_section = section_name
                if current_section not in sections:
                    sections[current_section] = []
                # Header line itself is NOT appended to section content
        else:
            sections[current_section].append(line)

    return sections


def section_text(sections: dict, name: str) -> str:
    """Convenience: get all text for a section as a single string."""
    lines = sections.get(name, [])
    return "\n".join(l["text"] for l in lines)


# ── quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    pdf = sys.argv[1] if len(sys.argv) > 1 else "synthetic_resume.pdf"
    extracted = extract_pdf(pdf)
    sections = segment(extracted)

    print(f"Sections found: {list(sections.keys())}\n")
    print("=" * 60)
    for sec_name, lines in sections.items():
        print(f"\n── {sec_name} ({'empty' if not lines else f'{len(lines)} lines'})")
        for l in lines:
            print(f"   {l['font_size']:5.1f}  {'B' if l['is_bold'] else ' '}  {l['text'][:90]}")
