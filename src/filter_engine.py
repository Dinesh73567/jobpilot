from dataclasses import dataclass
from src.logger import get_logger

logger = get_logger("filter_engine")


@dataclass
class RawJob:
    platform: str
    job_id: str
    title: str
    company: str
    location: str
    salary_text: str
    salary_min: int | None
    salary_max: int | None
    experience_text: str
    experience_min: int | None
    experience_max: int | None
    required_skills: list
    apply_type: str   # "easy_apply" | "external" | "naukri_apply"
    job_url: str
    posted_date: str = ""


@dataclass
class FilteredJob:
    raw: RawJob
    decision: str        # "apply" | "skip" | "flag"
    reason: str
    skills_match_pct: float


def calculate_skills_match(required: list, my_skills: list) -> float:
    if not required:
        return 100.0
    required_lower = [s.lower().strip() for s in required]
    my_lower = [s.lower().strip() for s in my_skills]
    matches = sum(1 for s in required_lower if any(s in m or m in s for m in my_lower))
    return round((matches / len(required_lower)) * 100, 1)


def filter_jobs(raw_jobs: list, config, tracker) -> list:
    results = []

    for job in raw_jobs:
        decision, reason = _evaluate(job, config, tracker)
        match_pct = calculate_skills_match(job.required_skills, config.my_skills)

        results.append(FilteredJob(
            raw=job,
            decision=decision,
            reason=reason,
            skills_match_pct=match_pct
        ))

        logger.debug(f"[{decision.upper()}] {job.title} @ {job.company} — {reason}")

    applied = sum(1 for j in results if j.decision == "apply")
    skipped = sum(1 for j in results if j.decision == "skip")
    flagged = sum(1 for j in results if j.decision == "flag")
    logger.info(f"Filter results: {applied} to apply, {skipped} skipped, {flagged} flagged")

    return results


def _evaluate(job: RawJob, config, tracker) -> tuple:
    # Rule 1: Already applied?
    if tracker.already_applied(job.job_id):
        return "skip", "already applied"

    # Rule 2: Company blacklisted?
    company_lower = job.company.lower()
    for blocked in config.blacklist_companies:
        if blocked.lower() in company_lower:
            return "skip", f"company blacklisted: {blocked}"

    # Rule 3: External application?
    if job.apply_type == "external":
        return "flag", "external application site"

    # Rule 4: Salary check (only if salary is shown)
    if job.salary_min is not None and job.salary_max is not None:
        if job.salary_max < config.salary_min:
            return "skip", f"salary too low: {job.salary_max:,} < {config.salary_min:,}"
        if job.salary_min > config.salary_max:
            return "skip", f"salary too high: {job.salary_min:,} > {config.salary_max:,}"
    elif config.skip_if_salary_hidden:
        return "skip", "salary not shown"

    # Rule 5: Experience check (only if shown)
    if job.experience_min is not None:
        if job.experience_min > config.experience_max:
            return "skip", f"requires too much experience: {job.experience_min}+ years"
    if job.experience_max is not None:
        if job.experience_max < config.experience_min:
            return "skip", f"requires too little experience: {job.experience_max} years max"

    # Rule 6: Skills match
    match_pct = calculate_skills_match(job.required_skills, config.my_skills)
    if match_pct < config.skills_match_pct:
        return "skip", f"skills match too low: {match_pct}% < {config.skills_match_pct}%"

    return "apply", f"passed all filters ({match_pct}% skills match)"
