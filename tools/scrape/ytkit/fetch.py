"""Bounded, validated extraction from YouTube's transcript panel."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from .driver import browser_session, make_driver
from .models import FetchResult, Segment, Transcript, ValidationError

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def normalize_video_id(value: str) -> str:
    value = value.strip()
    if VIDEO_ID.fullmatch(value):
        return value
    parsed = urlparse(value)
    if parsed.scheme in ("http", "https") and parsed.netloc in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        candidate = parse_qs(parsed.query).get("v", [""])[0]
        if VIDEO_ID.fullmatch(candidate):
            return candidate
    raise ValueError("invalid YouTube video ID or watch URL")


def to_seconds(stamp: str) -> float:
    """Parse h:mm:ss, mm:ss, or seconds; return -1 for malformed input."""
    try:
        parts = stamp.strip().split(":")
        if not 1 <= len(parts) <= 3 or any(not p for p in parts):
            return -1.0
        nums = [float(p) for p in parts]
        if any(n < 0 for n in nums):
            return -1.0
        return nums[-1] + (nums[-2] * 60 if len(nums) > 1 else 0) + (nums[-3] * 3600 if len(nums) > 2 else 0)
    except (TypeError, ValueError):
        return -1.0


def parse_rows(rows) -> tuple[Segment, ...]:
    """Convert DOM rows without guessing end times."""
    result = []
    for index, row in enumerate(rows or []):
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise ValidationError("malformed transcript row %d" % index)
        start = to_seconds(str(row[0]))
        text = re.sub(r"\s+", " ", str(row[1])).strip()
        if start < 0 or not text:
            raise ValidationError("invalid transcript row %d" % index)
        result.append(Segment(start=start, text=text, source_index=index))
    if any(b.start < a.start for a, b in zip(result, result[1:])):
        raise ValidationError("transcript rows are not ordered")
    return tuple(result)


def _failure(video_id, code, stage, diagnostic, retryable=False):
    status = "blocked" if code in {"blocked", "consent_required"} else "unavailable" if code == "unavailable" else "failed"
    return FetchResult(video_id, status, error_code=code, stage=stage, diagnostic=diagnostic, retryable=retryable)


def fetch(video_id: str, driver=None, quiet: bool = False, deadline: float = 45.0) -> FetchResult:
    video_id = normalize_video_id(video_id)
    own = driver is None
    if own:
        driver = make_driver()
    end = time.monotonic() + deadline
    try:
        from selenium.common.exceptions import TimeoutException, WebDriverException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
        driver.set_page_load_timeout(max(1, deadline))
        driver.get("https://www.youtube.com/watch?v=" + video_id)
        if time.monotonic() >= end:
            return _failure(video_id, "deadline_exceeded", "navigation", "video deadline expired", True)
        wait = WebDriverWait(driver, max(0.1, end - time.monotonic()))
        # Presence is intentional: YouTube often renders the control off-screen.
        expand = wait.until(EC.presence_of_element_located((By.XPATH, "//*[@id='expand']")))
        driver.execute_script("arguments[0].click();", expand)
        button = wait.until(EC.presence_of_element_located((By.XPATH, "//button[contains(translate(., 'ST', 'st'), 'transcript')]")))
        driver.execute_script("arguments[0].click();", button)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "ytd-transcript-segment-renderer")))
        rows = driver.execute_script("""
          return Array.from(document.querySelectorAll('ytd-transcript-segment-renderer')).map(el => {
            const t=el.querySelector('.segment-timestamp'), x=el.querySelector('.segment-text');
            return [t ? t.textContent.trim() : '', x ? x.textContent.trim() : ''];
          });
        """)
        segments = parse_rows(rows)
        if not segments:
            return _failure(video_id, "unavailable", "collection", "transcript panel is empty")
        transcript = Transcript(video_id, "https://www.youtube.com/watch?v=" + video_id,
                                None, None, segments, datetime.now(timezone.utc).isoformat())
        return FetchResult(video_id, "success", transcript=transcript, completeness="verified")
    except ValidationError as exc:
        return _failure(video_id, "invalid_row", "parsing", str(exc))
    except (TimeoutException, WebDriverException) as exc:
        return _failure(video_id, "extraction_error", "browser", str(exc), True)
    finally:
        if own and driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def fetch_many(video_ids, quiet: bool = False, driver=None, **kwargs) -> dict[str, FetchResult]:
    """Fetch in order with one owned session; duplicate IDs are removed."""
    ids = list(dict.fromkeys(normalize_video_id(v) for v in video_ids))
    if driver is not None:
        return {v: fetch(v, driver=driver, quiet=quiet, **kwargs) for v in ids}
    with browser_session() as session:
        return {v: fetch(v, driver=session, quiet=quiet, **kwargs) for v in ids}
