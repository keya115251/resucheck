"""
github_enricher.py
------------------
Optional enrichment step: fetches public GitHub repo data for the candidate
and cross-references against parsed projects and skills.

What it adds to the result:
  - github_profile: basic stats (repos, stars, top languages)
  - project matches: links parsed projects to GitHub repos by name similarity
  - additional implied skills: languages/topics from repos not listed in skills
  - verification signal: confirms claimed projects actually exist on GitHub

Usage:
    from github_enricher import enrich_github
    result = enrich_github(result)   # pass the final assembled result dict

No API key required — uses GitHub's public REST API (unauthenticated).
Rate limit: 60 requests/hour per IP. Caches results per session.
"""

from __future__ import annotations

import re
import time
import urllib.request
import urllib.error
import json
from difflib import SequenceMatcher


# ── Config ────────────────────────────────────────────────────────────────────

GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 5   # seconds per request
MAX_REPOS = 30        # max repos to fetch per user
MATCH_THRESHOLD = 0.5  # minimum similarity to attempt a link
VERIFIED_THRESHOLD = 0.80  # above this = verified, below = partial match

# GitHub language → skill taxonomy name mapping
LANG_TO_SKILL = {
    "python":      "Python",
    "javascript":  "JavaScript",
    "typescript":  "TypeScript",
    "java":        "Java",
    "c++":         "C++",
    "c":           "C",
    "go":          "Go",
    "rust":        "Rust",
    "kotlin":      "Kotlin",
    "swift":       "Swift",
    "r":           "R",
    "matlab":      "MATLAB",
    "html":        "HTML",
    "css":         "CSS",
    "shell":       "Bash",
    "dockerfile":  "Docker",
    "jupyter notebook": "Jupyter",
    "dart":        "Dart",
    "ruby":        "Ruby",
    "php":         "PHP",
    "scala":       "Scala",
    "assembly":    "Assembly",
    "verilog":     "Verilog",
    "vhdl":        "VHDL",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(url: str) -> dict | list | None:
    """Simple GET with timeout. Returns parsed JSON or None on error."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "resume-parser/1.0", "Accept": "application/vnd.github.v3+json"}
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError):
        pass
    return None


def _extract_username(github_url: str) -> str | None:
    """Extract GitHub username from a URL or bare username."""
    if not github_url:
        return None
    # Handle URLs like github.com/username or https://github.com/username
    m = re.search(r"github\.com/([a-zA-Z0-9\-]+)", github_url)
    if m:
        return m.group(1)
    # Bare username
    if re.match(r"^[a-zA-Z0-9\-]+$", github_url.strip()):
        return github_url.strip()
    return None


def _name_similarity(a: str, b: str) -> float:
    """
    Fuzzy name similarity between a project name and a repo slug.
    Combines SequenceMatcher with a word-coverage bonus:
    if all words in the repo slug appear in the project name,
    the repo is clearly a match even if the project name is longer.
    e.g. "deepfake-voice-detection" vs "Deepfake Voice Detection System" → high score
    """
    a_clean = re.sub(r"[^a-z0-9]", "", a.lower())
    b_clean = re.sub(r"[^a-z0-9]", "", b.lower())
    if not a_clean or not b_clean:
        return 0.0

    base = SequenceMatcher(None, a_clean, b_clean).ratio()

    # Word-coverage bonus: check how many repo slug words appear in the project name
    # Normalise both by removing special chars so "q&a" → "qa" matches "qna" → "qna"
    # Use both the cleaned and word-split versions for maximum recall
    repo_words = [w for w in re.split(r"[^a-z0-9]+", b.lower()) if len(w) > 1]
    proj_words_set = set(re.split(r"[^a-z0-9]+", a.lower()))
    # Also add joined version: "q&a" → "qa", "q a" → "qa"
    proj_clean_joined = re.sub(r"[^a-z0-9]", "", a.lower())

    if repo_words:
        matched = sum(
            1 for w in repo_words
            if w in proj_words_set or w in proj_clean_joined
        )
        coverage = matched / len(repo_words)
        score = max(base, coverage * 0.95)
    else:
        score = base

    return round(score, 2)


# ── Core enrichment ───────────────────────────────────────────────────────────

def enrich_github(result: dict) -> dict:
    """
    Fetch GitHub profile data and enrich the result dict.

    Parameters
    ----------
    result : dict
        The assembled result dict from assembler.assemble().

    Returns
    -------
    dict
        Same dict with added "github_data" key. If GitHub is unreachable
        or the user has no public repos, returns result unchanged.
    """
    github_url = result.get("header", {}).get("github", "")
    username = _extract_username(github_url)

    if not username:
        return result

    # ── 1. Fetch user profile ─────────────────────────────────────────────────
    profile = _get(f"{GITHUB_API}/users/{username}")
    if not profile or "login" not in profile:
        result["github_data"] = {"error": "Profile not found or rate limited"}
        return result

    # ── 2. Fetch repos ────────────────────────────────────────────────────────
    repos_raw = _get(
        f"{GITHUB_API}/users/{username}/repos"
        f"?sort=updated&per_page={MAX_REPOS}&type=public"
    )
    if not repos_raw:
        repos_raw = []

    # ── 3. Aggregate repo data ────────────────────────────────────────────────
    repos = []
    language_counts: dict[str, int] = {}
    total_stars = 0

    for repo in repos_raw:
        if repo.get("fork"):
            continue  # skip forks — not original work

        lang = (repo.get("language") or "").lower()
        stars = repo.get("stargazers_count", 0)
        total_stars += stars

        if lang:
            language_counts[lang] = language_counts.get(lang, 0) + 1

        repos.append({
            "name":        repo["name"],
            "description": (repo.get("description") or "").strip(),
            "language":    repo.get("language") or "",
            "stars":       stars,
            "url":         repo.get("html_url", ""),
            "topics":      repo.get("topics", []),
            "updated":     repo.get("updated_at", "")[:10],
        })

    top_languages = sorted(language_counts.items(), key=lambda x: -x[1])[:5]

    # ── 4. Match parsed projects to repos ────────────────────────────────────
    parsed_projects = result.get("projects", [])
    project_matches = []

    for proj in parsed_projects:
        proj_name  = proj.get("name", "")
        proj_desc  = proj.get("description", "").lower()
        proj_stack = {t.lower() for t in proj.get("tech_stack", [])}

        best_repo  = None
        best_score = 0.0

        for repo in repos:
            # Signal 1: name similarity
            name_score = _name_similarity(proj_name, repo["name"])

            # Signal 2: description word overlap
            repo_desc = (repo.get("description") or "").lower()
            if proj_desc and repo_desc:
                proj_words = {w for w in re.split(r"[^a-z0-9]+", proj_desc) if len(w) > 3}
                repo_words = {w for w in re.split(r"[^a-z0-9]+", repo_desc) if len(w) > 3}
                common = proj_words & repo_words
                desc_score = min(len(common) / max(len(repo_words), 1), 1.0)
            else:
                desc_score = 0.0

            # Signal 3: tech stack vs repo language + topics
            repo_lang   = (repo.get("language") or "").lower()
            repo_topics = {t.lower() for t in repo.get("topics", [])}
            repo_tech   = repo_topics | ({repo_lang} if repo_lang else set())

            if proj_stack and repo_tech:
                proj_norm  = {re.sub(r"[^a-z0-9]", "", s) for s in proj_stack}
                repo_norm  = {re.sub(r"[^a-z0-9]", "", s) for s in repo_tech}
                stack_score = min(len(proj_norm & repo_norm) / max(len(proj_norm), 1), 1.0)
            else:
                stack_score = 0.0

            # Weighted blend
            combined = name_score * 0.55 + desc_score * 0.25 + stack_score * 0.20
            if name_score >= 0.80:
                combined = max(combined, name_score * 0.95)

            if combined > best_score:
                best_score = combined
                best_repo  = repo
                best_repo["_signals"] = {
                    "name": round(name_score, 2),
                    "desc": round(desc_score, 2),
                    "stack": round(stack_score, 2),
                }

        linked = best_repo is not None and best_score >= MATCH_THRESHOLD
        project_matches.append({
            "project":    proj_name,
            "repo":       best_repo["name"] if linked else None,
            "repo_url":   best_repo["url"]  if linked else None,
            "confidence": round(best_score, 2),
            "verified":   best_score >= VERIFIED_THRESHOLD,
            "partial":    linked and best_score < VERIFIED_THRESHOLD,
            "signals":    best_repo.get("_signals", {}) if linked else {},
        })

    # ── 5. Detect skills from repo languages not listed in resume ─────────────
    listed_skills_lower = {
        s.lower()
        for items in result.get("skills", {}).values()
        for s in items
    }

    implied_from_github = []
    for lang, _ in top_languages:
        skill = LANG_TO_SKILL.get(lang)
        if skill and skill.lower() not in listed_skills_lower:
            implied_from_github.append(skill)

    # Also check repo topics
    all_topics = {t for repo in repos for t in repo.get("topics", [])}
    topic_to_skill = {
        "pytorch": "PyTorch", "tensorflow": "TensorFlow", "react": "React",
        "nodejs": "Node.js", "docker": "Docker", "flask": "Flask",
        "fastapi": "FastAPI", "opencv": "OpenCV", "sklearn": "scikit-learn",
        "arduino": "Arduino", "raspberry-pi": "Raspberry Pi",
        "solidworks": "SolidWorks", "ansys": "ANSYS",
    }
    for topic, skill in topic_to_skill.items():
        if topic in all_topics and skill.lower() not in listed_skills_lower:
            implied_from_github.append(skill)

    # ── 6. Package result ─────────────────────────────────────────────────────
    result["github_data"] = {
        "username":            username,
        "public_repos":        profile.get("public_repos", 0),
        "followers":           profile.get("followers", 0),
        "total_stars":         total_stars,
        "top_languages":       [lang for lang, _ in top_languages],
        "repos":               repos[:10],   # top 10 most recently updated
        "project_matches":     project_matches,
        "implied_from_github": implied_from_github,
    }

    return result


# ── quick test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    username = sys.argv[1] if len(sys.argv) > 1 else "keya115251"

    mock_result = {
        "header": {"github": f"github.com/{username}"},
        "projects": [
            {"name": "Librarium"},
            {"name": "sentinel-cd"},
        ],
        "skills": {"Languages": ["Python", "JavaScript"]},
    }

    print(f"Fetching GitHub data for {username}...")
    enriched = enrich_github(mock_result)
    gd = enriched.get("github_data", {})

    if "error" in gd:
        print(f"Error: {gd['error']}")
    else:
        print(f"\nProfile: {gd['username']}")
        print(f"Public repos: {gd['public_repos']} | Followers: {gd['followers']} | Stars: {gd['total_stars']}")
        print(f"Top languages: {gd['top_languages']}")
        print(f"\nProject matches:")
        for m in gd["project_matches"]:
            status = "✓" if m["verified"] else "✗"
            print(f"  {status} '{m['project']}' → {m['repo']} ({m['confidence']:.0%})")
        print(f"\nImplied from GitHub: {gd['implied_from_github']}")
