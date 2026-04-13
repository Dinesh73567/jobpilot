import os
import re
import yaml
from dataclasses import dataclass, field
from dotenv import load_dotenv
from src.logger import get_logger

logger = get_logger("config_manager")

class ConfigError(Exception):
    pass

@dataclass
class Config:
    # LinkedIn
    linkedin_email: str
    linkedin_password: str
    # Naukri
    naukri_email: str
    naukri_password: str
    # Search
    search_titles: list
    search_location: str
    search_remote: bool = False
    search_date_posted: str = "month"
    # Filters
    salary_min: int = 0
    salary_max: int = 99999999
    experience_min: int = 0
    experience_max: int = 99
    skills_match_pct: int = 60
    skip_if_salary_hidden: bool = False
    my_skills: list = field(default_factory=list)
    # Blacklist
    blacklist_companies: list = field(default_factory=list)
    # Limits
    daily_apply_limit: int = 40
    # Personal (for screening / chatbot answers)
    phone: str = ""
    total_experience_years: int = 0
    relevant_experience_years: int = 0
    current_ctc_lpa: float = 0.0
    expected_ctc_lpa: float = 0.0
    notice_period_days: int = 30
    current_location: str = ""
    willing_to_relocate: bool = True
    highest_qualification: str = ""
    # Resume
    resume_path: str = "./assets/resume.pdf"
    # Schedule
    schedule_cron: str = "0 9 * * 1-5"
    background_interval_min: int = 30
    # Bot behaviour
    dry_run: bool = False
    headless: bool = True
    delay_min_sec: float = 0.5
    delay_max_sec: float = 2.5
    max_retries: int = 2
    timeout_sec: int = 30
    # Output
    csv_path: str = "./output/applied_jobs.csv"
    # Notifications
    notifications_enabled: bool = False


def _substitute_env_vars(value: str) -> str:
    """Replace ${VAR} placeholders with environment variable values."""
    pattern = r'\$\{(\w+)\}'

    def replacer(match):
        var_name = match.group(1)
        env_value = os.environ.get(var_name)
        if env_value is None:
            raise ConfigError(f"Environment variable '{var_name}' is not set. Check your .env file.")
        return env_value

    return re.sub(pattern, replacer, value)


def _process_value(value):
    """Recursively substitute env vars in strings."""
    if isinstance(value, str):
        return _substitute_env_vars(value)
    elif isinstance(value, dict):
        return {k: _process_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_process_value(item) for item in value]
    return value


def load(config_path: str = "config.yaml") -> Config:
    """Load config.yaml, inject .env values, validate, and return Config object."""

    # Load .env file
    load_dotenv()

    # Read YAML
    if not os.path.exists(config_path):
        raise ConfigError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        raw = yaml.safe_load(f)

    # Substitute env vars
    raw = _process_value(raw)

    # Extract values with defaults
    try:
        config = Config(
            linkedin_email=raw["linkedin"]["email"],
            linkedin_password=raw["linkedin"]["password"],
            naukri_email=raw["naukri"]["email"],
            naukri_password=raw["naukri"]["password"],
            search_titles=raw["search"]["titles"],
            search_location=raw["search"]["location"],
            search_remote=raw["search"].get("remote", False),
            search_date_posted=raw["search"].get("date_posted", "month"),
            salary_min=raw.get("filters", {}).get("salary_min", 0),
            salary_max=raw.get("filters", {}).get("salary_max", 99999999),
            experience_min=raw.get("filters", {}).get("experience_min", 0),
            experience_max=raw.get("filters", {}).get("experience_max", 99),
            skills_match_pct=raw.get("filters", {}).get("skills_match_pct", 60),
            skip_if_salary_hidden=raw.get("filters", {}).get("skip_if_salary_hidden", False),
            my_skills=raw.get("filters", {}).get("my_skills", []),
            blacklist_companies=raw.get("blacklist", {}).get("companies", []),
            daily_apply_limit=raw.get("limits", {}).get("daily_apply", 40),
            phone=str(raw.get("personal", {}).get("phone", "")),
            total_experience_years=raw.get("personal", {}).get("total_experience_years", 0),
            relevant_experience_years=raw.get("personal", {}).get("relevant_experience_years", 0),
            current_ctc_lpa=float(raw.get("personal", {}).get("current_ctc_lpa", 0) or 0),
            expected_ctc_lpa=float(raw.get("personal", {}).get("expected_ctc_lpa", 0) or 0),
            notice_period_days=raw.get("personal", {}).get("notice_period_days", 30),
            current_location=raw.get("personal", {}).get("current_location", ""),
            willing_to_relocate=raw.get("personal", {}).get("willing_to_relocate", True),
            highest_qualification=raw.get("personal", {}).get("highest_qualification", ""),
            resume_path=raw.get("resume", {}).get("path", "./assets/resume.pdf"),
            schedule_cron=raw.get("schedule", {}).get("cron", "0 9 * * 1-5"),
            background_interval_min=raw.get("schedule", {}).get("background_interval_min", 30),
            dry_run=raw.get("bot", {}).get("dry_run", False),
            headless=raw.get("bot", {}).get("headless", True),
            delay_min_sec=raw.get("bot", {}).get("delay_min_sec", 0.5),
            delay_max_sec=raw.get("bot", {}).get("delay_max_sec", 2.5),
            max_retries=raw.get("bot", {}).get("max_retries", 2),
            timeout_sec=raw.get("bot", {}).get("timeout_sec", 30),
            csv_path=raw.get("output", {}).get("csv_path", "./output/applied_jobs.csv"),
            notifications_enabled=raw.get("notifications", {}).get("enabled", False),
        )
    except KeyError as e:
        raise ConfigError(f"Missing required config field: {e}")

    # Validate
    _validate(config)

    logger.info("Config loaded successfully")
    return config


def _validate(config: Config):
    if not config.linkedin_email or not config.linkedin_password:
        raise ConfigError("LinkedIn email and password are required")

    if not config.naukri_email or not config.naukri_password:
        raise ConfigError("Naukri email and password are required")

    if not config.search_titles:
        raise ConfigError("At least one job title is required in search.titles")

    if config.salary_min > config.salary_max:
        raise ConfigError(f"salary_min ({config.salary_min}) cannot be greater than salary_max ({config.salary_max})")

    if config.experience_min > config.experience_max:
        raise ConfigError(f"experience_min ({config.experience_min}) cannot be greater than experience_max ({config.experience_max})")

    if not 0 <= config.skills_match_pct <= 100:
        raise ConfigError(f"skills_match_pct must be between 0 and 100, got: {config.skills_match_pct}")

    if not os.path.exists(config.resume_path):
        logger.warning(f"Resume file not found: {config.resume_path} — place your resume there before applying")

    if config.daily_apply_limit < 1:
        raise ConfigError("daily_apply_limit must be at least 1")

    logger.debug("Config validation passed")
