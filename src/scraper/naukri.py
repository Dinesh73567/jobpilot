import os
import json
import re
from urllib.parse import quote_plus
from playwright.async_api import Page
from src.scraper.base import random_delay, safe_click, safe_type
from src.filter_engine import RawJob
from src.logger import get_logger

logger = get_logger("scraper.naukri")
COOKIES_FILE = "output/naukri_cookies.json"


# ─────────────────────────────────────────
# Login + session
# ─────────────────────────────────────────

async def login(page: Page, config) -> bool:
    """Log in to Naukri. Returns True on success."""
    if await _load_session(page):
        logger.info("Naukri: resumed from saved session")
        return True

    logger.info("Naukri: logging in fresh")
    await page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded")
    await random_delay(2, 3)

    # Close any promo popup if present
    try:
        close_btn = await page.query_selector("[class*='close']")
        if close_btn:
            await close_btn.click()
            await random_delay(0.5, 1)
    except Exception:
        pass

    # Naukri's login form uses placeholder-based inputs (verified in test)
    await safe_type(page, 'input[placeholder*="Email" i]', config.naukri_email)
    await safe_type(page, 'input[placeholder*="password" i]', config.naukri_password)
    await safe_click(page, 'button[type="submit"]')

    await random_delay(4, 6)

    if "mnjuser" in page.url or "homepage" in page.url or "nlogin" not in page.url:
        await _save_session(page)
        logger.info("Naukri: login successful")
        return True

    logger.error(f"Naukri: login failed — URL: {page.url}")
    return False


async def _save_session(page: Page):
    os.makedirs("output", exist_ok=True)
    cookies = await page.context.cookies()
    with open(COOKIES_FILE, "w") as f:
        json.dump(cookies, f)


async def _load_session(page: Page) -> bool:
    if not os.path.exists(COOKIES_FILE):
        return False
    with open(COOKIES_FILE, "r") as f:
        cookies = json.load(f)
    await page.context.add_cookies(cookies)
    await page.goto("https://www.naukri.com/mnjuser/homepage", wait_until="domcontentloaded")
    await random_delay(1.5, 2.5)
    # If we got redirected back to login, session is stale
    if "nlogin" in page.url or "login" in page.url:
        return False
    return "mnjuser" in page.url or "homepage" in page.url


# ─────────────────────────────────────────
# Search
# ─────────────────────────────────────────

def _normalize_locations(location_cfg) -> list:
    """search.location may be a string or a list."""
    if isinstance(location_cfg, list):
        return location_cfg
    return [location_cfg]


async def search_jobs(page: Page, config) -> list:
    """Search Naukri for every title × location combination."""
    all_jobs = []
    seen_ids = set()
    locations = _normalize_locations(config.search_location)

    for title in config.search_titles:
        for location in locations:
            logger.info(f"Naukri: searching '{title}' in '{location}'")

            url = _build_search_url(title, location, config)
            try:
                await page.goto(url, wait_until="domcontentloaded")
            except Exception as e:
                logger.warning(f"Naukri: failed to load search page: {e}")
                continue
            await random_delay(2.5, 4)

            # Scroll to trigger lazy loading
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
            await random_delay(1, 2)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await random_delay(1.5, 2.5)

            jobs = await _scrape_job_list(page)
            new_jobs = [j for j in jobs if j.job_id not in seen_ids]
            for j in new_jobs:
                seen_ids.add(j.job_id)
            all_jobs.extend(new_jobs)
            logger.info(f"Naukri: found {len(jobs)} ({len(new_jobs)} new) for '{title}' in '{location}'")

            await random_delay(2, 4)

    logger.info(f"Naukri: total unique jobs collected: {len(all_jobs)}")
    return all_jobs


def _build_search_url(title: str, location: str, config) -> str:
    """Naukri search URL — uses keyword + location query string format."""
    title_slug = title.lower().replace(" ", "-").replace("/", "-")
    location_slug = location.lower().replace(" ", "-")
    exp_min = config.experience_min
    exp_max = config.experience_max

    # Primary SEO URL + fallback query params
    path = f"{title_slug}-jobs-in-{location_slug}"
    query = f"k={quote_plus(title)}&l={quote_plus(location)}&experience={exp_min}"
    return f"https://www.naukri.com/{path}?{query}"


async def _scrape_job_list(page: Page) -> list:
    """Collect up to 50 job cards from current search results page."""
    jobs = []

    # Multiple selector candidates — Naukri changes these periodically
    card_selectors = [
        ".srp-jobtuple-wrapper",
        "article.jobTuple",
        ".jobTuple",
        "div.job-tuple",
    ]

    cards = []
    for sel in card_selectors:
        cards = await page.query_selector_all(sel)
        if cards:
            logger.debug(f"Naukri: matched {len(cards)} cards with selector '{sel}'")
            break

    if not cards:
        logger.warning("Naukri: no job cards found on this page")
        return jobs

    for card in cards[:50]:
        try:
            job = await _parse_job_card(card)
            if job:
                jobs.append(job)
        except Exception as e:
            logger.debug(f"Naukri card parse error: {e}")

    return jobs


async def _text(element, selector: str) -> str:
    """Safely get inner text from a child selector."""
    if element is None:
        return ""
    try:
        el = await element.query_selector(selector)
        if el:
            return (await el.inner_text()).strip()
    except Exception:
        pass
    return ""


async def _parse_job_card(card) -> RawJob | None:
    try:
        # Title + URL
        title_el = await card.query_selector("a.title, a.jobTitle, a.title-link")
        if not title_el:
            return None
        title = (await title_el.inner_text()).strip()
        href = await title_el.get_attribute("href") or ""

        # Job ID — Naukri's job URL usually ends with a numeric ID or hyphenated slug
        job_id_match = re.search(r'-(\d{5,})(?:[/?]|$)', href)
        job_id = job_id_match.group(1) if job_id_match else href.split("?")[0]

        # Company
        company = await _text(card, "a.comp-name") \
            or await _text(card, ".companyInfo .subTitle") \
            or await _text(card, "a.subTitle") \
            or "Unknown"

        # Experience
        experience_text = await _text(card, ".expwdth") \
            or await _text(card, ".experience") \
            or await _text(card, "span.exp")
        exp_min, exp_max = _parse_experience(experience_text)

        # Salary
        salary_text = await _text(card, ".sal") \
            or await _text(card, ".salary") \
            or await _text(card, "span.sal-wrap")
        sal_min, sal_max = _parse_salary(salary_text)

        # Location
        location = await _text(card, ".locWdth") \
            or await _text(card, ".location") \
            or await _text(card, "span.loc")

        # Skills tags
        skills = []
        for sel in [".tags-gt li", ".tags li", "ul.tags li"]:
            els = await card.query_selector_all(sel)
            if els:
                for el in els:
                    try:
                        text = (await el.inner_text()).strip()
                        if text:
                            skills.append(text)
                    except Exception:
                        continue
                break

        # Apply-type heuristic — detail page has the real button; default to naukri_apply here
        apply_type = "naukri_apply"

        return RawJob(
            platform="naukri",
            job_id=str(job_id),
            title=title,
            company=company,
            location=location,
            salary_text=salary_text,
            salary_min=sal_min,
            salary_max=sal_max,
            experience_text=experience_text,
            experience_min=exp_min,
            experience_max=exp_max,
            required_skills=skills,
            apply_type=apply_type,
            job_url=href if href.startswith("http") else f"https://www.naukri.com{href}",
        )
    except Exception as e:
        logger.debug(f"Naukri parse error: {e}")
        return None


def _parse_experience(text: str) -> tuple:
    """Parse '2-4 Yrs' → (2, 4). Returns (None, None) if not parseable."""
    if not text:
        return None, None
    match = re.search(r'(\d+)\s*[-–]\s*(\d+)', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r'(\d+)\+', text)
    if match:
        return int(match.group(1)), 99
    match = re.search(r'(\d+)', text)
    if match:
        n = int(match.group(1))
        return n, n
    return None, None


def _parse_salary(text: str) -> tuple:
    """Parse '8-12 Lacs PA' → (800000, 1200000)."""
    if not text or "not disclosed" in text.lower():
        return None, None
    match = re.search(r'(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(lac|lpa|lakh)', text, re.I)
    if match:
        lo = float(match.group(1)) * 100000
        hi = float(match.group(2)) * 100000
        return int(lo), int(hi)
    return None, None


# ─────────────────────────────────────────
# Apply
# ─────────────────────────────────────────

async def apply_job(page: Page, job: RawJob, config) -> str:
    """Go to job page and click Apply. Handles dry-run + external redirect."""
    if config.dry_run:
        logger.info(f"DRY RUN: would apply to '{job.title}' @ {job.company}")
        return "dry_run_applied"

    try:
        await page.goto(job.job_url, wait_until="domcontentloaded")
        await random_delay(2.5, 4)

        # Detect apply button — multiple fallbacks
        apply_selectors = [
            "button#apply-button",
            "button.apply-button",
            "button:has-text('Apply')",
        ]

        apply_btn = None
        for sel in apply_selectors:
            apply_btn = await page.query_selector(sel)
            if apply_btn:
                break

        if not apply_btn:
            logger.warning(f"Naukri: no apply button on page for {job.title}")
            return "failed"

        btn_text = (await apply_btn.inner_text()).strip().lower()
        if "company site" in btn_text or "external" in btn_text:
            logger.info(f"Naukri: {job.title} redirects to company site — flagging")
            return "skipped_external"

        # Already-applied detection: button text is "Applied" (not "Apply")
        if btn_text in ("applied", "already applied") or btn_text.startswith("applied "):
            logger.info(f"Naukri: {job.title} already applied — skipping")
            return "already_applied"

        await apply_btn.scroll_into_view_if_needed()
        await random_delay(0.5, 1.2)
        await apply_btn.click()
        await random_delay(2.5, 4)

        # Confirmation modal ("Applied successfully") or chatbot flow
        # Try to detect success banner
        success_selectors = [
            "text=/successfully applied/i",
            "text=/you have successfully/i",
            ".apply-status-msg",
        ]
        for sel in success_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    logger.info(f"Naukri applied: {job.title} @ {job.company}")
                    return "applied"
            except Exception:
                continue

        # Chatbot screening flow — try to auto-answer
        chatbot = await page.query_selector(".chatbot_MessageContainer, #chatbot_Drawer")
        if chatbot:
            logger.info(f"Naukri: chatbot opened for '{job.title}' — running Q&A handler")
            result = await _handle_chatbot(page, config, job.title)
            if result == "applied":
                logger.info(f"Naukri applied (via chatbot): {job.title} @ {job.company}")
                return "applied"
            logger.warning(f"Naukri chatbot result for {job.title}: {result}")
            return result

        # No explicit confirmation but no error — assume applied
        logger.info(f"Naukri apply clicked (no confirmation detected): {job.title} @ {job.company}")
        return "applied"

    except Exception as e:
        logger.error(f"Naukri apply error for {job.title}: {e}")
        return "failed"


# ─────────────────────────────────────────
# Chatbot Q&A handler
# ─────────────────────────────────────────

async def _handle_chatbot(page, config, job_title: str) -> str:
    """Iterate through Naukri chatbot questions. Returns 'applied' | 'chatbot_stuck'."""
    last_question = None
    stuck_count = 0
    max_iterations = 20

    for i in range(max_iterations):
        await random_delay(1.8, 3)

        # Success detection: chatbot closed OR success banner visible
        if await _chatbot_is_done(page):
            return "applied"

        question_text = await _latest_chatbot_question(page)
        if not question_text:
            logger.debug(f"Chatbot iter {i+1}: no question text yet")
            stuck_count += 1
            if stuck_count >= 3:
                return "chatbot_stuck"
            continue

        if question_text == last_question:
            stuck_count += 1
            if stuck_count >= 2:
                logger.warning(f"Chatbot stuck on: {question_text[:100]}")
                return "chatbot_stuck"
            continue

        last_question = question_text
        stuck_count = 0
        logger.info(f"Chatbot Q{i+1}: {question_text[:120]}")

        answer = _match_chatbot_answer(question_text, config)
        logger.info(f"Chatbot A{i+1}: {answer}")

        submitted = await _fill_chatbot_answer(page, answer, question_text, config)
        if not submitted:
            logger.warning(f"Chatbot: couldn't answer '{question_text[:80]}'")
            return "chatbot_stuck"

    logger.warning("Chatbot: max iterations reached without completion")
    return "chatbot_stuck"


async def _chatbot_is_done(page) -> bool:
    """Detect successful application after chatbot flow."""
    # Drawer gone
    drawer = await page.query_selector(".chatbot_MessageContainer")
    if not drawer:
        return True
    # Check if drawer is hidden
    try:
        visible = await drawer.is_visible()
        if not visible:
            return True
    except Exception:
        pass

    # Success banners
    for sel in [
        "text=/successfully applied/i",
        "text=/application sent/i",
        "text=/you have applied/i",
        "text=/your application has been submitted/i",
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                return True
        except Exception:
            continue
    return False


async def _latest_chatbot_question(page) -> str:
    """Return text of the most recent bot message in the chatbot drawer."""
    selectors = [
        ".chatbot_MessageContainer li.botItem .botMsg",
        ".chatbot_MessageContainer .botMsg",
        "li.botItem .botMsg",
        ".botMsg",
    ]
    for sel in selectors:
        msgs = await page.query_selector_all(sel)
        if msgs:
            try:
                text = (await msgs[-1].inner_text()).strip()
                if text:
                    return text
            except Exception:
                continue
    return ""


def _match_chatbot_answer(question: str, config) -> str:
    """Map question keywords → config value."""
    q = question.lower()

    # Disability / diversity — NEVER claim a disability you don't have
    if any(kw in q for kw in ["disabilit", "diversity", "inclusive"]):
        return "no"

    # Yes/no style
    if any(kw in q for kw in ["authoriz", "authoris", "eligible to work", "work permit", "legally"]):
        return "yes"
    if "relocat" in q:
        return "yes" if config.willing_to_relocate else "no"
    if any(kw in q for kw in ["willing to", "are you okay", "comfortable with", "open to"]):
        return "yes"
    if "immediate joiner" in q:
        return "yes" if config.notice_period_days <= 15 else "no"

    # Notice period
    if "notice" in q:
        return str(config.notice_period_days)

    # CTC
    if ("current" in q or "present" in q) and any(k in q for k in ["ctc", "salary", "package", "compensation"]):
        return str(config.current_ctc_lpa)
    if ("expected" in q or "expecting" in q or "desired" in q) and any(k in q for k in ["ctc", "salary", "package", "compensation"]):
        return str(config.expected_ctc_lpa)
    if "ctc" in q or "salary" in q:
        return str(config.current_ctc_lpa)

    # Experience
    if "year" in q and ("experience" in q or "exp" in q):
        if any(kw in q for kw in ["react native", "react-native", "rn", "relevant"]):
            return str(config.relevant_experience_years)
        return str(config.total_experience_years)

    # Phone
    if any(kw in q for kw in ["phone", "mobile", "contact number", "whatsapp"]):
        return config.phone

    # Location — match preferred/choose/select location questions
    if "location" in q or "city" in q or "where are you" in q or "based in" in q:
        return config.current_location

    # Qualification
    if any(kw in q for kw in ["qualif", "degree", "highest education", "education"]):
        return config.highest_qualification

    # Default
    return "yes"


def _pick_chip_for_answer(answer: str, chip_labels: list, question_lower: str = "") -> str | None:
    """Pick the chip label that best matches the answer, with semantic handling."""
    if not chip_labels:
        return None
    a = str(answer).strip().lower()

    # Semantic: disability "no" → "I don't have a disability" / "no disability"
    if "disabilit" in question_lower or "diversity" in question_lower:
        if a == "no":
            for lbl in chip_labels:
                lbl_l = lbl.lower()
                if "don't" in lbl_l or "don t" in lbl_l or "do not" in lbl_l or "no disability" in lbl_l:
                    return lbl
        if a == "yes":
            for lbl in chip_labels:
                if lbl.lower().startswith("i have"):
                    return lbl

    # Semantic: yes/no
    if a in ("yes", "no"):
        for lbl in chip_labels:
            lbl_l = lbl.lower().strip()
            if lbl_l == a:
                return lbl
            if a == "yes" and lbl_l.startswith(("yes", "i have", "available", "i am")):
                return lbl
            if a == "no" and (lbl_l.startswith(("no", "i don", "not ", "i do not")) or "don't" in lbl_l):
                return lbl

    # Generic: exact/contains match
    for lbl in chip_labels:
        lbl_l = lbl.lower()
        if lbl_l == a or a in lbl_l or (a and lbl_l in a):
            return lbl

    return None


def _notice_days_to_chip_label(days: int, chip_labels: list) -> str | None:
    """Pick the best chip label for a given notice-period days value."""
    if not chip_labels:
        return None

    # Priority mapping
    if days <= 15:
        targets = ["15 days or less", "immediate", "15 days", "less than 15"]
    elif days <= 30:
        targets = ["1 month", "30 days"]
    elif days <= 60:
        targets = ["2 months", "60 days", "1-2 months"]
    elif days <= 90:
        targets = ["3 months", "90 days", "2-3 months"]
    else:
        targets = ["more than 3 months", "more than 90", "3+ months", "serving notice"]

    labels_lower = [(lbl.lower(), lbl) for lbl in chip_labels]
    for t in targets:
        for lbl_lower, lbl_original in labels_lower:
            if t in lbl_lower:
                return lbl_original
    # Fallback: first chip
    return chip_labels[0]


async def _fill_chatbot_answer(page, answer, question: str = "", config=None) -> bool:
    """Attempt to fill + submit. Order: multiselect checkboxes, single-select radios, contenteditable text."""
    q_lower = question.lower() if question else ""

    # 0) Multiselect checkboxes (e.g. location picker) — pick all matching + save
    mcc_boxes = await page.query_selector_all(".chatbot_MessageContainer .mcc__checkbox, .multicheckboxes-container input[type='checkbox']")
    if mcc_boxes:
        logger.debug(f"Chatbot: multiselect checkboxes detected ({len(mcc_boxes)} options)")
        # Build candidate answer list — location list from config + answer
        candidates = []
        if config is not None:
            if isinstance(config.search_location, list):
                candidates.extend(config.search_location)
            else:
                candidates.append(config.search_location)
            if config.current_location:
                candidates.append(config.current_location)
        candidates.append(str(answer))

        clicked_any = False
        for box in mcc_boxes:
            try:
                if not await box.is_visible():
                    # Label is visible; click label sibling
                    pass
                box_id = await box.get_attribute("id") or ""
                box_val = (await box.get_attribute("value") or "").lower()
                # Find the label text
                label = None
                if box_id:
                    label = await page.query_selector(f"label[for='{box_id}']")
                label_text = (await label.inner_text()).strip().lower() if label else box_val

                if "skip" in label_text:
                    continue

                for cand in candidates:
                    cand_lower = str(cand).strip().lower()
                    if cand_lower and (cand_lower in label_text or label_text in cand_lower):
                        target = label or box
                        try:
                            await target.scroll_into_view_if_needed()
                            await random_delay(0.2, 0.5)
                            await target.click()
                            clicked_any = True
                            logger.debug(f"Multiselect: checked '{label_text}'")
                            await random_delay(0.3, 0.6)
                        except Exception as e:
                            logger.debug(f"Multiselect click failed: {e}")
                        break
            except Exception as e:
                logger.debug(f"Multiselect iter error: {e}")
                continue

        if clicked_any:
            # Click save button below the checkboxes
            if await _click_multiselect_save(page):
                await random_delay(1, 2)
                return True
            # Fallback: send button / Enter
            if await _click_chatbot_send(page):
                return True
            await page.keyboard.press("Enter")
            await random_delay(0.8, 1.5)
            return True

    # 0b) Standalone chip buttons (.chatbot_Chip — e.g. disability "Yes/No", reply suggestions)
    chip_elements = await page.query_selector_all(".chatbot_Chips .chatbot_Chip, div.chatbot_Chip")
    if chip_elements:
        logger.debug(f"Chatbot: standalone chips detected ({len(chip_elements)} options)")
        chip_labels = []
        visible_chips = []
        for chip in chip_elements:
            try:
                if await chip.is_visible():
                    text = (await chip.inner_text()).strip()
                    if text:
                        chip_labels.append(text)
                        visible_chips.append(chip)
            except Exception:
                continue

        target = _pick_chip_for_answer(str(answer), chip_labels, q_lower)
        if target is not None:
            idx = chip_labels.index(target)
            try:
                await visible_chips[idx].scroll_into_view_if_needed()
                await random_delay(0.3, 0.6)
                await visible_chips[idx].click()
                logger.debug(f"Chip: clicked '{target}'")
                await random_delay(0.8, 1.5)
                await _click_chatbot_send(page)
                return True
            except Exception as e:
                logger.debug(f"Chip click failed: {e}")

    # 1) Single-select radio buttons (e.g. notice period, Yes/No)
    radio_containers = await page.query_selector_all(".chatbot_MessageContainer .ssrc__radio-btn-container")
    if radio_containers:
        logger.debug(f"Chatbot: single-select radios detected ({len(radio_containers)} options)")
        # Collect all labels
        chip_labels = []
        chip_elements = []
        for container in radio_containers:
            try:
                label_el = await container.query_selector("label.ssrc__label, label")
                if label_el:
                    text = (await label_el.inner_text()).strip()
                    if text:
                        chip_labels.append(text)
                        chip_elements.append(label_el)
            except Exception:
                continue

        # Special case: notice period — map days to chip
        target_label = None
        if "notice" in q_lower and config is not None:
            target_label = _notice_days_to_chip_label(config.notice_period_days, chip_labels)

        # General match: answer string against chip labels
        answer_lower = str(answer).strip().lower()
        if not target_label:
            for lbl in chip_labels:
                lbl_l = lbl.lower()
                if lbl_l == answer_lower or answer_lower in lbl_l or lbl_l in answer_lower:
                    target_label = lbl
                    break

        # Yes/No fuzzy: if answer is yes/no, look for matching chip
        if not target_label and answer_lower in ("yes", "no"):
            for lbl in chip_labels:
                if lbl.lower().startswith(answer_lower):
                    target_label = lbl
                    break

        if target_label:
            idx = chip_labels.index(target_label)
            try:
                await chip_elements[idx].scroll_into_view_if_needed()
                await random_delay(0.3, 0.6)
                await chip_elements[idx].click()
                logger.debug(f"Radio: clicked '{target_label}'")
                await random_delay(0.8, 1.5)
                # Some radios auto-advance; also try send
                await _click_chatbot_send(page)
                return True
            except Exception as e:
                logger.debug(f"Radio click failed: {e}")

    # 2) Contenteditable div (text input)
    ce_selectors = [
        ".chatbot_MessageContainer div.textArea[contenteditable='true']",
        ".chatbot_InputContainer div[contenteditable='true']",
        "div.textArea[contenteditable='true']",
        "[contenteditable='true'].textArea",
    ]
    for sel in ce_selectors:
        inputs = await page.query_selector_all(sel)
        for inp in inputs:
            try:
                if not await inp.is_visible():
                    continue
                await inp.click()
                await random_delay(0.3, 0.6)
                # Clear via keyboard select-all + backspace
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Meta+A")
                await page.keyboard.press("Backspace")
                await random_delay(0.1, 0.3)
                await page.keyboard.type(str(answer), delay=60)
                await random_delay(0.5, 1)
                if await _click_chatbot_send(page):
                    return True
                # Fallback: press Enter
                await page.keyboard.press("Enter")
                await random_delay(0.8, 1.5)
                return True
            except Exception as e:
                logger.debug(f"Contenteditable fill failed ({sel}): {e}")
                continue

    # 2) Plain text/number inputs (rare fallback)
    for sel in [
        ".chatbot_MessageContainer input[type='text']",
        ".chatbot_MessageContainer input[type='number']",
        ".chatbot_MessageContainer textarea",
    ]:
        inputs = await page.query_selector_all(sel)
        for inp in inputs:
            try:
                if not await inp.is_visible():
                    continue
                await inp.click()
                try:
                    await inp.fill("")
                except Exception:
                    pass
                await inp.type(str(answer), delay=60)
                await random_delay(0.5, 1)
                if await _click_chatbot_send(page):
                    return True
                await page.keyboard.press("Enter")
                return True
            except Exception as e:
                logger.debug(f"Fallback input fill failed ({sel}): {e}")
                continue

    return False


async def _click_multiselect_save(page) -> bool:
    """Click the save/next button after selecting multiselect checkboxes."""
    save_selectors = [
        ".chatbot_MessageContainer button.save",
        ".chatbot_MessageContainer button.btnSave",
        ".chatbot_MessageContainer [class*='save-btn']",
        ".chatbot_MessageContainer [class*='Save']",
        ".multicheckboxes-container ~ button",
        ".multicheckboxes-container + div button",
        "button:has-text('Save')",
        "button:has-text('Submit')",
        "button:has-text('Next')",
    ]
    for sel in save_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await random_delay(1, 2)
                logger.debug(f"Multiselect save clicked ({sel})")
                return True
        except Exception as e:
            logger.debug(f"Multiselect save try failed ({sel}): {e}")
            continue
    return False


async def _click_chatbot_send(page) -> bool:
    """Click chatbot send/save button. Button is sibling of .chatbot_MessageContainer."""
    send_selectors = [
        ".sendMsgbtn_container .sendMsg",
        ".sendMsgbtn_container div.send",
        ".chatbot_DrawerContentWrapper .sendMsg",
        "div.send > div.sendMsg",
        "div[id^='sendMsg_'] .sendMsg",
        "div[class='sendMsg']",
        ".chatbot_InputContainer div.sendMsg",
        ".footerWrapper [class*='send']",
    ]
    for sel in send_selectors:
        btn = await page.query_selector(sel)
        if not btn:
            continue
        try:
            if not await btn.is_visible():
                continue
            await btn.click()
            await random_delay(1, 2)
            return True
        except Exception as e:
            logger.debug(f"Send click failed ({sel}): {e}")
            continue
    return False
