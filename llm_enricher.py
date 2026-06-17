"""
llm_enricher.py
----------------
Routes low-confidence sections to a local Ollama model for re-extraction.
Merges LLM output with rule-based output — never replaces wholesale,
only fills in fields the rule-based parser left empty or clearly garbled.

Requires Ollama running locally with the model pulled:
    ollama pull llama3.1:8b
    ollama serve   (usually auto-starts)

Usage:
    from llm_enricher import enrich_with_llm
    result = parse_resume(path)        # from assembler.py
    result = enrich_with_llm(result, raw_sections)   # raw_sections from segmenter.segment()
"""

from __future__ import annotations

import json
import re
import requests

OLLAMA_URL   = "http://localhost:11434/api/generate"
MODEL_NAME   = "llama3.1:8b"
CONFIDENCE_THRESHOLD = 0.6
REQUEST_TIMEOUT = 30  # seconds per section


# ── Prompts ───────────────────────────────────────────────────────────────────

_PROMPTS = {
    "experience": """Extract work experience entries from this resume section. Return ONLY valid JSON, no other text.

Format:
[
  {{
    "title": "job title",
    "company": "company name",
    "date_start": "start date as written",
    "date_end": "end date as written, or 'Present'/'Current'",
    "location": "city if mentioned, else empty string",
    "bullets": ["bullet point 1", "bullet point 2"]
  }}
]

If a field is not present, use an empty string or empty array. Do not invent information.

Resume text:
{text}""",

    "projects": """Extract project entries from this resume section. Return ONLY valid JSON, no other text.

Format:
[
  {{
    "name": "project name",
    "tech_stack": ["tool1", "tool2"],
    "description": "what was built and the outcome, combine all bullets into one paragraph"
  }}
]

If tech stack is not explicitly listed, use an empty array. Do not invent technologies.

Resume text:
{text}""",

    "education": """Extract education entries from this resume section. Return ONLY valid JSON, no other text.

Format:
[
  {{
    "degree": "degree name",
    "institution": "institution name",
    "year_start": "start year if mentioned, else empty string",
    "year_end": "end year or expected graduation year",
    "gpa": "GPA if mentioned, else empty string",
    "percentage": "percentage if mentioned, else empty string",
    "location": "city if mentioned, else empty string",
    "coursework": ["topic1", "topic2"]
  }}
]

If a field is not present, use an empty string or empty array. Do not invent information.

Resume text:
{text}""",
}


# ── Ollama call ───────────────────────────────────────────────────────────────

def _call_ollama(prompt: str) -> str | None:
    """Send a prompt to Ollama, return the raw text response or None on failure."""
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},  # low temp for extraction tasks
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")
    except requests.exceptions.RequestException as e:
        print(f"[llm_enricher] Ollama request failed: {e}")
    return None


def _extract_json(text: str) -> list | None:
    """Extract a JSON array from LLM output, stripping markdown fences if present."""
    if not text:
        return None
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        # Try to find the first [ ... ] block
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


# ── Section re-extraction ────────────────────────────────────────────────────

def _reextract_section(section_name: str, raw_text: str) -> list | None:
    """Run LLM extraction for one section. Returns parsed entries or None on failure."""
    if section_name not in _PROMPTS or not raw_text.strip():
        return None

    prompt = _PROMPTS[section_name].format(text=raw_text[:4000])  # cap input length
    response = _call_ollama(prompt)
    return _extract_json(response)


# ── Merge logic ───────────────────────────────────────────────────────────────

def _merge_entries(rule_based: list, llm_entries: list, key_fields: list[str]) -> list:
    """
    Merge LLM-extracted entries with rule-based entries.
    Strategy: if rule-based has entries, fill empty fields from LLM where possible
    (matched by position, since order is usually preserved).
    If rule-based has none, use LLM entries directly.
    """
    if not rule_based:
        return llm_entries or []

    if not llm_entries:
        return rule_based

    merged = []
    for i, rb_entry in enumerate(rule_based):
        llm_entry = llm_entries[i] if i < len(llm_entries) else {}
        new_entry = dict(rb_entry)
        for field in key_fields:
            rb_val = rb_entry.get(field)
            llm_val = llm_entry.get(field)
            # Fill if rule-based is empty/garbled and LLM has something
            is_empty = not rb_val or (isinstance(rb_val, str) and len(rb_val.split()) > 30)
            if is_empty and llm_val:
                new_entry[field] = llm_val
        merged.append(new_entry)

    # If LLM found more entries than rule-based, append the extras
    if len(llm_entries) > len(rule_based):
        merged.extend(llm_entries[len(rule_based):])

    return merged


# ── Main entry point ─────────────────────────────────────────────────────────

def enrich_with_llm(result: dict, sections: dict, threshold: float = CONFIDENCE_THRESHOLD) -> dict:
    """
    Re-extract low-confidence sections using Ollama and merge into the result.

    Parameters
    ----------
    result : dict
        Output from assembler.parse_resume() — must include result["health"]["confidence"]
    sections : dict
        Raw segmented sections from segmenter.segment() — needed for raw text per section
    threshold : float
        Confidence below which a section gets LLM re-extraction (default 0.6)

    Returns
    -------
    dict
        Same result dict, with low-confidence sections enriched in place.
        Adds result["_llm_enrichment"] showing which sections were touched.
    """
    confidence = result.get("health", {}).get("confidence", {})
    enrichment_log = {}

    # ── Experience ────────────────────────────────────────────────────────────
    exp_conf = confidence.get("experience", {}).get("confidence", 1.0)
    if exp_conf < threshold and "EXPERIENCE" in sections:
        raw_text = "\n".join(l["text"] for l in sections["EXPERIENCE"])
        llm_entries = _reextract_section("experience", raw_text)
        if llm_entries:
            result["experience"] = _merge_entries(
                result.get("experience", []), llm_entries,
                key_fields=["title", "company", "date_start", "date_end", "location", "bullets"]
            )
            enrichment_log["experience"] = {"confidence_before": exp_conf, "entries_from_llm": len(llm_entries)}

    # ── Projects ──────────────────────────────────────────────────────────────
    proj_conf = confidence.get("projects", {}).get("confidence", 1.0)
    if proj_conf < threshold and "PROJECTS" in sections:
        raw_text = "\n".join(l["text"] for l in sections["PROJECTS"])
        llm_entries = _reextract_section("projects", raw_text)
        if llm_entries:
            result["projects"] = _merge_entries(
                result.get("projects", []), llm_entries,
                key_fields=["name", "tech_stack", "description"]
            )
            enrichment_log["projects"] = {"confidence_before": proj_conf, "entries_from_llm": len(llm_entries)}

    # ── Education ─────────────────────────────────────────────────────────────
    edu_conf = confidence.get("education", {}).get("confidence", 1.0)
    if edu_conf < threshold and "EDUCATION" in sections:
        raw_text = "\n".join(l["text"] for l in sections["EDUCATION"])
        llm_entries = _reextract_section("education", raw_text)
        if llm_entries:
            result["education"] = _merge_entries(
                result.get("education", []), llm_entries,
                key_fields=["degree", "institution", "year_start", "year_end",
                           "gpa", "percentage", "location", "coursework"]
            )
            enrichment_log["education"] = {"confidence_before": edu_conf, "entries_from_llm": len(llm_entries)}

    result["_llm_enrichment"] = enrichment_log
    return result


# ── quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from extractor import extract_pdf
    from segmenter import segment
    from assembler import parse_resume

    path = sys.argv[1] if len(sys.argv) > 1 else "synthetic_resume.pdf"

    print("Parsing with rule-based pipeline...")
    result = parse_resume(path)

    print("\nConfidence scores before enrichment:")
    conf = result.get("health", {}).get("confidence", {})
    for sec in ["header", "education", "experience", "projects", "skills"]:
        c = conf.get(sec, {}).get("confidence", 0)
        print(f"  {sec:12}: {c:.2f}")

    print("\nRunning LLM enrichment for low-confidence sections...")
    raw_sections = segment(extract_pdf(path))
    result = enrich_with_llm(result, raw_sections)

    print("\nEnrichment log:")
    print(json.dumps(result.get("_llm_enrichment", {}), indent=2))

    print("\nExperience after enrichment:")
    for e in result.get("experience", []):
        print(f"  '{e.get('title')}' @ '{e.get('company')}'")
        for b in e.get("bullets", []):
            print(f"    • {b}")
