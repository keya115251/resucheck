# Resume Parser API — Response Schema

**Base URL:** `http://localhost:8000` (dev) / WeXL production URL  
**Content-Type:** `application/json`

---

## Endpoints

### `POST /parse`
Upload a resume and receive structured JSON.

**Request:** `multipart/form-data`
```
file: <PDF or DOCX, max 10MB>
```

**Response:** See schema below.

---

### `GET /health`
```json
{ "status": "ok", "service": "resume-parser" }
```

---

### `GET /schema`
Returns this schema as JSON.

---

## Response Fields

### `header` — object
Contact information from the resume header.

| Field | Type | Notes |
|---|---|---|
| `name` | string | Full name |
| `email` | string | |
| `phone` | string | Indian format (+91 XXXXXXXXXX) |
| `linkedin` | string | URL or handle |
| `github` | string | URL or handle |
| `location` | string | City, State |

All fields are strings. Empty string `""` if not found.

---

### `profile` — string
Profile/summary text. Empty string if not present.

---

### `education` — array
```json
[
  {
    "degree":      "B.E. in Artificial Intelligence and ML",
    "institution": "Chaitanya Bharathi Institute of Technology",
    "year_start":  "2023",
    "year_end":    "2027",
    "gpa":         "9.35",
    "percentage":  "",
    "location":    "Hyderabad",
    "coursework":  ["Machine Learning", "Data Structures", "Operating Systems"]
  }
]
```
`gpa` and `percentage` are mutually exclusive. `coursework` may be empty `[]`.

---

### `experience` — array
```json
[
  {
    "title":      "Machine Learning Intern",
    "company":    "WeXL AI Pvt Ltd",
    "date_start": "June 2026",
    "date_end":   "Current",
    "location":   "Hyderabad",
    "bullets":    [
      "Built a resume parser that reduced LLM costs by 40%.",
      "Worked on testing the platform and provided regular feedback."
    ]
  }
]
```

---

### `projects` — array
```json
[
  {
    "name":        "Deepfake Voice Detection System",
    "tech_stack":  ["Python", "Wav2Vec2", "PyTorch", "Deep Learning"],
    "description": "Built a multilingual binary classifier to distinguish AI-generated speech..."
  }
]
```

---

### `skills` — object
Keys are category names, values are arrays of skill strings.
```json
{
  "Languages":  ["Python", "Java"],
  "ML / DL":    ["PyTorch", "TensorFlow", "scikit-learn"],
  "Tools":      ["Git", "Jupyter", "Power BI"],
  "Coursework": ["Machine Learning", "Operating Systems"]
}
```
`Coursework` category is academic — sourced from education section, not claimed proficiency.

---

### `certifications` — array
```json
[
  {
    "name":   "Oracle OCI AI Foundations Associate",
    "issuer": "Oracle",
    "year":   "2025"
  }
]
```

---

### `achievements` — array of strings
```json
[
  "Finalist — Hackatron (Top 50), IIITM Gwalior 2024",
  "Won multiple Battle of the Bands competitions at IIT Hyderabad"
]
```

---

### `languages` — array of strings
Spoken/written languages. Empty `[]` if no Languages section.
```json
["English", "Telugu", "Hindi"]
```

---

### `leadership` — array of strings
```json
["CBIT — Head — Rocketry Department", "CBIT — Vice President — Music Club"]
```

---

### `extracurriculars` — array of strings
```json
["Robotics and Innovation Club — Joint Secretary"]
```

---

### `skill_analysis` — object
Classifies listed skills by evidence in project/experience text.

| Field | Type | Description |
|---|---|---|
| `all_listed` | string[] | All skills from the Skills section |
| `evidenced` | string[] | Skills backed by project or experience text |
| `listed_only` | string[] | Skills listed but with no project evidence |
| `implied` | string[] | Skills found in projects but not listed |

```json
{
  "all_listed":  ["PyTorch", "TensorFlow", "Docker"],
  "evidenced":   ["PyTorch", "TensorFlow"],
  "listed_only": ["Docker"],
  "implied":     ["FastAPI", "ONNX"]
}
```

---

### `gaps` — array
Detected resume gaps with actionable advice.

| Field | Type | Values |
|---|---|---|
| `severity` | string | `"high"` / `"medium"` / `"low"` |
| `message` | string | Human-readable, field-aware advice |

```json
[
  {
    "severity": "high",
    "message": "No internship or work experience found. Even a short internship significantly strengthens your profile."
  },
  {
    "severity": "medium",
    "message": "3 skills listed without project evidence: Docker, Kubernetes, Redis."
  }
]
```

Sorted high → medium → low. Messages are adapted to the student's engineering branch (CS vs Mech vs Bio etc.).

---

### `quality_score` — object
Resume quality score based on content depth — not parse quality.

| Field | Type | Description |
|---|---|---|
| `total` | int | 0–100 overall score |
| `label` | string | `"Strong"` / `"Promising"` / `"Developing"` / `"Needs Work"` |
| `is_cs_ece` | bool | CS/ECE branch detected |
| `is_mech_civil_ee` | bool | Mech/Civil/EE branch detected |

**Thresholds:** Strong ≥82 · Promising ≥68 · Developing ≥52 · Needs Work <52

**`breakdown`** — dimension scores:
| Dimension | Max | What it measures |
|---|---|---|
| `project_depth` | 30 | Description length, tools listed, project name quality |
| `skill_credibility` | 25 | Evidence ratio + category breadth |
| `experience_quality` | 20 | Internship presence + quantified bullets |
| `profile_completeness` | 15 | Contact fields (GitHub weighted for CS/ECE only) |
| `achievements_quality` | 10 | Signal strength (winner > participant) |
| `github_bonus` | 5 | CS/ECE only, verified GitHub projects |

**`explanations`** — per-dimension feedback (field-aware):
```json
{
  "projects":     ["Projects look solid — good descriptions and tools listed."],
  "skills":       ["Most skills are backed by project evidence — good.", "Skills are narrow — try to show breadth."],
  "experience":   ["No quantified impact in your experience bullets. Add numbers..."],
  "profile":      ["Contact info is complete."],
  "achievements": ["2 strong achievements — finalist/winner entries carry good weight."]
}
```

---

### `health` — object
Parse quality indicator. Use `health.confidence` for LLM fallback routing.

**`health.overall_score`** — int (0–100). Parse confidence, not resume quality.

**`health.no_spaces_warning`** — bool. True if PDF has encoding issues (missing spaces). Prompt user to re-export.

**`health.confidence`** — per-section extraction confidence (0.0–1.0):
```json
{
  "overall":    0.72,
  "header":     { "confidence": 0.83, "field_scores": { "name": 1.0, "email": 1.0, "phone": 1.0, "linkedin": 1.0, "github": 1.0, "location": 0.0 } },
  "education":  { "confidence": 0.61, "entry_count": 3 },
  "experience": { "confidence": 0.30, "entry_count": 1 },
  "projects":   { "confidence": 0.72, "entry_count": 4 },
  "skills":     { "confidence": 0.91, "skill_count": 22 },
  "certifications": { "confidence": 0.85, "entry_count": 3 },
  "achievements":   { "confidence": 0.90, "entry_count": 5 }
}
```

> **LLM routing signal:** Sections with `confidence < 0.6` benefit from LLM re-extraction.
> Experience almost always qualifies (avg 0.19). Skills rarely does (avg 0.91).

---

### `github_data` — object | null
`null` if no GitHub URL in resume or GitHub is unreachable.

```json
{
  "username":      "keya115251",
  "public_repos":  12,
  "followers":     8,
  "total_stars":   3,
  "top_languages": ["Python", "JavaScript"],
  "project_matches": [
    {
      "project":    "Deepfake Voice Detection System",
      "repo":       "deepfake-voice-detection",
      "repo_url":   "https://github.com/keya115251/deepfake-voice-detection",
      "confidence": 0.95,
      "verified":   true,
      "partial":    false,
      "signals":    { "name": 0.95, "desc": 0.40, "stack": 0.60 }
    },
    {
      "project":    "Some Unlisted Project",
      "repo":       null,
      "repo_url":   null,
      "confidence": 0.21,
      "verified":   false,
      "partial":    false,
      "signals":    {}
    }
  ],
  "implied_from_github": ["FastAPI", "Docker"]
}
```

---

### `_meta` — object
Request metadata added by the API (not from the resume).

| Field | Type | Description |
|---|---|---|
| `filename` | string | Original uploaded filename |
| `size_kb` | float | File size in KB |
| `parse_time_s` | float | Wall-clock parse time in seconds |

---

## Error Responses

| Status | Condition |
|---|---|
| 400 | Unsupported file type |
| 413 | File exceeds 10MB |
| 500 | Parse failed (malformed file, encoding error, etc.) |

```json
{ "detail": "Unsupported file type '.txt'. Upload a PDF or DOCX." }
```

---

## Notes for Frontend

- All string fields return `""` (empty string) when not found — never `null`. Check `field !== ""`.
- All array fields return `[]` when empty — never `null`.
- `github_data` is the only top-level field that can be `null`.
- `quality_score.explanations` strings are plain text, suitable for direct display.
- `gaps[].message` strings are complete sentences — display as-is, no further formatting needed.
- `health.no_spaces_warning: true` means the PDF had encoding issues — show the user a re-export prompt.
- Parse time is typically 2–8 seconds depending on resume length and whether GitHub fetch is triggered.
