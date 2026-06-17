"""
api.py
------
FastAPI wrapper around the resume parser pipeline.
Exposes parse_resume() as a REST endpoint for WeXL's React frontend.

Usage:
    pip install fastapi uvicorn python-multipart
    uvicorn api:app --host 0.0.0.0 --port 8000

Endpoints:
    POST /parse     — upload a resume PDF or DOCX, returns structured JSON
    GET  /health    — service health check
    GET  /schema    — JSON schema documentation
"""

import os
import shutil
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from assembler import parse_resume


# ── App setup ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Resume Parser API",
    description="Structured resume extraction with quality scoring and gap detection.",
    version="1.0.0",
)

# Allow WeXL's React frontend to call this API
# Update origins to match WeXL's actual domain in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # restrict to WeXL domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}
MAX_FILE_SIZE_MB = 10


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Service health check."""
    return {"status": "ok", "service": "resume-parser"}


@app.post("/parse")
async def parse(file: UploadFile = File(...)):
    """
    Parse a resume PDF or DOCX file.

    Accepts:    multipart/form-data with a file field
    Returns:    structured JSON (see /schema for full field reference)
    """
    # Validate extension
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Upload a PDF or DOCX."
        )

    # Read and size-check
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f} MB). Maximum is {MAX_FILE_SIZE_MB} MB."
        )

    # Write to temp file
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        t0 = time.perf_counter()
        result = parse_resume(tmp_path)
        elapsed = round(time.perf_counter() - t0, 2)

        # Attach metadata
        result["_meta"] = {
            "filename":    file.filename,
            "size_kb":     round(len(content) / 1024, 1),
            "parse_time_s": elapsed,
        }

        return JSONResponse(content=result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Parse failed: {str(e)}")

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.unlink(tmp_path)
            except: pass


@app.get("/schema")
def schema():
    """
    JSON schema documentation.
    Returns a description of every field in the /parse response.
    """
    return RESPONSE_SCHEMA


# ── Schema documentation ───────────────────────────────────────────────────────

RESPONSE_SCHEMA = {
    "description": "Structured resume parse result",
    "fields": {

        "header": {
            "type": "object",
            "description": "Candidate contact information extracted from the resume header",
            "fields": {
                "name":     {"type": "string", "example": "Keya Chembuli"},
                "email":    {"type": "string", "example": "keya@email.com"},
                "phone":    {"type": "string", "example": "+91 9100753081"},
                "linkedin": {"type": "string", "example": "linkedin.com/in/keya-chembuli"},
                "github":   {"type": "string", "example": "github.com/keya115251"},
                "location": {"type": "string", "example": "Hyderabad, Telangana"},
            }
        },

        "profile": {
            "type": "string",
            "description": "Profile/summary text from the resume. Empty string if not present.",
            "example": "AI/ML Engineering student at CBIT seeking applied AI internships..."
        },

        "education": {
            "type": "array",
            "description": "Education entries, ordered as they appear in the resume",
            "item_fields": {
                "degree":      {"type": "string", "example": "B.E. in Artificial Intelligence and ML"},
                "institution": {"type": "string", "example": "Chaitanya Bharathi Institute of Technology"},
                "year_start":  {"type": "string", "example": "2023"},
                "year_end":    {"type": "string", "example": "2027"},
                "gpa":         {"type": "string", "example": "9.35"},
                "percentage":  {"type": "string", "example": "94.9%"},
                "location":    {"type": "string", "example": "Hyderabad"},
                "coursework":  {"type": "array[string]", "example": ["Machine Learning", "Data Structures"]},
            }
        },

        "experience": {
            "type": "array",
            "description": "Work experience and internship entries",
            "item_fields": {
                "title":      {"type": "string",        "example": "Machine Learning Intern"},
                "company":    {"type": "string",        "example": "WeXL AI Pvt Ltd"},
                "date_start": {"type": "string",        "example": "June 2026"},
                "date_end":   {"type": "string",        "example": "Current"},
                "location":   {"type": "string",        "example": "Hyderabad"},
                "bullets":    {"type": "array[string]", "example": ["Built a resume parser that reduced LLM costs by 40%"]},
            }
        },

        "projects": {
            "type": "array",
            "description": "Project entries",
            "item_fields": {
                "name":        {"type": "string",        "example": "Deepfake Voice Detection System"},
                "tech_stack":  {"type": "array[string]", "example": ["Python", "Wav2Vec2", "PyTorch"]},
                "description": {"type": "string",        "example": "Built a multilingual binary classifier..."},
            }
        },

        "skills": {
            "type": "object",
            "description": "Skills grouped by category. Keys are category names, values are lists of skills.",
            "example": {
                "Languages":   ["Python", "Java"],
                "ML / DL":     ["PyTorch", "TensorFlow", "scikit-learn"],
                "Tools":       ["Git", "Docker"],
                "Coursework":  ["Machine Learning", "Operating Systems"],
            }
        },

        "certifications": {
            "type": "array",
            "description": "Certification entries",
            "item_fields": {
                "name":   {"type": "string", "example": "Oracle OCI AI Foundations Associate"},
                "issuer": {"type": "string", "example": "Oracle"},
                "year":   {"type": "string", "example": "2025"},
            }
        },

        "achievements": {
            "type": "array[string]",
            "description": "Achievement, award, and hackathon entries as plain strings",
            "example": ["Finalist — Hackatron (Top 50), IIITM Gwalior 2024"]
        },

        "languages": {
            "type": "array[string]",
            "description": "Spoken/written languages. Empty if no Languages section found.",
            "example": ["English", "Telugu", "Hindi"]
        },

        "leadership": {
            "type": "array[string]",
            "description": "Leadership roles and positions of responsibility",
            "example": ["CBIT — Head — Rocketry Department"]
        },

        "extracurriculars": {
            "type": "array[string]",
            "description": "Extracurricular activities and interests",
            "example": ["Vice President — Music Club"]
        },

        "skill_analysis": {
            "type": "object",
            "description": "Skill evidence analysis — classifies listed skills by project backing",
            "fields": {
                "all_listed":  {"type": "array[string]", "description": "All skills listed in the Skills section"},
                "evidenced":   {"type": "array[string]", "description": "Skills backed by project or experience text"},
                "listed_only": {"type": "array[string]", "description": "Skills listed but with no project evidence"},
                "implied":     {"type": "array[string]", "description": "Skills found in project text but not listed"},
            }
        },

        "gaps": {
            "type": "array",
            "description": "Detected resume gaps, sorted high → medium → low severity",
            "item_fields": {
                "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                "message":  {"type": "string", "description": "Human-readable gap description with actionable advice"},
            }
        },

        "quality_score": {
            "type": "object",
            "description": "Resume quality score — content depth, not parse quality",
            "fields": {
                "total":  {"type": "int", "range": "0–100", "description": "Overall quality score"},
                "label":  {"type": "string", "enum": ["Strong", "Promising", "Developing", "Needs Work"]},
                "breakdown": {
                    "type": "object",
                    "fields": {
                        "project_depth":        {"type": "int", "max": 30},
                        "skill_credibility":    {"type": "int", "max": 25},
                        "experience_quality":   {"type": "int", "max": 20},
                        "profile_completeness": {"type": "int", "max": 15},
                        "achievements_quality": {"type": "int", "max": 10},
                        "github_bonus":         {"type": "int", "max": 5, "note": "CS/ECE only"},
                    }
                },
                "explanations": {
                    "type": "object",
                    "description": "Per-dimension actionable feedback strings",
                    "fields": {
                        "projects":     {"type": "array[string]"},
                        "skills":       {"type": "array[string]"},
                        "experience":   {"type": "array[string]"},
                        "profile":      {"type": "array[string]"},
                        "achievements": {"type": "array[string]"},
                    }
                },
                "is_cs_ece":        {"type": "bool", "description": "True if CS/ECE branch detected"},
                "is_mech_civil_ee": {"type": "bool", "description": "True if Mech/Civil/EE branch detected"},
            }
        },

        "health": {
            "type": "object",
            "description": "Parse quality indicator — how well the parser extracted content (not resume quality)",
            "fields": {
                "overall_score": {"type": "int", "range": "0–100", "description": "Parse confidence score"},
                "confidence": {
                    "type": "object",
                    "description": "Per-section extraction confidence scores (0.0–1.0). Use for LLM fallback routing.",
                    "note": "Sections with confidence < 0.6 benefit from LLM re-extraction",
                    "fields": {
                        "overall":        {"type": "float"},
                        "header":         {"type": "object", "fields": {"confidence": "float", "field_scores": "object"}},
                        "education":      {"type": "object", "fields": {"confidence": "float", "entry_count": "int"}},
                        "experience":     {"type": "object", "fields": {"confidence": "float", "entry_count": "int"}},
                        "projects":       {"type": "object", "fields": {"confidence": "float", "entry_count": "int"}},
                        "skills":         {"type": "object", "fields": {"confidence": "float", "skill_count": "int"}},
                        "certifications": {"type": "object", "fields": {"confidence": "float", "entry_count": "int"}},
                        "achievements":   {"type": "object", "fields": {"confidence": "float", "entry_count": "int"}},
                        "languages":      {"type": "object", "fields": {"confidence": "float", "entry_count": "int"}},
                        "leadership":     {"type": "object", "fields": {"confidence": "float", "entry_count": "int"}},
                        "extracurriculars": {"type": "object", "fields": {"confidence": "float", "entry_count": "int"}},
                    }
                },
                "no_spaces_warning": {"type": "bool", "description": "True if PDF has encoding issues (missing spaces)"},
                "header":       {"type": "object", "fields": {"status": "green|yellow|red", "note": "string", "confidence": "float"}},
                "education":    {"type": "object", "fields": {"status": "green|yellow|red", "note": "string", "confidence": "float"}},
                "experience":   {"type": "object", "fields": {"status": "green|yellow|red", "note": "string", "confidence": "float"}},
                "projects":     {"type": "object", "fields": {"status": "green|yellow|red", "note": "string", "confidence": "float"}},
                "skills":       {"type": "object", "fields": {"status": "green|yellow|red", "note": "string", "confidence": "float"}},
                "certifications": {"type": "object", "fields": {"status": "green|yellow|red", "note": "string", "confidence": "float"}},
            }
        },

        "github_data": {
            "type": "object | null",
            "description": "GitHub profile data. null if no GitHub URL in resume or if GitHub is unreachable.",
            "fields": {
                "username":            {"type": "string"},
                "public_repos":        {"type": "int"},
                "followers":           {"type": "int"},
                "total_stars":         {"type": "int"},
                "top_languages":       {"type": "array[string]", "example": ["Python", "JavaScript"]},
                "repos":               {"type": "array", "description": "Up to 10 most recently updated non-fork repos"},
                "project_matches": {
                    "type": "array",
                    "description": "Resume projects matched to GitHub repos",
                    "item_fields": {
                        "project":    {"type": "string", "description": "Project name from resume"},
                        "repo":       {"type": "string | null", "description": "Matched repo name, null if no match"},
                        "repo_url":   {"type": "string | null"},
                        "confidence": {"type": "float", "range": "0.0–1.0"},
                        "verified":   {"type": "bool", "description": "True if confidence >= 0.7"},
                        "partial":    {"type": "bool", "description": "True if confidence 0.5–0.69"},
                        "signals":    {"type": "object", "fields": {"name": "float", "desc": "float", "stack": "float"}},
                    }
                },
                "implied_from_github": {"type": "array[string]", "description": "Skills visible on GitHub but not listed on resume"},
            }
        },

        "_meta": {
            "type": "object",
            "description": "Request metadata added by the API",
            "fields": {
                "filename":     {"type": "string"},
                "size_kb":      {"type": "float"},
                "parse_time_s": {"type": "float", "description": "Wall-clock parse time in seconds"},
            }
        },
    }
}
