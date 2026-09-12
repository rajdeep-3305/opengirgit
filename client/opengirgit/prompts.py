"""Client-side formatting of the interview context.

The context is one plain-text blob attached to every chat/vision request; the
server owns the system prompt (identical split of responsibilities to the
original app).
"""

from __future__ import annotations

from typing import Any


def format_resume_data(resume: dict[str, Any] | None) -> str:
    lines: list[str] = ["=== CANDIDATE RESUME ==="]
    if not resume:
        lines.append("(no resume provided)")
        return "\n".join(lines)

    for key, label in (
        ("name", "Name"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("location", "Location"),
    ):
        value = resume.get(key)
        if value:
            lines.append(f"{label}: {value}")

    if resume.get("summary"):
        lines.extend(["", "Summary:", str(resume["summary"])])

    experience = resume.get("experience") or []
    if experience:
        lines.extend(["", "--- Experience ---"])
        for job in experience:
            entry = f"- {job.get('title') or 'N/A'} at {job.get('company') or 'N/A'}"
            if job.get("duration"):
                entry += f" ({job['duration']})"
            lines.append(entry)
            if job.get("description"):
                lines.append(f"  {job['description']}")

    education = resume.get("education") or []
    if education:
        lines.extend(["", "--- Education ---"])
        for item in education:
            entry = f"- {item.get('degree') or 'N/A'}"
            if item.get("institution"):
                entry += f" from {item['institution']}"
            if item.get("year"):
                entry += f" ({item['year']})"
            lines.append(entry)

    skills = resume.get("skills") or []
    if skills:
        lines.extend(["", "--- Skills ---", ", ".join(map(str, skills))])

    certifications = resume.get("certifications") or []
    if certifications:
        lines.extend(["", "--- Certifications ---", ", ".join(map(str, certifications))])

    projects = resume.get("projects") or []
    if projects:
        lines.extend(["", "--- Projects ---"])
        for project in projects:
            entry = f"- {project.get('name') or 'N/A'}"
            if project.get("description"):
                entry += f": {project['description']}"
            tech = project.get("technologies") or []
            if tech:
                entry += f" (Technologies: {', '.join(map(str, tech))})"
            lines.append(entry)

    languages = resume.get("languages") or []
    if languages:
        lines.extend(["", "--- Languages ---", ", ".join(map(str, languages))])

    return "\n".join(lines)


def format_interview_context(
    resume: dict[str, Any] | None,
    company: str = "",
    job_description: str = "",
    anything_else: str = "",
) -> str:
    parts = [format_resume_data(resume), "", "=== JOB DETAILS ==="]
    parts.append(f"Company: {company.strip() or 'Not specified'}")
    jd = (job_description or "").strip()
    parts.append(f"\nJob Description:\n{jd}" if jd else "\nJob Description: Not provided")
    extra = (anything_else or "").strip()
    if extra:
        parts.append(f"\nAdditional Information:\n{extra}")
    return "\n".join(parts)
