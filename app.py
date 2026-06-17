"""
app.py
------
Streamlit UI for the resume parser.
Run with: streamlit run app.py
"""

import json
import tempfile
import os
import streamlit as st

from assembler import parse_resume

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="ResuCheck",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Styling ───────────────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* Base */
    html, body, [data-testid="stAppViewContainer"] {
        background-color: #0f1117;
        color: #e2e8f0;
    }
    [data-testid="stAppViewContainer"] {
        padding: 0;
    }

    /* Hide default streamlit chrome */
    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding: 2rem 3rem 4rem 3rem; max-width: 1100px; }

    /* Typography */
    h1 { font-size: 1.6rem !important; font-weight: 700 !important; letter-spacing: -0.02em; color: #f8fafc !important; }
    h2 { font-size: 0.7rem !important; font-weight: 600 !important; letter-spacing: 0.12em !important;
         text-transform: uppercase; color: #64748b !important; margin-top: 2rem !important; margin-bottom: 0.75rem !important; }
    h3 { font-size: 0.95rem !important; font-weight: 600 !important; color: #cbd5e1 !important; margin-bottom: 0.2rem !important; }
    p, li { font-size: 0.88rem !important; color: #94a3b8; line-height: 1.6; }

    /* Upload zone */
    [data-testid="stFileUploader"] {
        background: #1e2330;
        border: 1.5px dashed #334155;
        border-radius: 10px;
        padding: 1rem;
    }
    [data-testid="stFileUploader"]:hover { border-color: #6366f1; }

    /* Cards */
    .card {
        background: #1e2330;
        border: 1px solid #1e293b;
        border-radius: 10px;
        padding: 1.1rem 1.3rem;
        margin-bottom: 0.75rem;
    }
    .card-title {
        font-size: 0.92rem;
        font-weight: 600;
        color: #e2e8f0;
        margin-bottom: 0.2rem;
    }
    .card-sub {
        font-size: 0.8rem;
        color: #64748b;
        margin-bottom: 0.5rem;
    }
    .card-meta {
        font-size: 0.78rem;
        color: #475569;
    }

    /* Skill chips */
    .chip-row { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.4rem; }
    .chip {
        font-size: 0.72rem;
        font-weight: 500;
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
        border: 1px solid;
        display: inline-block;
    }
    .chip-green  { background: #052e1680; border-color: #16a34a; color: #4ade80; }
    .chip-yellow { background: #42220080; border-color: #d97706; color: #fbbf24; }
    .chip-blue   { background: #0d1f3880; border-color: #3b82f6; color: #93c5fd; }
    .chip-gray   { background: #1e293b;   border-color: #334155; color: #94a3b8; }

    /* Gap badges */
    .gap-card {
        border-radius: 8px;
        padding: 0.75rem 1rem;
        margin-bottom: 0.5rem;
        font-size: 0.83rem;
        line-height: 1.55;
    }
    .gap-high   { background: #2d0a0a; border-left: 3px solid #ef4444; color: #fca5a5; }
    .gap-medium { background: #2a1a00; border-left: 3px solid #f59e0b; color: #fcd34d; }
    .gap-low    { background: #0a1628; border-left: 3px solid #3b82f6; color: #93c5fd; }

    /* Divider */
    hr { border-color: #1e293b !important; margin: 1.5rem 0 !important; }

    /* Metric strip */
    .metric-strip { display: flex; gap: 1rem; margin: 1rem 0 1.5rem 0; flex-wrap: wrap; }
    .metric-box {
        background: #1e2330;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 0.6rem 1.1rem;
        text-align: center;
        min-width: 90px;
    }
    .metric-num { font-size: 1.4rem; font-weight: 700; color: #6366f1; }
    .metric-lbl { font-size: 0.68rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.08em; }

    /* JSON toggle */
    .stExpander { border: 1px solid #1e293b !important; border-radius: 8px !important; background: #1e2330 !important; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def chips(items: list, style: str) -> str:
    if not items:
        return ""
    inner = "".join(f'<span class="chip chip-{style}">{i}</span>' for i in items)
    return f'<div class="chip-row">{inner}</div>'


def gap_html(gap: dict) -> str:
    cls = {"high": "gap-high", "medium": "gap-medium", "low": "gap-low"}.get(gap["severity"], "gap-low")
    icon = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(gap["severity"], "•")
    return f'<div class="gap-card {cls}">{icon} {gap["message"]}</div>'


# ── Session state init ────────────────────────────────────────────────────────
if "resume_store" not in st.session_state:
    st.session_state["resume_store"] = {}
    st.session_state["resume_order"] = []

# Sync resume_store from parse cache on every rerun
# This ensures tab switches don't lose parsed results
for _ck, _cv in st.session_state.get("_parse_cache", {}).items():
    _fname = _ck.rsplit("_", 1)[0]
    if _fname not in st.session_state["resume_store"]:
        st.session_state["resume_store"][_fname] = _cv
        st.session_state["resume_order"].append(_fname)

# ── Tabs ──────────────────────────────────────────────────────────────────────

st.markdown("<h1 style='font-size:2.4rem; font-weight:800; letter-spacing:-0.02em; margin-bottom:0.2rem;'>📄 ResuCheck</h1>", unsafe_allow_html=True)
st.markdown("<p style='color:#64748b; margin-top:0; margin-bottom:1.5rem; font-size:0.95rem;'>Parse your resume, see what's missing, and track improvements over time.</p>", unsafe_allow_html=True)

tab_parse, tab_compare = st.tabs(["📄 Parse", "🔀 Compare"])

with tab_parse:
    uploaded = st.file_uploader("Upload a resume PDF or DOCX", type=["pdf", "docx"], label_visibility="collapsed")

    if not uploaded:
        st.markdown("""
        <div style='background:#1e2330; border:1px solid #1e293b; border-radius:10px;
                    padding:2rem; text-align:center; color:#475569; margin-top:1rem;'>
            <div style='font-size:2rem; margin-bottom:0.5rem;'>⬆</div>
            <div style='font-size:0.9rem;'>Drop a PDF or DOCX above to begin</div>
            <div style='font-size:0.75rem; margin-top:0.4rem;'>Supports single-column and two-column layouts</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("📋 Guidelines for best results", expanded=True):
            st.markdown("""
### ✅ What works well
- **Canva, Google Docs, Word** exports — all parse well
- **Overleaf / LaTeX** — works if compiled with `xelatex` or `pdflatex` with `\\usepackage[T1]{fontenc}`
- **Single-column and two-column** layouts both supported

### ⚠️ What may cause issues
| Problem | Likely cause | Fix |
|---|---|---|
| All text merged together | Word "Minimum size" export | Re-export: Save As PDF → "Best for electronic distribution" |
| Spaces missing in text | LaTeX font encoding | Add `\\usepackage[T1]{fontenc}` or switch to XeLaTeX |
| Projects not detected | Unrecognised section header | Rename to "Projects" or "Key Projects" |
| Skills showing as "Other" | No category labels | Format as `Category: item1, item2` |

### ❌ Known limitations
- Scanned or photographed resumes (image PDFs) — no text to extract
            """)

    else:
        file_bytes = uploaded.getvalue()
        _cache_key = f"{uploaded.name}_{len(file_bytes)}"
        _cached = st.session_state.get("_parse_cache", {})

        if _cache_key in _cached:
            result = _cached[_cache_key]
            _no_spaces_severe = False
        else:
            with st.spinner("Parsing resume..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(file_bytes)
                    tmp_path = tmp.name

                from pathlib import Path
                import shutil
                ext = Path(uploaded.name).suffix.lower()
                proper_path = tmp_path + ext
                shutil.copy(tmp_path, proper_path)
                tmp_path = proper_path

                try:
                    _no_spaces_severe = False
                    if ext == ".pdf":
                        from extractor import extract_pdf as _epdf
                        _pre = _epdf(tmp_path)
                        _words = " ".join(l["text"] for l in _pre["lines"]).split()
                        _long = sum(1 for w in _words if len(w) > 25)
                        _ratio = _long / max(len(_words), 1)
                        _no_spaces_severe = _ratio > 0.40
                    result = parse_resume(tmp_path)
                    st.session_state["_parse_cache"] = {_cache_key: result}
                except Exception as e:
                    st.error(f"Parsing failed: {e}")
                    st.stop()
                finally:
                    try: os.unlink(tmp_path)
                    except: pass

        # Save to store immediately — before Compare tab reads it
        fname = uploaded.name
        st.session_state["resume_store"][fname] = result
        if fname not in st.session_state["resume_order"]:
            st.session_state["resume_order"].append(fname)

        sa = result["skill_analysis"]
        h  = result["header"]


        # ── Header strip ──────────────────────────────────────────────────────────────

        # Build contact spans safely outside the f-string to avoid </div> artifacts
        _contact_spans = []
        if h.get("email"):    _contact_spans.append(f'<span>✉ {h["email"]}</span>')
        if h.get("phone"):    _contact_spans.append(f'<span>📞 {h["phone"]}</span>')
        if h.get("linkedin"): _contact_spans.append(f'<span>🔗 {h["linkedin"]}</span>')
        if h.get("github"):   _contact_spans.append(f'<span>🐙 {h["github"]}</span>')
        if h.get("location"): _contact_spans.append(f'<span>📍 {h["location"]}</span>')
        _contact_html = " ".join(_contact_spans)

        st.markdown(f"""
        <div class='card' style='margin-bottom:1.5rem;'>
            <div style='font-size:1.2rem; font-weight:700; color:#f1f5f9;'>{h.get('name', '—')}</div>
            <div style='font-size:0.8rem; color:#64748b; margin-top:0.3rem; display:flex; flex-wrap:wrap; gap:1rem;'>
                {_contact_html}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Health indicator
        health = result.get("health", {})
        score = health.get("overall_score", 0)

        _score_color = "#4ade80" if score >= 75 else ("#fbbf24" if score >= 45 else "#f87171")
        _score_label = "Strong" if score >= 75 else ("Needs work" if score >= 45 else "Weak")

        _STATUS_ICON = {"green": "✓", "yellow": "⚠", "red": "✗"}
        _STATUS_COLOR = {"green": "#4ade80", "yellow": "#fbbf24", "red": "#f87171"}
        _STATUS_BG    = {"green": "#052e16", "yellow": "#422200", "red": "#2d0a0a"}

        def health_chip(section: str, label: str) -> str:
            s = health.get(section, {})
            status = s.get("status", "red")
            note   = s.get("note", "")
            icon   = _STATUS_ICON[status]
            color  = _STATUS_COLOR[status]
            bg     = _STATUS_BG[status]
            return (f"<div style='background:{bg};border:1px solid {color};border-radius:7px;"
                    f"padding:0.5rem 0.75rem;flex:1;min-width:110px;'>"
                    f"<div style='font-size:0.7rem;color:#64748b;margin-bottom:0.2rem;'>{label}</div>"
                    f"<div style='font-size:0.8rem;font-weight:600;color:{color};'>{icon} {note}</div>"
                    f"</div>")

        st.markdown(f"""
        <div style='display:flex;align-items:center;gap:1rem;margin-bottom:1rem;flex-wrap:wrap;'>
            <div style='background:#1e2330;border:1px solid #1e293b;border-radius:10px;
                        padding:0.75rem 1.2rem;text-align:center;min-width:90px;'>
                <div style='font-size:2rem;font-weight:800;color:{_score_color};line-height:1;'>{score}</div>
                <div style='font-size:0.65rem;color:#64748b;text-transform:uppercase;
                            letter-spacing:0.1em;margin-top:0.2rem;'>Parse score</div>
                <div style='font-size:0.7rem;color:{_score_color};margin-top:0.1rem;'>{_score_label}</div>
            </div>
            <div style='display:flex;gap:0.5rem;flex-wrap:wrap;flex:1;'>
                {health_chip("header", "Contact")}
                {health_chip("education", "Education")}
                {health_chip("experience", "Experience")}
                {health_chip("projects", "Projects")}
                {health_chip("skills", "Skills")}
                {health_chip("certifications", "Certifications")}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Metric strip
        st.markdown(f"""
        <div class='metric-strip'>
            <div class='metric-box'><div class='metric-num'>{len(result["projects"])}</div><div class='metric-lbl'>Projects</div></div>
            <div class='metric-box'><div class='metric-num'>{len(result["experience"])}</div><div class='metric-lbl'>Roles</div></div>
            <div class='metric-box'><div class='metric-num'>{len(sa["evidenced"])}</div><div class='metric-lbl'>Evidenced skills</div></div>
            <div class='metric-box'><div class='metric-num'>{len(sa["listed_only"])}</div><div class='metric-lbl'>Unevidenced</div></div>
            <div class='metric-box'><div class='metric-num'>{len(result["gaps"])}</div><div class='metric-lbl'>Gaps</div></div>
        </div>
        """, unsafe_allow_html=True)

        # ── Resume quality score ───────────────────────────────────────────────
        qs = result.get("quality_score", {})
        if qs:
            qt = qs.get("total", 0)
            ql = qs.get("label", "")
            qb = qs.get("breakdown", {})
            qe = qs.get("explanations", {})
            _qc = "#4ade80" if qt >= 82 else ("#a3e635" if qt >= 68 else ("#fbbf24" if qt >= 52 else "#f87171"))

            _dim_labels = {
                "project_depth":        ("Projects",     30),
                "skill_credibility":    ("Skills",       25),
                "experience_quality":   ("Experience",   20),
                "profile_completeness": ("Profile",      15),
                "achievements_quality": ("Achievements", 10),
            }
            if qb.get("github_bonus", 0) > 0:
                _dim_labels["github_bonus"] = ("GitHub ✦", 5)

            _bars = ""
            for key, (label, max_pts) in _dim_labels.items():
                pts = qb.get(key, 0)
                pct = (pts / max_pts) * 100
                bar_col = "#4ade80" if pct >= 75 else ("#fbbf24" if pct >= 40 else "#f87171")
                _bars += f"""
                <div style='margin-bottom:0.5rem;'>
                    <div style='display:flex;justify-content:space-between;font-size:0.75rem;margin-bottom:0.2rem;'>
                        <span style='color:#94a3b8;'>{label}</span>
                        <span style='color:{bar_col};font-weight:600;'>{pts}/{max_pts}</span>
                    </div>
                    <div style='background:#1e293b;border-radius:4px;height:6px;'>
                        <div style='background:{bar_col};width:{pct:.0f}%;height:6px;border-radius:4px;'></div>
                    </div>
                </div>"""

            st.markdown(f"""
            <div style='background:#1e2330;border:1px solid #1e293b;border-radius:12px;
                        padding:1.2rem 1.5rem;margin-bottom:1rem;'>
                <div style='display:flex;align-items:center;gap:1.2rem;margin-bottom:0.5rem;'>
                    <div style='text-align:center;min-width:80px;'>
                        <div style='font-size:2.4rem;font-weight:800;color:{_qc};line-height:1;'>{qt}</div>
                        <div style='font-size:0.65rem;color:#64748b;text-transform:uppercase;letter-spacing:0.1em;margin-top:0.2rem;'>Resume Score</div>
                        <div style='font-size:0.8rem;font-weight:600;color:{_qc};margin-top:0.2rem;'>{ql}</div>
                    </div>
                    <div style='flex:1;'>{_bars}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Explanations expander
            _dim_exp_labels = {
                "projects":     ("Projects",     qb.get("project_depth", 0),      30),
                "skills":       ("Skills",       qb.get("skill_credibility", 0),  25),
                "experience":   ("Experience",   qb.get("experience_quality", 0), 20),
                "profile":      ("Profile",      qb.get("profile_completeness", 0), 15),
                "achievements": ("Achievements", qb.get("achievements_quality", 0), 10),
            }
            with st.expander("📋 Score breakdown & tips"):
                for dim_key, (dim_label, pts, max_pts) in _dim_exp_labels.items():
                    notes = qe.get(dim_key, [])
                    pct = (pts / max_pts) * 100
                    col = "#4ade80" if pct >= 75 else ("#fbbf24" if pct >= 40 else "#f87171")
                    st.markdown(f"**{dim_label}** — <span style='color:{col};font-weight:600;'>{pts}/{max_pts}</span>", unsafe_allow_html=True)
                    for note in notes:
                        st.caption(f"• {note}")
                    st.markdown("---")


        # ── Main layout ───────────────────────────────────────────────────────────────

        left, right = st.columns([3, 2], gap="large")

        with left:

            # Profile / Summary
            if result.get("profile"):
                st.markdown("## Profile")
                st.markdown(f"""
                <div class='card' style='padding:0.8rem 1rem;'>
                    <p style='margin:0;font-size:0.88rem;color:#94a3b8;line-height:1.6;'>{result["profile"]}</p>
                </div>
                """, unsafe_allow_html=True)

            # Education
            st.markdown("## Education")
            for edu in result["education"]:
                yr = f"{edu['year_start']} – {edu['year_end']}" if edu["year_start"] else edu["year_end"]
                score = f"GPA {edu['gpa']}" if edu["gpa"] else (f"{edu['percentage']}" if edu["percentage"] else "")
                st.markdown(f"""
                <div class='card'>
                    <div class='card-title'>{edu['degree']}</div>
                    <div class='card-sub'>{edu['institution']}</div>
                    <div class='card-meta'>{yr}{' · ' + score if score else ''}</div>
                </div>
                """, unsafe_allow_html=True)

            # Experience
            if result["experience"]:
                st.markdown("## Experience")
                for exp in result["experience"]:
                    dr = f"{exp['date_start']} – {exp['date_end']}" if exp["date_start"] else exp["date_end"]
                    loc = f" · {exp['location']}" if exp.get("location") else ""
                    with st.container():
                        st.markdown(f"""
                        <div class='card' style='padding-bottom:0.4rem;'>
                            <div class='card-title'>{exp['title']}</div>
                            <div class='card-sub'>{exp['company']}{loc}</div>
                            <div class='card-meta'>{dr}</div>
                        </div>
                        """, unsafe_allow_html=True)
                        for b in exp["bullets"]:
                            st.caption(f"• {b}")

            # Projects
            st.markdown("## Projects")
            for proj in result["projects"]:
                stack_chips = chips(proj["tech_stack"], "gray")
                desc = proj["description"]
                # Render card header + stack chips via HTML, description via st.caption
                # to avoid unsafe_allow_html issues with long text content
                with st.container():
                    st.markdown(f"""
                    <div class='card' style='padding-bottom:0.4rem;'>
                        <div class='card-title'>{proj['name']}</div>
                        {stack_chips}
                    </div>
                    """, unsafe_allow_html=True)
                    if desc:
                        st.caption(desc)

            # Certifications
            if result["certifications"]:
                st.markdown("## Certifications")
                for cert in result["certifications"]:
                    yr = f" · {cert['year']}" if cert.get("year") else ""
                    st.markdown(f"""
                    <div class='card'>
                        <div class='card-title'>{cert['name']}</div>
                        <div class='card-meta'>{cert.get('issuer', '')}{yr}</div>
                    </div>
                    """, unsafe_allow_html=True)

            # Achievements
            if result["achievements"]:
                st.markdown("## Achievements")
                for a in result["achievements"]:
                    if a.strip():
                        st.markdown(f"""
                        <div class='card' style='padding:0.65rem 1rem;'>
                            <span style='font-size:0.85rem;color:#94a3b8;'>• {a}</span>
                        </div>
                        """, unsafe_allow_html=True)


            # Languages
            if result.get("languages"):
                st.markdown("## Languages")
                lang_chips = "".join(f'<span class="chip chip-gray">{l}</span>' for l in result["languages"])
                st.markdown(f'<div class="chip-row">{lang_chips}</div>', unsafe_allow_html=True)

            # Extracurriculars
            if result.get("extracurriculars"):
                st.markdown("## Extracurriculars")
                for e in result["extracurriculars"]:
                    if not e.strip():
                        continue
                    is_role = ("—" in e or "–" in e) and len(e.split()) <= 12
                    if is_role:
                        st.markdown(f"""
                        <div class='card' style='padding:0.65rem 1rem;'>
                            <div class='card-title' style='font-size:0.9rem;'>{e}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.caption(f"• {e}")

            # Leadership
            if result.get("leadership"):
                st.markdown("## Leadership")
                for l in result["leadership"]:
                    if not l.strip():
                        continue
                    # Role titles are short and contain — separator; bullets are longer sentences
                    is_role = ("—" in l or "–" in l) and len(l.split()) <= 12
                    if is_role:
                        st.markdown(f"""
                        <div class='card' style='padding:0.65rem 1rem;'>
                            <div class='card-title' style='font-size:0.9rem;'>{l}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.caption(f"• {l}")


        with right:

            # Skills — colour-coded by evidence status
            evidenced_set   = {s.lower() for s in sa["evidenced"]}
            listed_only_set = {s.lower() for s in sa["listed_only"]}

            def chip_for(skill):
                sl = skill.lower()
                if sl in evidenced_set:   return f'<span class="chip chip-green">{skill}</span>'
                if sl in listed_only_set: return f'<span class="chip chip-yellow">{skill}</span>'
                return f'<span class="chip chip-gray">{skill}</span>'

            st.markdown("## Skills")

            legend = (
                "<div style='display:flex;gap:0.8rem;flex-wrap:wrap;margin-bottom:1rem;font-size:0.72rem;color:#94a3b8;'>"
                "<span><span class='chip chip-green' style='padding:0.15rem 0.5rem;'>&#9632;</span> Evidenced</span>"
                "<span><span class='chip chip-yellow' style='padding:0.15rem 0.5rem;'>&#9632;</span> Listed only</span>"
                "</div>"
            )
            st.markdown(legend, unsafe_allow_html=True)

            for category, items in result["skills"].items():
                st.markdown(f"<div style='font-size:0.75rem;color:#64748b;margin-bottom:0.35rem;margin-top:0.8rem;'>{category.upper()}</div>", unsafe_allow_html=True)
                row = "".join(chip_for(s) for s in items)
                st.markdown(f'<div class="chip-row">{row}</div>', unsafe_allow_html=True)

            if sa["implied"]:
                st.markdown("<div style='font-size:0.75rem;color:#64748b;margin-bottom:0.35rem;margin-top:1.2rem;'>IMPLIED — in project text, consider adding</div>", unsafe_allow_html=True)
                st.markdown(chips(sa["implied"][:10], "blue"), unsafe_allow_html=True)

            # Gaps
            st.markdown("## Gaps")
            if result["gaps"]:
                for gap in result["gaps"]:
                    st.markdown(gap_html(gap), unsafe_allow_html=True)
            else:
                st.markdown("<div style='color:#4ade80; font-size:0.85rem;'>✓ No significant gaps detected.</div>", unsafe_allow_html=True)


        # ── Confidence scores ────────────────────────────────────────────────────────

        st.markdown("<hr>", unsafe_allow_html=True)

        # ── GitHub data ──────────────────────────────────────────────────────────────
        gd = result.get("github_data", {})
        if gd and "error" not in gd and gd.get("username"):
            with st.expander(f"🐙 GitHub — {gd['username']} · {gd['public_repos']} public repos"):
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("Public Repos", gd["public_repos"])
                col_b.metric("Followers", gd["followers"])
                col_c.metric("Total Stars", gd["total_stars"])

                if gd.get("top_languages"):
                    st.markdown("**Top languages on GitHub:** " + " · ".join(gd["top_languages"]))

                matches = gd.get("project_matches", [])
                verified = [m for m in matches if m["verified"]]
                unverified = [m for m in matches if not m["verified"]]

                if matches:
                    st.markdown("**Project verification:**")
                    for m in matches:
                        signals = m.get("signals", {})
                        parts = []
                        if signals.get("name", 0) > 0:  parts.append(f"name {signals['name']:.0%}")
                        if signals.get("desc", 0) > 0:  parts.append(f"desc {signals['desc']:.0%}")
                        if signals.get("stack", 0) > 0: parts.append(f"stack {signals['stack']:.0%}")
                        detail = f" · {', '.join(parts)}" if parts else f" · {m['confidence']:.0%}"

                        if m.get("verified"):
                            st.markdown(f"✅ **{m['project']}** → [{m['repo']}]({m['repo_url']}){detail}")
                        elif m.get("partial"):
                            st.markdown(f"🟡 **{m['project']}** → [{m['repo']}]({m['repo_url']}) *(partial)*{detail}")
                        else:
                            st.markdown(f"❓ **{m['project']}** — no matching repo found")
                    st.caption(
                        "✅ **Strong match** — repo name, description, and tech stack align well with the project on your resume.\n\n"
                        "🟡 **Partial match** — a repo with a similar name was found but the description or stack don't fully align; verify it's the right one.\n\n"
                        "❓ **Not found** — no public repo matched this project. It may be private, named differently, or not yet pushed to GitHub."
                    )

                if gd.get("implied_from_github"):
                    st.markdown("**Skills evident from GitHub not listed on resume:** " +
                                ", ".join(gd["implied_from_github"]))

        with st.expander("📊 Extraction confidence scores"):
            conf = result.get("health", {}).get("confidence", {})
            if conf:
                overall = conf.get("overall", 0)
                _c = lambda v: ("#4ade80" if v >= 0.7 else ("#fbbf24" if v >= 0.4 else "#f87171"))

                st.markdown(f"""
                <div style='margin-bottom:1rem;'>
                    <span style='font-size:0.8rem;color:#64748b;'>Overall confidence: </span>
                    <span style='font-size:1rem;font-weight:700;color:{_c(overall)};'>{overall:.0%}</span>
                    <span style='font-size:0.75rem;color:#475569;margin-left:0.5rem;'>
                        Used to decide which sections benefit from LLM re-extraction
                    </span>
                </div>
                """, unsafe_allow_html=True)

                sections = [
                    ("header",          "Contact"),
                    ("education",       "Education"),
                    ("experience",      "Experience"),
                    ("projects",        "Projects"),
                    ("skills",          "Skills"),
                    ("certifications",  "Certifications"),
                    ("achievements",    "Achievements"),
                    ("languages",       "Languages"),
                    ("extracurriculars","Extracurriculars"),
                    ("leadership",      "Leadership"),
                ]

                rows = ""
                for key, label in sections:
                    s = conf.get(key, {})
                    c = s.get("confidence", 0)
                    count = s.get("entry_count", s.get("skill_count", "—"))
                    flag = "✓ reliable" if c >= 0.7 else ("⚠ uncertain" if c >= 0.4 else "✗ low")
                    color = _c(c)
                    rows += (
                        f"<tr>"
                        f"<td style='padding:0.35rem 0.75rem;color:#94a3b8;'>{label}</td>"
                        f"<td style='padding:0.35rem 0.75rem;'>"
                        f"<div style='background:#1e293b;border-radius:4px;height:6px;width:100%;'>"
                        f"<div style='background:{color};width:{c*100:.0f}%;height:6px;border-radius:4px;'></div>"
                        f"</div></td>"
                        f"<td style='padding:0.35rem 0.75rem;color:{color};font-weight:600;'>{c:.0%}</td>"
                        f"<td style='padding:0.35rem 0.75rem;color:#475569;font-size:0.75rem;'>{flag}</td>"
                        f"</tr>"
                    )

                st.markdown(f"""
                <table style='width:100%;border-collapse:collapse;font-size:0.85rem;'>
                    <thead>
                        <tr style='border-bottom:1px solid #1e293b;'>
                            <th style='padding:0.35rem 0.75rem;color:#475569;text-align:left;font-weight:500;'>Section</th>
                            <th style='padding:0.35rem 0.75rem;color:#475569;text-align:left;font-weight:500;width:40%;'>Confidence</th>
                            <th style='padding:0.35rem 0.75rem;color:#475569;text-align:left;font-weight:500;'></th>
                            <th style='padding:0.35rem 0.75rem;color:#475569;text-align:left;font-weight:500;'>Signal</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
                """, unsafe_allow_html=True)

                # Show which sections would trigger LLM fallback
                low_conf = [(label, conf.get(key, {}).get("confidence", 0))
                            for key, label in sections
                            if conf.get(key, {}).get("confidence", 0) < 0.6
                            and conf.get(key, {}).get("entry_count", conf.get(key, {}).get("skill_count", 0))]
                if low_conf:
                    names = ", ".join(f"{l} ({c:.0%})" for l, c in low_conf)
                    st.markdown(
                        f"<div style='margin-top:1rem;font-size:0.8rem;color:#fbbf24;'>"
                        f"⚡ Sections that would benefit from LLM re-extraction: {names}</div>",
                        unsafe_allow_html=True
                    )

        # ── Raw JSON ──────────────────────────────────────────────────────────────────

        with st.expander("Raw JSON output"):
            st.code(json.dumps(result, indent=2), language="json")


with tab_compare:
    store = st.session_state["resume_store"]
    order = st.session_state["resume_order"]

    if len(store) < 1:
        st.info("No resumes parsed yet. Parse at least one resume in the **📄 Parse** tab first.")
    else:
        st.markdown("### Compare two resume versions")
        st.markdown("<p style='color:#64748b;'>Select two previously parsed resumes to compare, or upload a new one as V2.</p>", unsafe_allow_html=True)

        col_v1, col_v2 = st.columns(2)

        with col_v1:
            st.markdown("**Version 1 (older)**")
            v1_name = st.selectbox("Select V1", options=order, key="sel_v1", label_visibility="collapsed")

        with col_v2:
            st.markdown("**Version 2 (newer)**")
            v2_options = [n for n in order if n != v1_name] + ["⬆ Upload new resume..."]
            v2_choice = st.selectbox("Select V2", options=v2_options, key="sel_v2", label_visibility="collapsed")

            uploaded_v2_new = None
            if v2_choice == "⬆ Upload new resume...":
                uploaded_v2_new = st.file_uploader("Upload V2", type=["pdf","docx"], key="v2_upload", label_visibility="collapsed")

        r1 = store.get(v1_name)
        r2 = None
        v2_name = ""

        if v2_choice == "⬆ Upload new resume...":
            if uploaded_v2_new:
                def _parse_upload(upload):
                    import shutil
                    from pathlib import Path
                    with tempfile.NamedTemporaryFile(delete=False) as tmp:
                        tmp.write(upload.getvalue())
                        tmp_path = tmp.name
                    ext = Path(upload.name).suffix.lower()
                    proper = tmp_path + ext
                    shutil.copy(tmp_path, proper)
                    try:
                        return parse_resume(proper)
                    finally:
                        try: os.unlink(proper)
                        except: pass

                with st.spinner("Parsing new resume..."):
                    r2 = _parse_upload(uploaded_v2_new)
                    v2_name = uploaded_v2_new.name
                    if v2_name not in st.session_state["resume_store"]:
                        st.session_state["resume_store"][v2_name] = r2
                        st.session_state["resume_order"].append(v2_name)
        else:
            r2 = store.get(v2_choice)
            v2_name = v2_choice

        if r1 and r2:
            st.markdown(f"**Comparing:** `{v1_name}` → `{v2_name}`")
            st.markdown("---")
            st.markdown("### What changed")

            def _delta(a, b, label):
                diff = b - a
                colour = "#4ade80" if diff > 0 else ("#f87171" if diff < 0 else "#64748b")
                arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
                sign = "+" if diff > 0 else ""
                return f"""<div style='background:#1e2330;border:1px solid #1e293b;border-radius:10px;
                    padding:1rem;text-align:center;'>
                    <div style='font-size:1.6rem;font-weight:800;color:{colour};'>{sign}{diff}</div>
                    <div style='font-size:0.75rem;color:#64748b;margin-top:0.3rem;'>{label}</div>
                    <div style='font-size:0.7rem;color:#475569;'>{a} {arrow} {b}</div></div>"""

            sk1 = sum(len(v) for v in r1["skills"].values())
            sk2 = sum(len(v) for v in r2["skills"].values())
            ev1 = len(r1.get("skill_analysis", {}).get("evidenced", []))
            ev2 = len(r2.get("skill_analysis", {}).get("evidenced", []))
            sc1 = r1.get("quality_score", {}).get("total", 0)
            sc2 = r2.get("quality_score", {}).get("total", 0)

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.markdown(_delta(len(r1["projects"]),   len(r2["projects"]),   "Projects"),  unsafe_allow_html=True)
            c2.markdown(_delta(len(r1["experience"]), len(r2["experience"]), "Roles"),     unsafe_allow_html=True)
            c3.markdown(_delta(sk1, sk2,                                     "Skills"),    unsafe_allow_html=True)
            c4.markdown(_delta(ev1, ev2,                                     "Evidenced"), unsafe_allow_html=True)
            c5.markdown(_delta(sc1, sc2,                                     "Resume score"), unsafe_allow_html=True)

            # Quality score breakdown comparison
            qs1 = r1.get("quality_score", {})
            qs2 = r2.get("quality_score", {})
            if qs1 and qs2:
                qb1 = qs1.get("breakdown", {})
                qb2 = qs2.get("breakdown", {})
                _dim_labels = [
                    ("project_depth",        "Projects",      30),
                    ("skill_credibility",    "Skills",        25),
                    ("experience_quality",   "Experience",    20),
                    ("profile_completeness", "Profile",       15),
                    ("achievements_quality", "Achievements",  10),
                ]
                rows = ""
                for key, label, max_pts in _dim_labels:
                    p1 = qb1.get(key, 0)
                    p2 = qb2.get(key, 0)
                    diff = p2 - p1
                    col = "#4ade80" if diff > 0 else ("#f87171" if diff < 0 else "#64748b")
                    sign = "+" if diff > 0 else ""
                    l1 = qs1.get("label","")
                    l2 = qs2.get("label","")
                    rows += (f"<tr>"
                             f"<td style='padding:0.3rem 0.75rem;color:#94a3b8;'>{label}</td>"
                             f"<td style='padding:0.3rem 0.75rem;color:#64748b;'>{p1}/{max_pts}</td>"
                             f"<td style='padding:0.3rem 0.75rem;color:#64748b;'>{p2}/{max_pts}</td>"
                             f"<td style='padding:0.3rem 0.75rem;font-weight:600;color:{col};'>{sign}{diff}</td>"
                             f"</tr>")
                _qc1 = "#4ade80" if sc1>=82 else ("#a3e635" if sc1>=68 else ("#fbbf24" if sc1>=52 else "#f87171"))
                _qc2 = "#4ade80" if sc2>=82 else ("#a3e635" if sc2>=68 else ("#fbbf24" if sc2>=52 else "#f87171"))
                st.markdown(f"""
                <div style='background:#1e2330;border:1px solid #1e293b;border-radius:10px;padding:1rem 1.2rem;margin-top:1rem;'>
                    <div style='display:flex;justify-content:space-between;margin-bottom:0.75rem;'>
                        <div>
                            <span style='font-size:0.75rem;color:#64748b;'>V1 Resume Score</span><br>
                            <span style='font-size:1.4rem;font-weight:800;color:{_qc1};'>{sc1}</span>
                            <span style='font-size:0.8rem;color:{_qc1};margin-left:0.4rem;'>{l1}</span>
                        </div>
                        <div style='text-align:right;'>
                            <span style='font-size:0.75rem;color:#64748b;'>V2 Resume Score</span><br>
                            <span style='font-size:1.4rem;font-weight:800;color:{_qc2};'>{sc2}</span>
                            <span style='font-size:0.8rem;color:{_qc2};margin-left:0.4rem;'>{l2}</span>
                        </div>
                    </div>
                    <table style='width:100%;border-collapse:collapse;font-size:0.82rem;'>
                        <thead><tr style='border-bottom:1px solid #1e293b;'>
                            <th style='padding:0.3rem 0.75rem;color:#475569;text-align:left;font-weight:500;'>Dimension</th>
                            <th style='padding:0.3rem 0.75rem;color:#475569;text-align:left;font-weight:500;'>V1</th>
                            <th style='padding:0.3rem 0.75rem;color:#475569;text-align:left;font-weight:500;'>V2</th>
                            <th style='padding:0.3rem 0.75rem;color:#475569;text-align:left;font-weight:500;'>Δ</th>
                        </tr></thead>
                        <tbody>{rows}</tbody>
                    </table>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("---")
            st.markdown("### Gap resolution")

            gaps1 = {g["message"]: g["severity"] for g in r1.get("gaps", [])}
            gaps2 = {g["message"]: g["severity"] for g in r2.get("gaps", [])}
            resolved  = [m for m in gaps1 if m not in gaps2]
            new_gaps  = [m for m in gaps2 if m not in gaps1]
            remaining = [m for m in gaps1 if m in gaps2]

            if resolved:
                st.markdown(f"**✅ Resolved ({len(resolved)})**")
                for m in resolved:
                    icon = {"high":"🔴","medium":"🟡","low":"🔵"}.get(gaps1[m],"•")
                    st.markdown(f"""<div style='background:#052e16;border:1px solid #166534;border-radius:8px;
                        padding:0.6rem 1rem;margin-bottom:0.4rem;font-size:0.85rem;color:#86efac;'>
                        ✓ {icon} {m}</div>""", unsafe_allow_html=True)

            if new_gaps:
                st.markdown(f"**🆕 New gaps ({len(new_gaps)})**")
                for m in new_gaps:
                    icon = {"high":"🔴","medium":"🟡","low":"🔵"}.get(gaps2[m],"•")
                    st.markdown(f"""<div style='background:#2d0a0a;border:1px solid #7f1d1d;border-radius:8px;
                        padding:0.6rem 1rem;margin-bottom:0.4rem;font-size:0.85rem;color:#fca5a5;'>
                        {icon} {m}</div>""", unsafe_allow_html=True)

            if remaining:
                st.markdown(f"**⏳ Still to address ({len(remaining)})**")
                for m in remaining:
                    icon = {"high":"🔴","medium":"🟡","low":"🔵"}.get(gaps1[m],"•")
                    st.markdown(f"""<div style='background:#1e2330;border:1px solid #334155;border-radius:8px;
                        padding:0.6rem 1rem;margin-bottom:0.4rem;font-size:0.85rem;color:#94a3b8;'>
                        {icon} {m}</div>""", unsafe_allow_html=True)

            if not resolved and not new_gaps and not remaining:
                st.info("No changes in gap profile between the two versions.")

            with st.expander("Section-level confidence changes"):
                conf1 = r1.get("health", {}).get("confidence", {})
                conf2 = r2.get("health", {}).get("confidence", {})
                rows = ""
                for sec in ["header","education","experience","projects","skills","certifications","achievements"]:
                    c1v = conf1.get(sec, {}).get("confidence", 0)
                    c2v = conf2.get(sec, {}).get("confidence", 0)
                    diff = c2v - c1v
                    colour = "#4ade80" if diff > 0.05 else ("#f87171" if diff < -0.05 else "#64748b")
                    sign = "+" if diff > 0 else ""
                    rows += (f"<tr><td style='padding:0.3rem 0.75rem;color:#94a3b8;'>{sec.title()}</td>"
                             f"<td style='padding:0.3rem 0.75rem;color:#64748b;'>{c1v:.0%}</td>"
                             f"<td style='padding:0.3rem 0.75rem;color:#64748b;'>{c2v:.0%}</td>"
                             f"<td style='padding:0.3rem 0.75rem;font-weight:600;color:{colour};'>{sign}{diff:.0%}</td></tr>")
                st.markdown(f"""<table style='width:100%;border-collapse:collapse;font-size:0.85rem;'>
                    <thead><tr style='border-bottom:1px solid #1e293b;'>
                        <th style='padding:0.3rem 0.75rem;color:#475569;text-align:left;'>Section</th>
                        <th style='padding:0.3rem 0.75rem;color:#475569;text-align:left;'>V1</th>
                        <th style='padding:0.3rem 0.75rem;color:#475569;text-align:left;'>V2</th>
                        <th style='padding:0.3rem 0.75rem;color:#475569;text-align:left;'>Δ</th>
                    </tr></thead><tbody>{rows}</tbody></table>""", unsafe_allow_html=True)
