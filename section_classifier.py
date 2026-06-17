from __future__ import annotations

import re

def normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


SECTION_EXAMPLES = {
    "PROFILE": [
        "summary", "professional summary", "career summary", "profile",
        "profile summary", "personal profile", "professional profile",
        "about me", "about myself", "who i am", "introduction",
        "personal statement", "bio", "overview", "professional overview",
        "career objective", "objective", "professional objective",
        "executive summary", "snapshot",
    ],
    "EDUCATION": [
        "education", "my education", "academic background",
        "educational background", "qualifications", "academic qualifications",
        "academic history", "schooling", "studies", "degrees",
        "academic credentials", "formal education", "academic record",
    ],
    "EXPERIENCE": [
        "experience", "work experience", "professional experience",
        "employment history", "work history", "career history",
        "job experience", "internship", "internship details",
        "internship experience", "professional background",
        "industry experience", "practical experience",
        "industrial experience", "hands on experience",
    ],
    "PROJECTS": [
        "projects", "my projects", "academic projects", "technical projects",
        "personal projects", "engineering projects", "key projects",
        "what ive built", "what i have built", "portfolio",
        "project portfolio", "project showcase", "selected projects",
        "development work", "applications developed", "builds",
    ],
    "SKILLS": [
        "skills", "technical skills", "core skills", "key skills",
        "core competencies", "competencies", "technical expertise",
        "areas of expertise", "tools and technologies", "technologies",
        "tech stack", "programming languages", "technical toolkit",
        "what i know", "what i can do", "strengths", "specializations",
    ],
    "CERTIFICATIONS": [
        "certifications", "certificates", "professional certifications",
        "credentials", "licenses and certifications", "courses and certifications",
        "completed courses", "online certifications", "professional development",
        "training and certifications",
    ],
    "ACHIEVEMENTS": [
        "achievements", "accomplishments", "awards", "awards and achievements",
        "honours", "honors", "recognition", "distinctions",
        "competitive achievements", "academic achievements", "hackathons",
        "hackathons participated", "competitions", "milestones",
        "awards and honors", "achievement highlights",
    ],

    "EXTRACURRICULARS": [
        "extracurricular activities", "extracurriculars",
        "extra curricular activities", "co curricular activities",
        "co-curricular activities", "activities", "student activities",
        "campus involvement", "beyond academics", "club activities",
        "community activities", "volunteer activities",
        "interests", "my interests", "areas of interest",
        "personal interests", "hobbies", "hobbies and interests",
    ],

    "LEADERSHIP": [
        "leadership", "leadership roles", "leadership experience",
        "positions of responsibility", "por", "responsibilities",
        "campus leadership", "club leadership", "coordinator roles",
        "committee roles", "organizational experience",
        "management experience", "student governance",
        "event management", "student leadership",
    ],
    "PUBLICATIONS": [
        "publications", "research publications", "published work",
        "research papers", "research work", "conference papers",
        "journal papers", "technical papers", "academic publications",
    ],
    "LANGUAGES": [
        "languages", "language skills", "languages known",
        "language proficiency", "spoken languages", "linguistic skills",
        "languages i speak", "multilingual skills",
    ],
}

# Map classifier output to the canonical names used by the rest of the pipeline
_CLASSIFIER_TO_CANONICAL = {
    "PROFILE":          "PROFILE",
    "EDUCATION":        "EDUCATION",
    "EXPERIENCE":       "EXPERIENCE",
    "PROJECTS":         "PROJECTS",
    "SKILLS":           "SKILLS",
    "CERTIFICATIONS":   "CERTIFICATIONS",
    "ACHIEVEMENTS":     "ACHIEVEMENTS",
    "PUBLICATIONS":     "PUBLICATIONS",
    "LANGUAGES":        "LANGUAGES",
    "EXTRACURRICULARS": "EXTRACURRICULARS",
    "LEADERSHIP":       "LEADERSHIP",
}

CONFIDENCE_THRESHOLD = 0.35

_model = None
_section_embeddings = None
_section_names = None


def _load() -> None:
    global _model, _section_embeddings, _section_names
    if _model is not None:
        return
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        _section_names = list(SECTION_EXAMPLES.keys())
        _section_embeddings = {}
        for section, phrases in SECTION_EXAMPLES.items():
            phrases = [normalize(p) for p in phrases]
            embs = _model.encode(phrases, convert_to_tensor=True)
            _section_embeddings[section] = embs.mean(dim=0)
    except Exception as e:
        _model = False
        print(f"[section_classifier] Could not load model: {e}")


def classify_header(text: str) -> str | None:
    """
    Classify an unknown section header into a canonical pipeline section name.
    Returns the canonical name (e.g. SUMMARY, ACHIEVEMENTS) or None.
    """
    _load()
    if not _model:
        return None
    try:
        from sentence_transformers import util
        query_emb = _model.encode(normalize(text), convert_to_tensor=True)
        best_section, best_score = None, 0.0
        for section in _section_names:
            score = float(util.cos_sim(query_emb, _section_embeddings[section]))
            if score > best_score:
                best_score = score
                best_section = section
        if best_score >= CONFIDENCE_THRESHOLD and best_section:
            return _CLASSIFIER_TO_CANONICAL.get(best_section, best_section)
        return None
    except Exception:
        return None


if __name__ == "__main__":
    test_cases = [
        ("HACKATHONS PARTICIPATED",       "ACHIEVEMENTS"),
        ("WHAT I'VE BUILT",               "PROJECTS"),
        ("WORK HISTORY",                  "EXPERIENCE"),
        ("ACADEMIC BACKGROUND",           "EDUCATION"),
        ("ACCOMPLISHMENTS",               "ACHIEVEMENTS"),
        ("CORE COMPETENCIES",             "SKILLS"),
        ("PROFILE SUMMARY",               "SUMMARY"),
        ("INTERNSHIP DETAILS",            "EXPERIENCE"),
        ("WEBSITES & PORTFOLIOS",         "PROJECTS"),
        ("CO-CURRICULAR ACTIVITIES",      "ACHIEVEMENTS"),
        ("STRENGTHS & PERSONAL TRAITS",   "SKILLS"),
        ("ADDITIONAL INFORMATION",        "ACHIEVEMENTS"),
        ("RESEARCH WORK",                 "PUBLICATIONS"),
        ("TECHNICAL EXPERTISE",           "SKILLS"),
        ("CAMPUS INVOLVEMENT",            "ACHIEVEMENTS"),
        ("LANGUAGES KNOWN",               "LANGUAGES"),
        ("POSITIONS OF RESPONSIBILITY",   "ACHIEVEMENTS"),
        ("Machine Learning Intern",       None),
        ("Python, Java, C++",             None),
        ("Chaitanya Bharathi Institute",  None),
    ]

    print("Loading model...")
    _load()
    print(f"Model loaded. Testing {len(test_cases)} cases:\n")

    correct = 0
    for text, expected in test_cases:
        result = classify_header(text)
        status = "✓" if result == expected else "✗"
        if result == expected:
            correct += 1
        print(f"  {status} '{text[:40]:<40}' → {str(result):<15} (expected {str(expected)})")
    print(f"\nAccuracy: {correct}/{len(test_cases)} = {correct/len(test_cases)*100:.0f}%")
