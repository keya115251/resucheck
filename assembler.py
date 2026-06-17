"""
assembler.py
------------
Step 5: Gap detection + final JSON assembly.

Input  : enriched entities dict from skill_enricher.enrich_skills()
Output : final structured output dict ready for the platform to consume

{
    "header":         {...},
    "education":      [...],
    "experience":     [...],
    "projects":       [...],
    "skills":         {...},
    "certifications": [...],
    "achievements":   [...],
    "skill_analysis": {
        "all_listed":  [...],
        "evidenced":   [...],
        "listed_only": [...],
        "implied":     [...]
    },
    "gaps": [
        {"severity": "high"|"medium"|"low", "message": str}
    ]
}
"""

import re
from datetime import datetime

from extractor import extract_pdf
from segmenter import segment
from entity_extractor import extract_entities
from skill_enricher import enrich_skills


# ── Gap detection rules ───────────────────────────────────────────────────────

_MECH_CIVIL_EE_GAP = re.compile(
    r"\b(mechanical|civil|structural|electrical|chemical|aerospace|aeronautical|"
    r"industrial|petroleum|metallurgy|biomedical|environmental|mining|"
    r"cad|simulation|ansys|solidworks|autocad|catia|staad|etabs|piping)\b",
    re.IGNORECASE
)
_BIO_GAP = re.compile(
    r"\b(biotechnology|biotech|bioinformatics|biochemistry|pharmacy|"
    r"microbiology|life sciences|biological)\b",
    re.IGNORECASE
)


def _branch_from_entities(entities: dict) -> str:
    """Return 'cs_ece', 'mech_civil_ee', 'bio', or 'other'."""
    edu_text = " ".join(
        " ".join(str(v) for v in e.values() if isinstance(v, str))
        for e in entities.get("education", [])
    )
    skill_cats = " ".join(entities.get("skills", {}).keys())
    exp_titles = " ".join(e.get("title","") for e in entities.get("experience", []))
    text = edu_text + " " + skill_cats + " " + exp_titles + " " + entities.get("profile","")

    if _CS_ECE_BRANCHES.search(text): return "cs_ece"
    if _MECH_CIVIL_EE_GAP.search(text): return "mech_civil_ee"
    if _BIO_GAP.search(text): return "bio"
    return "other"


def _detect_gaps(entities: dict) -> list[dict]:
    gaps = []
    now  = datetime.now()

    experience    = entities.get("experience", [])
    projects      = entities.get("projects", [])
    education     = entities.get("education", [])
    certifications= entities.get("certifications", [])
    achievements  = entities.get("achievements", [])
    header        = entities.get("header", {})
    skill_analysis= entities.get("skill_analysis", {})

    branch = _branch_from_entities(entities)
    is_cs_ece        = branch == "cs_ece"
    is_mech_civil_ee = branch == "mech_civil_ee"
    is_bio           = branch == "bio"

    # ── High severity ─────────────────────────────────────────────────────────

    # No internship / work experience
    if not experience:
        gaps.append({
            "severity": "high",
            "message": "No internship or work experience found. "
                       "Industry exposure is a strong differentiator for engineering students — "
                       "even a short internship or industrial training significantly strengthens your profile."
        })

    # Very few projects
    if len(projects) < 2:
        gaps.append({
            "severity": "high",
            "message": f"Only {len(projects)} project(s) found. "
                       "Recruiters expect at least 2–3 substantive projects that demonstrate "
                       "hands-on technical skills relevant to your target role."
        })

    # Student graduating soon with no internship
    for edu in education:
        year_end = edu.get("year_end", "")
        if year_end:
            yr_match = re.search(r"\d{4}", str(year_end))
            if yr_match:
                grad_year = int(yr_match.group())
                if grad_year >= now.year and not experience:
                    gaps.append({
                        "severity": "high",
                        "message": f"Expected graduation in {grad_year} with no internship on record. "
                                   "Most engineering roles expect at least one internship by final year."
                    })
                    break

    # ── Medium severity ───────────────────────────────────────────────────────

    # Skills listed without project evidence (exclude coursework topics)
    listed_only = skill_analysis.get("listed_only", [])
    coursework_set = {
        t.lower()
        for edu in entities.get("education", [])
        for t in edu.get("coursework", [])
    }
    listed_only_non_cw = [s for s in listed_only if s.lower() not in coursework_set]
    if listed_only_non_cw:
        gaps.append({
            "severity": "medium",
            "message": f"{len(listed_only_non_cw)} skill(s) listed without supporting evidence in projects or experience: "
                       f"{', '.join(listed_only_non_cw[:8])}{'...' if len(listed_only_non_cw) > 8 else ''}. "
                       "Back up claimed skills with a project or role that uses them."
        })

    # No quantified impact in experience bullets
    if experience:
        all_bullets = [b for exp in experience for b in exp.get("bullets", [])]
        quantified  = [b for b in all_bullets if re.search(
            r"\d+\s*%|\d+x|\$[\d,]+|\d+\s*(ms|fps|req|users|teams?|units?|hrs?|days?|weeks?)",
            b, re.IGNORECASE
        )]
        if all_bullets and len(quantified) == 0:
            if is_mech_civil_ee:
                example = ("e.g. 'reduced material waste by 15%', "
                           "'completed 50+ component drawings', 'improved load capacity by 20%'")
            elif is_bio:
                example = ("e.g. 'achieved 95% cell viability', "
                           "'processed 200+ samples', 'reduced assay time by 30%'")
            else:
                example = ("e.g. 'reduced processing time by 30%', "
                           "'handled 500+ daily requests', 'improved accuracy by 12%'")
            gaps.append({
                "severity": "medium",
                "message": f"No quantified impact in experience bullets. "
                           f"Numbers make bullets credible — {example}."
            })

    # Projects with no tech stack / tools listed
    projects_no_stack = [p["name"] for p in projects if not p.get("tech_stack")]
    if projects_no_stack:
        tool_word = "software or tools" if is_mech_civil_ee else "tech stack"
        gaps.append({
            "severity": "medium",
            "message": f"Project(s) with no {tool_word} listed: {', '.join(projects_no_stack[:3])}. "
                       "Always list what you used — recruiters and ATS systems scan for these keywords."
        })

    # Projects with very short descriptions
    thin_projects = [p["name"] for p in projects
                     if len(p.get("description", "").split()) < 20 and p.get("name")]
    if thin_projects:
        gaps.append({
            "severity": "medium",
            "message": f"Project(s) with thin descriptions: {', '.join(thin_projects[:3])}. "
                       "Add what you built, how you built it, and what the outcome was."
        })

    # ── Low severity ──────────────────────────────────────────────────────────

    # Hackathons mixed into certifications section
    from entity_extractor import _ACHIEVEMENT_KEYWORDS
    cert_names = [c.get("name", "") for c in entities.get("certifications", [])]
    mixed = [n for n in cert_names if _ACHIEVEMENT_KEYWORDS.search(n)]
    if mixed:
        gaps.append({
            "severity": "low",
            "message": "Competition wins and participation certificates are listed under Certifications. "
                       "Move them to an Achievements or Extracurriculars section — "
                       "ATS systems and recruiters treat these as different categories."
        })

    # Resume uses tables (bad for ATS)
    if entities.get("has_tables"):
        gaps.append({
            "severity": "low",
            "message": "Resume uses tables for layout. ATS systems often can't parse tables and will "
                       "skip or scramble the content. Use plain text sections instead."
        })

    # No certifications
    if not certifications:
        if is_mech_civil_ee:
            cert_examples = "CATIA, SolidWorks CAD, ANSYS courses, AutoCAD, or NPTEL engineering programs"
        elif is_bio:
            cert_examples = "NPTEL bioinformatics, Coursera genomics, or lab technique certifications"
        elif is_cs_ece:
            cert_examples = "AWS, Oracle, Coursera, NPTEL, or vendor programs"
        else:
            cert_examples = "Coursera, NPTEL, or any field-relevant vendor program"
        gaps.append({
            "severity": "low",
            "message": f"No certifications found. Relevant certifications — {cert_examples} — "
                       "signal self-driven learning and add ATS keywords."
        })

    # Missing contact fields
    contact_fields = ["email", "linkedin"]
    if is_cs_ece:
        contact_fields.append("github")
    missing_contact = [k for k in contact_fields if not header.get(k)]
    if missing_contact:
        suffix = "Include email and LinkedIn at minimum." if not is_cs_ece else "Include email, LinkedIn, and GitHub on every resume."
        gaps.append({
            "severity": "low",
            "message": f"Missing contact field(s): {', '.join(missing_contact)}. {suffix}"
        })

    # No location
    if not header.get("location"):
        gaps.append({
            "severity": "low",
            "message": "No location found. City and state help with location-based filtering on job portals like Naukri and LinkedIn."
        })

    # Implied skills not listed
    implied = skill_analysis.get("implied", [])
    if implied:
        gaps.append({
            "severity": "low",
            "message": f"Skills used in your projects but missing from the Skills section: "
                       f"{', '.join(implied[:8])}. "
                       "Adding these improves keyword matching in ATS screening."
        })

    return gaps


# ── Final assembler ───────────────────────────────────────────────────────────

# ── Per-field confidence scoring ──────────────────────────────────────────────
# Each heuristic returns 0.0 (bad), 0.5 (uncertain), or 1.0 (good)

_NAME_PATTERN    = re.compile(r"^[A-Za-z][a-zA-Z'\-\. ]{1,39}$")
_EMAIL_PATTERN   = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_PATTERN   = re.compile(r"(\+?91[\s\-]?)?[6-9]\d{9}")
_YEAR_VALID      = re.compile(r"20(1[5-9]|2[0-9]|3[0-5])")
_INST_KEYWORDS   = re.compile(
    r"\b(university|institute|college|school|iit|nit|bits|iim|cbit|vtu|anna|osmania)\b",
    re.IGNORECASE
)
_DEGREE_PATTERN  = re.compile(
    r"\b(b\.?e|b\.?tech|m\.?tech|b\.?sc|m\.?sc|mba|phd|bachelor|master|"
    r"class\s*(x|xii|10|12)|intermediate|sslc|hsc)\b",
    re.IGNORECASE
)
_TITLE_CLEAN     = re.compile(
    r"\b(intern(?:ship)?|engineer|developer|analyst|researcher|scientist|"
    r"consultant|associate|manager|lead|head|director)\b",
    re.IGNORECASE
)
_SENTENCE_START  = re.compile(r"\b(we |i |the |our |this |developed|built|created|worked)", re.IGNORECASE)


def _conf_header(h: dict) -> dict:
    """Confidence scores for each header field."""
    scores = {}

    # Name
    name = h.get("name", "")
    if not name:
        scores["name"] = 0.0
    elif _NAME_PATTERN.match(name) and 2 <= len(name.split()) <= 4:
        scores["name"] = 1.0
    elif len(name.split()) >= 2:
        scores["name"] = 0.5  # present but may be garbled
    else:
        scores["name"] = 0.0

    # Email
    email = h.get("email", "")
    scores["email"] = 1.0 if email and _EMAIL_PATTERN.match(email) else (0.5 if email else 0.0)

    # Phone
    phone = h.get("phone", "")
    scores["phone"] = 1.0 if phone and _PHONE_PATTERN.search(phone) else (0.5 if phone else 0.0)

    # LinkedIn / GitHub — just presence
    scores["linkedin"] = 1.0 if h.get("linkedin") else 0.0
    scores["github"]   = 1.0 if h.get("github")   else 0.0
    scores["location"] = 1.0 if h.get("location")  else 0.0

    overall = sum(scores.values()) / len(scores)
    return {"field_scores": scores, "confidence": round(overall, 2)}


def _conf_education(edu: list) -> dict:
    """Confidence scores for education entries."""
    if not edu:
        return {"field_scores": {}, "confidence": 0.0}

    entry_scores = []
    for e in edu:
        s = {}
        # Institution
        inst = e.get("institution", "")
        if inst and _INST_KEYWORDS.search(inst):
            s["institution"] = 1.0
        elif inst and 2 <= len(inst.split()) <= 8:
            s["institution"] = 0.5
        else:
            s["institution"] = 0.0

        # Degree
        deg = e.get("degree", "")
        if deg and _DEGREE_PATTERN.search(deg):
            s["degree"] = 1.0
        elif deg:
            s["degree"] = 0.5
        else:
            s["degree"] = 0.0

        # Year
        yr = str(e.get("year_end", ""))
        s["year"] = 1.0 if _YEAR_VALID.search(yr) else (0.5 if yr else 0.0)

        entry_scores.append(sum(s.values()) / len(s))

    overall = sum(entry_scores) / len(entry_scores)
    return {"entry_count": len(edu), "confidence": round(overall, 2)}


def _conf_experience(exp: list) -> dict:
    """Confidence scores for experience entries."""
    if not exp:
        return {"entry_count": 0, "confidence": 0.0}

    entry_scores = []
    for e in exp:
        s = {}
        # Title — should be short, contain a title keyword, no sentence structure
        title = e.get("title", "")
        title_words = len(title.split())
        if (title and _TITLE_CLEAN.search(title)
                and title_words <= 8
                and not _SENTENCE_START.search(title)):
            s["title"] = 1.0
        elif title and title_words <= 12 and not _SENTENCE_START.search(title):
            s["title"] = 0.5
        elif title:
            s["title"] = 0.2  # present but looks like description bleed
        else:
            s["title"] = 0.0

        # Company — should be short, no sentence structure
        company = e.get("company", "")
        company_words = len(company.split()) if company else 0
        if company and company_words <= 6 and not _SENTENCE_START.search(company):
            s["company"] = 1.0
        elif company and company_words <= 10:
            s["company"] = 0.5
        elif company:
            s["company"] = 0.2  # likely description bleed
        else:
            s["company"] = 0.0

        # Dates
        has_start = bool(e.get("date_start"))
        has_end   = bool(e.get("date_end"))
        if has_start and has_end:
            s["dates"] = 1.0
        elif has_start or has_end:
            s["dates"] = 0.5
        else:
            s["dates"] = 0.0

        # Bullets — have at least one non-trivial bullet
        bullets = [b for b in e.get("bullets", []) if len(b.split()) >= 5]
        s["bullets"] = 1.0 if len(bullets) >= 2 else (0.5 if len(bullets) == 1 else 0.0)

        entry_scores.append(sum(s.values()) / len(s))

    overall = sum(entry_scores) / len(entry_scores)
    return {"entry_count": len(exp), "confidence": round(overall, 2)}


def _conf_projects(proj: list) -> dict:
    """Confidence scores for project entries."""
    if not proj:
        return {"entry_count": 0, "confidence": 0.0}

    entry_scores = []
    for p in proj:
        s = {}
        # Name — short, title-case-ish, no sentence endings
        name = p.get("name", "")
        name_words = len(name.split())
        has_garble = any(len(w) > 20 for w in name.split())
        if name and name_words <= 8 and not name.endswith(".") and not has_garble:
            s["name"] = 1.0
        elif name and not has_garble:
            s["name"] = 0.5
        else:
            s["name"] = 0.0

        # Tech stack
        stack = p.get("tech_stack", [])
        s["tech_stack"] = 1.0 if len(stack) >= 2 else (0.5 if len(stack) == 1 else 0.0)

        # Description
        desc_words = len(p.get("description", "").split())
        s["description"] = 1.0 if desc_words >= 20 else (0.5 if desc_words >= 5 else 0.0)

        entry_scores.append(sum(s.values()) / len(s))

    overall = sum(entry_scores) / len(entry_scores)
    return {"entry_count": len(proj), "confidence": round(overall, 2)}


def _conf_skills(sk: dict) -> dict:
    """Confidence score for skills section."""
    skill_count = sum(len(v) for v in sk.values())
    has_categories = len(sk) > 1 or (len(sk) == 1 and "Other" not in sk)

    if skill_count >= 10 and has_categories:
        conf = 1.0
    elif skill_count >= 5:
        conf = 0.7
    elif skill_count >= 2:
        conf = 0.4
    else:
        conf = 0.0

    return {"skill_count": skill_count, "has_categories": has_categories, "confidence": round(conf, 2)}


def _conf_certifications(cert: list) -> dict:
    """Confidence score for certifications."""
    if not cert:
        return {"entry_count": 0, "confidence": 0.0}

    entry_scores = []
    for c in cert:
        s = {}
        # Name — should be a reasonable length, not garbled
        name = c.get("name", "")
        has_garble = any(len(w) > 20 for w in name.split())
        if name and not has_garble and len(name.split()) <= 10:
            s["name"] = 1.0
        elif name and not has_garble:
            s["name"] = 0.5
        else:
            s["name"] = 0.0

        # Issuer presence
        s["issuer"] = 1.0 if c.get("issuer") else 0.5

        # Year presence
        s["year"] = 1.0 if c.get("year") else 0.5

        entry_scores.append(sum(s.values()) / len(s))

    return {"entry_count": len(cert), "confidence": round(sum(entry_scores) / len(entry_scores), 2)}


def _conf_achievements(ach: list) -> dict:
    """Confidence score for achievements."""
    if not ach:
        return {"entry_count": 0, "confidence": 0.0}

    entry_scores = []
    for a in ach:
        words = a.split()
        has_garble = any(len(w) > 20 for w in words)
        word_count = len(words)

        if not has_garble and 3 <= word_count <= 30:
            score = 1.0
        elif not has_garble and word_count > 0:
            score = 0.5
        else:
            score = 0.0
        entry_scores.append(score)

    return {"entry_count": len(ach), "confidence": round(sum(entry_scores) / len(entry_scores), 2)}


def _conf_flat_list(items: list, section: str) -> dict:
    """Generic confidence for flat list sections (languages, leadership, extracurriculars)."""
    if not items:
        return {"entry_count": 0, "confidence": 0.0}

    clean = [i for i in items if i and not any(len(w) > 20 for w in i.split())]
    conf = 1.0 if len(clean) == len(items) else (0.5 if clean else 0.0)
    return {"entry_count": len(items), "confidence": conf}


def _compute_confidence(enriched: dict) -> dict:
    """
    Compute per-field extraction confidence scores for all sections.
    Returns a dict with section-level confidence (0.0–1.0) and field breakdowns.
    Intended for downstream consumers (LLM fallback routing, analytics, API).

    Sections weighted by importance for core resume evaluation:
      projects 30%, experience 20%, skills 20%, education 15%, header 15%
    Secondary sections (achievements, certifications, etc.) are scored but
    don't affect the overall — they're supplementary.
    """
    h      = enriched.get("header", {})
    edu    = enriched.get("education", [])
    exp    = enriched.get("experience", [])
    proj   = enriched.get("projects", [])
    sk     = enriched.get("skills", {})
    cert   = enriched.get("certifications", [])
    ach    = enriched.get("achievements", [])
    langs  = enriched.get("languages", [])
    extra  = enriched.get("extracurriculars", [])
    lead   = enriched.get("leadership", [])

    header_conf  = _conf_header(h)
    edu_conf     = _conf_education(edu)
    exp_conf     = _conf_experience(exp)
    proj_conf    = _conf_projects(proj)
    skills_conf  = _conf_skills(sk)
    cert_conf    = _conf_certifications(cert)
    ach_conf     = _conf_achievements(ach)
    lang_conf    = _conf_flat_list(langs, "languages")
    extra_conf   = _conf_flat_list(extra, "extracurriculars")
    lead_conf    = _conf_flat_list(lead, "leadership")

    # Overall: weighted average of core sections only
    weights = {"header": 0.15, "education": 0.15, "experience": 0.20,
               "projects": 0.30, "skills": 0.20}
    overall = (
        header_conf["confidence"]  * weights["header"]
        + edu_conf["confidence"]   * weights["education"]
        + exp_conf["confidence"]   * weights["experience"]
        + proj_conf["confidence"]  * weights["projects"]
        + skills_conf["confidence"]* weights["skills"]
    )

    return {
        "header":           header_conf,
        "education":        edu_conf,
        "experience":       exp_conf,
        "projects":         proj_conf,
        "skills":           skills_conf,
        "certifications":   cert_conf,
        "achievements":     ach_conf,
        "languages":        lang_conf,
        "extracurriculars": extra_conf,
        "leadership":       lead_conf,
        "overall":          round(overall, 2),
    }


def _compute_health(enriched: dict, gaps: list) -> dict:
    """
    Compute a per-section parse health indicator for the UI,
    plus per-field confidence scores for downstream routing.
    """
    health = {}

    h = enriched.get("header", {})
    edu  = enriched.get("education", [])
    exp  = enriched.get("experience", [])
    proj = enriched.get("projects", [])
    sk   = enriched.get("skills", {})
    cert = enriched.get("certifications", [])
    ach  = enriched.get("achievements", [])

    skill_count = sum(len(v) for v in sk.values())

    # Compute confidence scores
    conf = _compute_confidence(enriched)

    def _status(c: float) -> str:
        if c >= 0.7: return "green"
        if c >= 0.4: return "yellow"
        return "red"

    # Header
    contact_fields = sum(bool(h.get(f)) for f in ["name","email","phone","linkedin","github","location"])
    hc = conf["header"]["confidence"]
    health["header"] = {
        "status": _status(hc),
        "note": f"{contact_fields}/6 contact fields detected",
        "confidence": hc,
    }

    # Education
    ec = conf["education"]["confidence"]
    if not edu:
        health["education"] = {"status": "red",    "note": "Education section not detected",  "confidence": 0.0}
    else:
        health["education"] = {
            "status": _status(ec),
            "note": f"{len(edu)} entr{'y' if len(edu)==1 else 'ies'}"
                    + ("" if ec >= 0.7 else " — some fields low confidence"),
            "confidence": ec,
        }

    # Experience
    xc = conf["experience"]["confidence"]
    if not exp:
        health["experience"] = {"status": "yellow", "note": "No experience detected",          "confidence": 0.0}
    else:
        health["experience"] = {
            "status": _status(xc),
            "note": f"{len(exp)} role{'s' if len(exp)>1 else ''}"
                    + ("" if xc >= 0.7 else " — titles or company names may be inaccurate"),
            "confidence": xc,
        }

    # Projects
    pc = conf["projects"]["confidence"]
    if not proj:
        health["projects"] = {"status": "red",    "note": "No projects detected",              "confidence": 0.0}
    else:
        health["projects"] = {
            "status": _status(pc),
            "note": f"{len(proj)} projects"
                    + ("" if pc >= 0.7 else " — some names or stacks may be inaccurate"),
            "confidence": pc,
        }

    # Skills
    sc = conf["skills"]["confidence"]
    health["skills"] = {
        "status": _status(sc),
        "note": f"{skill_count} skills detected" if skill_count else "Skills section not detected",
        "confidence": sc,
    }

    # Certifications (no confidence scoring — simpler)
    health["certifications"] = {
        "status": "green" if cert else "yellow",
        "note": f"{len(cert)} certifications detected" if cert else "No certifications detected",
        "confidence": 1.0 if cert else 0.0,
    }

    # Overall parse score (0–100) — based on confidence not just presence
    weighted_conf = conf["overall"]
    score = round(weighted_conf * 100)
    high_gaps = sum(1 for g in gaps if g["severity"] == "high")
    score = max(0, score - high_gaps * 5)

    # No-spaces detection
    all_text = " ".join([
        e.get("description", "") for e in enriched.get("projects", [])
    ] + [
        b for ex in enriched.get("experience", []) for b in ex.get("bullets", [])
    ])
    long_tokens = [w for w in all_text.split() if len(w) > 20]
    health["no_spaces_warning"] = len(long_tokens) >= 3

    health["overall_score"] = score
    health["confidence"]    = conf  # full breakdown for downstream use

    return health



# ── Resume quality score ──────────────────────────────────────────────────────

_CS_ECE_BRANCHES = re.compile(
    r"\b(computer science|cse|it|information technology|"
    r"ece|electronics|electrical|ai|ml|artificial intelligence|"
    r"machine learning|data science|software|cyber)\b",
    re.IGNORECASE
)

_IMPACT_SIGNAL = re.compile(
    r"\d+\s*%|\d+x|\$[\d,]+|\d+\s*(ms|fps|req|users?|teams?|units?|hrs?|days?|weeks?|samples?|classes?)",
    re.IGNORECASE
)

_STRONG_ACH = re.compile(
    r"\b(winner|won|finalist|runner.up|first|second|third|top\s*\d+|"
    r"selected|national|international|gold|silver|bronze|rank\s*\d+|"
    r"merit|distinction|scholarship|best)\b",
    re.IGNORECASE
)

_WEAK_ACH = re.compile(
    r"\b(participated|attended|member|volunteer|completed|certificate of participation)\b",
    re.IGNORECASE
)


_GENERIC_PROJ_NAMES = re.compile(
    r"^(ml project|web app|website|application|project \d+|mini project|"
    r"major project|final year project|college project|my project|sample project|"
    r"deep learning|machine learning project|data science project)$",
    re.IGNORECASE
)


def _score_resume_quality(enriched: dict) -> dict:
    """
    Score resume quality on content depth, not just presence.
    Returns a dict with dimension scores, explanations, and overall 0-100.
    """
    projects     = enriched.get("projects", [])
    skills       = enriched.get("skills", {})
    skill_ana    = enriched.get("skill_analysis", {})
    experience   = enriched.get("experience", [])
    header       = enriched.get("header", {})
    achievements = enriched.get("achievements", [])
    education    = enriched.get("education", [])
    github_data  = enriched.get("github_data", {})

    # ── Detect branch ────────────────────────────────────────────────────────
    is_cs_ece = False
    is_mech_civil_ee = False
    _MECH_CIVIL_EE = re.compile(
        r"\b(mechanical|civil|structural|electrical|chemical|"
        r"aerospace|aeronautical|industrial|petroleum|metallurgy|"
        r"biomedical|environmental|mining)\b",
        re.IGNORECASE
    )
    # Build branch detection text from all education string fields + profile + experience titles
    # Search broadly since degree parsing sometimes misses the field
    _edu_text = " ".join(
        " ".join(str(v) for v in e.values() if isinstance(v, str))
        for e in education
    )
    _branch_text = (_edu_text + " " + enriched.get("profile", "") + " " +
                    " ".join(e.get("title", "") for e in enriched.get("experience", [])) + " " +
                    " ".join(enriched.get("skills", {}).keys()))

    if _CS_ECE_BRANCHES.search(_branch_text):
        is_cs_ece = True
    elif _MECH_CIVIL_EE.search(_branch_text):
        is_mech_civil_ee = True
    else:
        # Fallback: detect by skill category names (mech students have CAD, Simulation etc.)
        _MECH_SKILL_CATS = re.compile(
            r"\b(cad|simulation|cfd|fea|drafting|manufacturing|solidworks|ansys|"
            r"autocad|catia|staad|etabs|piping|structural design)\b",
            re.IGNORECASE
        )
        if _MECH_SKILL_CATS.search(_branch_text):
            is_mech_civil_ee = True

    # ── 1. Project Depth (0–30) ───────────────────────────────────────────────
    proj_score = 0.0
    thin_descs, missing_stacks, generic_names = [], [], []

    for p in projects[:5]:
        pts = 0.0
        desc_words = len(p.get("description", "").split())
        stack = p.get("tech_stack", [])
        name  = p.get("name", "")

        # Description depth
        if desc_words >= 40:   pts += 1.0
        elif desc_words >= 20: pts += 0.6
        elif desc_words >= 5:  pts += 0.2
        else: thin_descs.append(name or "Unnamed")

        # Tools/stack — lower bar for non-CS (1-2 specialist tools = good)
        stack_full = 4 if is_cs_ece else 2
        stack_good = 2 if is_cs_ece else 1
        if len(stack) >= stack_full:   pts += 1.0
        elif len(stack) >= stack_good: pts += 0.6
        elif len(stack) >= 1:          pts += 0.3
        else: missing_stacks.append(name or "Unnamed")

        # Generic name penalty
        if name and _GENERIC_PROJ_NAMES.match(name.strip()):
            pts *= 0.5
            generic_names.append(name)
        elif name and len(name.split()) <= 8 and not any(len(w) > 20 for w in name.split()):
            pts += 0.3

        proj_score += pts

    # Skill-to-project imbalance penalty
    all_listed = skill_ana.get("all_listed", [])
    skill_count = len(all_listed)
    proj_count  = len(projects)
    imbalance_penalty = 0
    if skill_count > 20 and proj_count <= 1:
        imbalance_penalty = 8
    elif skill_count > 15 and proj_count <= 2:
        imbalance_penalty = 4

    proj_max = 3 * 2.3
    proj_pts = max(0, min(round((proj_score / proj_max) * 30) - imbalance_penalty, 30))

    # Explanation
    proj_notes = []
    if proj_count == 0:
        proj_notes.append("No projects found — this is the biggest gap on your resume.")
    elif proj_count < 3:
        proj_notes.append(f"You have {proj_count} project{'s' if proj_count > 1 else ''} — aim for 3+ to show range.")
    if thin_descs:
        proj_notes.append(f"Thin descriptions on: {', '.join(thin_descs[:2])}. Add methodology, tools, and outcomes.")
    if missing_stacks:
        tool_label = "tools or software" if is_mech_civil_ee else "tech stack"
        proj_notes.append(f"No {tool_label} listed for: {', '.join(missing_stacks[:2])}. "
                          "Always list the tools used — recruiters scan for these keywords.")
    if generic_names:
        proj_notes.append(f"Generic project names like \"{generic_names[0]}\" don't stand out — give it a specific name.")
    if imbalance_penalty:
        proj_notes.append("Many skills listed but few projects to back them up — adds credibility risk.")
    if not proj_notes:
        proj_notes.append("Projects look solid — good descriptions and tools listed.")

    # ── 2. Skill Credibility (0–25) ───────────────────────────────────────────
    evidenced   = skill_ana.get("evidenced", [])
    listed_only = skill_ana.get("listed_only", [])

    ev_ratio    = len(evidenced) / len(all_listed) if all_listed else 0.0
    skill_cats  = [c for c in skills.keys() if c.lower() != "coursework"]
    # Field-relative target: CS/ECE needs 4+ categories, Mech/Civil/EE needs 2+
    cat_target  = 4 if is_cs_ece else 2
    cat_breadth = min(len(skill_cats) / cat_target, 1.0)

    skill_pts = round((ev_ratio * 0.65 + cat_breadth * 0.35) * 25)

    skill_notes = []
    if not all_listed:
        skill_notes.append("No skills section found.")
    elif ev_ratio < 0.5:
        skill_notes.append(f"Only {len(evidenced)}/{len(all_listed)} skills are backed by project evidence. "
                           f"Either add projects that use {', '.join(listed_only[:3])} or remove them.")
    elif ev_ratio < 0.8:
        skill_notes.append(f"{len(listed_only)} skill(s) have no project evidence: {', '.join(listed_only[:3])}.")
    else:
        skill_notes.append("Most skills are backed by project evidence — good.")
    if len(skill_cats) < cat_target:
        if is_mech_civil_ee:
            skill_notes.append("Skills are narrow — try to show breadth across CAD, simulation, and other tools relevant to your field.")
        else:
            skill_notes.append("Skills are narrow — try to show breadth across languages, frameworks, and tools.")
    else:
        skill_notes.append(f"Good breadth across {len(skill_cats)} skill categories.")

    # ── 3. Experience Quality (0–20) ──────────────────────────────────────────
    exp_pts = 0
    exp_notes = []

    if experience:
        internship_pts = 14 if is_mech_civil_ee else 10
        quantify_pts   = 6  if is_mech_civil_ee else 10
        exp_pts += internship_pts

        all_bullets = [b for e in experience for b in e.get("bullets", [])]
        quantified  = [b for b in all_bullets if _IMPACT_SIGNAL.search(b)]
        quant_ratio = len(quantified) / max(len(all_bullets), 1) if all_bullets else 0
        exp_pts    += round(quant_ratio * quantify_pts)
        exp_pts     = min(exp_pts, 20)

        if quant_ratio == 0:
            if is_mech_civil_ee:
                exp_notes.append("No quantified impact in bullets. Even approximate numbers help — "
                                 "e.g. 'reduced material waste by 15%', 'handled 50+ drawings'.")
            else:
                exp_notes.append("No quantified impact in your experience bullets. "
                                 "Add numbers — %, accuracy, scale, time saved — to make them concrete.")
        elif quant_ratio < 0.4:
            exp_notes.append(f"Only {len(quantified)} of {len(all_bullets)} bullets have measurable impact. "
                             "Try to quantify more — even rough numbers help.")
        else:
            exp_notes.append("Good use of numbers and metrics in experience bullets.")
    else:
        exp_notes.append("No internship or work experience found. "
                         "Even a short internship or industrial training significantly strengthens your profile.")

    # ── 4. Profile Completeness (0–15) ────────────────────────────────────────
    profile_pts = 0
    missing_fields = []
    if header.get("email"):    profile_pts += 3
    else: missing_fields.append("email")
    if header.get("phone"):    profile_pts += 2
    else: missing_fields.append("phone")
    if header.get("linkedin"): profile_pts += 4
    else: missing_fields.append("LinkedIn")
    if header.get("location"): profile_pts += 2
    else: missing_fields.append("location")
    if header.get("github"):
        profile_pts += 4 if is_cs_ece else 2
    elif is_cs_ece:
        missing_fields.append("GitHub")

    profile_pts = min(profile_pts, 15)

    profile_notes = []
    if missing_fields:
        profile_notes.append(f"Missing from contact info: {', '.join(missing_fields)}.")
    else:
        profile_notes.append("Contact info is complete.")
    if is_cs_ece and not header.get("github"):
        profile_notes.append("Adding a GitHub profile is strongly recommended for CS/ECE roles.")
    elif not is_cs_ece and header.get("github"):
        profile_notes.append("GitHub is a nice addition — it shows initiative beyond your field.")

    # ── 5. Achievements Quality (0–10) ────────────────────────────────────────
    ach_pts = 0
    strong_achs, weak_achs = [], []
    for a in achievements:
        if _STRONG_ACH.search(a):
            ach_pts += 3
            strong_achs.append(a[:50])
        elif not _WEAK_ACH.search(a):
            ach_pts += 1
        else:
            weak_achs.append(a[:50])

    ach_pts = min(ach_pts, 10)

    ach_notes = []
    if not achievements:
        if is_mech_civil_ee:
            ach_notes.append("No achievements listed. Competition wins, design challenge placements, or scholarships add credibility.")
        else:
            ach_notes.append("No achievements listed. Hackathon placements, scholarships, or competition wins add credibility.")
    elif strong_achs:
        ach_notes.append(f"{len(strong_achs)} strong achievement(s) — finalist/winner/selected entries carry good weight.")
        if weak_achs:
            ach_notes.append(f"{len(weak_achs)} participation-only entries — these add little weight. "
                             "Focus on outcomes and placements.")
    else:
        ach_notes.append("Achievements listed are mostly participation-only. "
                         "Highlight any wins, selections, or top placements instead.")

    # ── GitHub bonus ──────────────────────────────────────────────────────────
    github_bonus = 0
    if is_cs_ece and github_data and "error" not in github_data:
        verified = [m for m in github_data.get("project_matches", []) if m.get("verified")]
        if len(verified) >= 2: github_bonus = 5
        elif len(verified) == 1: github_bonus = 3

    # ── Total ─────────────────────────────────────────────────────────────────
    total = min(proj_pts + skill_pts + exp_pts + profile_pts + ach_pts + github_bonus, 100)

    if total >= 82:   label = "Strong"
    elif total >= 68: label = "Promising"
    elif total >= 52: label = "Developing"
    else:             label = "Needs Work"

    return {
        "total":   total,
        "label":   label,
        "breakdown": {
            "project_depth":        proj_pts,
            "skill_credibility":    skill_pts,
            "experience_quality":   exp_pts,
            "profile_completeness": profile_pts,
            "achievements_quality": ach_pts,
            "github_bonus":         github_bonus,
        },
        "explanations": {
            "projects":     proj_notes,
            "skills":       skill_notes,
            "experience":   exp_notes,
            "profile":      profile_notes,
            "achievements": ach_notes,
        },
        "is_cs_ece":       is_cs_ece,
        "is_mech_civil_ee": is_mech_civil_ee,
    }


def assemble(enriched: dict) -> dict:
    """
    Run gap detection and return the final output dict.

    Parameters
    ----------
    enriched : dict
        Output from skill_enricher.enrich_skills()

    Returns
    -------
    Final structured dict with gaps and health indicator added.
    """
    gaps = _detect_gaps(enriched)

    # Sort: high → medium → low
    severity_order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: severity_order.get(g["severity"], 99))

    health = _compute_health(enriched, gaps)

    quality = _score_resume_quality(enriched)

    return {
        "header":           enriched.get("header", {}),
        "profile":          enriched.get("profile", ""),
        "quality_score":    quality,
        "education":        enriched.get("education", []),
        "experience":       enriched.get("experience", []),
        "projects":         enriched.get("projects", []),
        "skills":           enriched.get("skills", {}),
        "certifications":   enriched.get("certifications", []),
        "achievements":     enriched.get("achievements", []),
        "languages":        enriched.get("languages", []),
        "extracurriculars": enriched.get("extracurriculars", []),
        "leadership":       enriched.get("leadership", []),
        "skill_analysis":   enriched.get("skill_analysis", {}),
        "gaps":             gaps,
        "has_tables":       enriched.get("has_tables", False),
        "health":           health,
    }


# ── Full pipeline runner ──────────────────────────────────────────────────────

def parse_resume(file_path: str, use_llm: bool = False, llm_threshold: float = 0.6) -> dict:
    """
    Run the full parsing pipeline on a PDF or DOCX file.
    Single entry point for external integration.

    Parameters
    ----------
    file_path : str
        Path to the resume file (.pdf or .docx).
    use_llm : bool
        If True, route low-confidence sections through a local Ollama model
        for re-extraction. Requires Ollama running locally with llama3.1:8b pulled.
        See llm_enricher.py. Default False — rule-based only.
    llm_threshold : float
        Confidence threshold below which a section gets LLM re-extraction.

    Returns
    -------
    Final structured dict.
    """
    from pathlib import Path
    ext = Path(file_path).suffix.lower()

    if ext == ".docx":
        from docx_extractor import extract_docx
        extracted = extract_docx(file_path)
    elif ext == ".pdf":
        extracted = extract_pdf(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Expected .pdf or .docx")

    sections = segment(extracted)
    entities = extract_entities(sections)
    # Pass file-level metadata through the pipeline
    entities["has_tables"] = extracted.get("has_tables", False)
    enriched = enrich_skills(entities)
    final    = assemble(enriched)

    # Optional: GitHub enrichment (non-blocking — skipped if unreachable)
    try:
        from github_enricher import enrich_github
        final = enrich_github(final)
    except Exception:
        pass

    # Optional: LLM enrichment for low-confidence sections (non-blocking)
    if use_llm:
        try:
            from llm_enricher import enrich_with_llm
            final = enrich_with_llm(final, sections, threshold=llm_threshold)
        except Exception as e:
            final["_llm_enrichment"] = {"error": str(e)}

    return final


# ── quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    import sys
    test_file = sys.argv[1] if len(sys.argv) > 1 else "synthetic_resume.pdf"
    result = parse_resume(test_file)

    # Pretty print gaps
    print("=" * 60)
    print("GAPS")
    print("=" * 60)
    for gap in result["gaps"]:
        icon = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(gap["severity"], "•")
        print(f"\n{icon} [{gap['severity'].upper()}]")
        print(f"   {gap['message']}")

    # Print skill analysis summary
    sa = result["skill_analysis"]
    print("\n" + "=" * 60)
    print("SKILL ANALYSIS")
    print("=" * 60)
    print(f"  Evidenced   ({len(sa['evidenced'])}): {', '.join(sa['evidenced'])}")
    print(f"  Listed only ({len(sa['listed_only'])}): {', '.join(sa['listed_only'])}")
    print(f"  Implied     ({len(sa['implied'])}): {', '.join(sa['implied'][:8])}")

    # Full JSON
    print("\n" + "=" * 60)
    print("FULL OUTPUT JSON")
    print("=" * 60)
    print(json.dumps(result, indent=2))
