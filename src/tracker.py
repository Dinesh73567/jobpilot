import os
import csv
import asyncio
from datetime import date, datetime
from src.logger import get_logger

logger = get_logger("tracker")

CSV_COLUMNS = [
    "date", "platform", "job_id", "title", "company",
    "location", "salary_min", "salary_max", "skills_match_pct",
    "apply_type", "status", "reason", "job_url"
]


class Tracker:
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self._lock = asyncio.Lock()
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        self._ensure_csv_exists()

    def _ensure_csv_exists(self):
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writeheader()
            logger.info(f"Created new CSV at: {self.csv_path}")

    async def log(self, job_data: dict, status: str, reason: str = ""):
        """Append one row to the CSV. job_data must contain the required fields."""
        row = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "platform": job_data.get("platform", ""),
            "job_id": job_data.get("job_id", ""),
            "title": job_data.get("title", ""),
            "company": job_data.get("company", ""),
            "location": job_data.get("location", ""),
            "salary_min": job_data.get("salary_min", ""),
            "salary_max": job_data.get("salary_max", ""),
            "skills_match_pct": job_data.get("skills_match_pct", ""),
            "apply_type": job_data.get("apply_type", ""),
            "status": status,
            "reason": reason,
            "job_url": job_data.get("job_url", ""),
        }

        async with self._lock:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
                writer.writerow(row)

        logger.info(f"Logged: [{status}] {job_data.get('title')} at {job_data.get('company')}")

    def get_today_count(self) -> int:
        """Return number of jobs with status='applied' logged today."""
        today = date.today().strftime("%Y-%m-%d")
        count = 0

        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["status"] == "applied" and row["date"].startswith(today):
                    count += 1

        return count

    def already_applied(self, job_id: str) -> bool:
        """Check if this job_id was already applied to (any status)."""
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["job_id"] == job_id and row["status"] == "applied":
                    return True
        return False

    def get_all_jobs(self) -> list:
        """Return all rows as a list of dicts."""
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
