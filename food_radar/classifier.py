"""Conservative rule-based filtering for local food and restaurant news."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Almaty")

CITY_PATTERNS = {
    "almaty": re.compile(r"(?<!\w)(?:алматы|алмат[еыин]|almaty|almatı)(?!\w)", re.I),
    "astana": re.compile(r"(?<!\w)(?:астан[аыеуой]|astana|нур[ -]?султан)(?!\w)", re.I),
}
FOOD = re.compile(
    r"ресторан|кафе|кофейн|бар\b|гастро|кухн|меню|шеф|ужин|бранч|"
    r"еда\b|доставк[аиу]|food|horeca|ho[. -]?re[. -]?ca|"
    r"общепит|мейрамхан|тамақ|асхана|қоғамдық тамақ|фудтех|"
    r"автоматизац.{0,20}(?:ресторан|кафе|общепит)|"
    r"касс.{0,20}(?:ресторан|кафе)|заказ.{0,20}(?:ресторан|кафе)", re.I
)
EVENT = re.compile(r"дегустац|гастроужин|фестивал|мастер[ -]?класс|ивент|"
                   r"концерт|вечеринк|мероприят|бранч|открыти[ея]|"
                   r"фест|кездесу|іс[ -]?шара", re.I)
PROMOTION = re.compile(r"скидк|акци[яию]|спецпредлож|промокод|бонус|"
                       r"подарок|2\s*\+\s*1|1\s*\+\s*1|happy hour|"
                       r"жеңілдік|тегін|розыгрыш", re.I)
INDUSTRY = re.compile(r"foodtech|фудтех|horeca|ho[. -]?re[. -]?ca|"
                      r"рынок|исследован|инвестиц|стартап|автоматизац|"
                      r"технолог|запуск|сервис|доставк|общепит", re.I)
DATE_NUMERIC = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?(?!\d)")
MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5,
          "июня": 6, "июля": 7, "августа": 8, "сентября": 9, "октября": 10,
          "ноября": 11, "декабря": 12, "қаңтар": 1, "ақпан": 2, "наурыз": 3,
          "сәуір": 4, "мамыр": 5, "маусым": 6, "шілде": 7, "тамыз": 8,
          "қыркүйек": 9, "қазан": 10, "қараша": 11, "желтоқсан": 12}
DATE_WORD = re.compile(r"(?<!\d)(\d{1,2})\s+(" + "|".join(MONTHS) + r")(?:\s+(\d{4}))?", re.I)


def _published(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str) and value:
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (result if result.tzinfo else result.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def _event_date(text: str, published: datetime | None) -> str | None:
    anchor = published.astimezone(LOCAL_TZ).date() if published else datetime.now(LOCAL_TZ).date()
    match = DATE_NUMERIC.search(text)
    if match:
        day, month, year = int(match[1]), int(match[2]), int(match[3]) if match[3] else anchor.year
    else:
        match = DATE_WORD.search(text)
        if not match:
            return None
        day, month, year = int(match[1]), MONTHS[match[2].lower()], int(match[3]) if match[3] else anchor.year
    try:
        result = date(year, month, day)
        if not match[3] and result < anchor - timedelta(days=45):
            result = result.replace(year=year + 1)
        return result.isoformat()
    except ValueError:
        return None


def normalize(raw: dict[str, Any], platform: str, source: str,
              source_cities: dict[str, str] | None = None,
              max_post_age_days: int = 14) -> dict[str, Any] | None:
    if platform == "instagram":
        post_id = raw.get("id") or raw.get("shortCode")
        caption = raw.get("caption") or ""
        text = caption if isinstance(caption, str) else ""
        url = raw.get("url") or (f"https://www.instagram.com/p/{raw['shortCode']}/" if raw.get("shortCode") else "")
        author = raw.get("ownerUsername") or raw.get("username") or ""
        published = _published(raw.get("timestamp") or raw.get("takenAt"))
        location = raw.get("locationName") or ""
        if isinstance(raw.get("location"), dict):
            location = " ".join(str(raw["location"].get(k, "")) for k in ("name", "city"))
    elif platform == "threads":
        post_id = raw.get("post_id") or raw.get("id")
        text = str(raw.get("text") or "")
        url = raw.get("url") or raw.get("permalink") or ""
        author = raw.get("username") or ""
        published = _published(raw.get("posted_at") or raw.get("timestamp"))
        location = ""
    else:
        raise ValueError(f"Unsupported platform: {platform}")
    if not post_id or not isinstance(url, str) or not url.startswith("https://"):
        return None
    if not text.strip():
        return None
    if published and published < datetime.now(timezone.utc) - timedelta(days=max_post_age_days):
        return None
    city_text = f"{text} {location}"
    cities = [city for city, pattern in CITY_PATTERNS.items() if pattern.search(city_text)]
    source_cities = source_cities or {}
    source_city = source_cities.get(str(author).lower()) or source_cities.get(source)
    if not cities and source_city in CITY_PATTERNS:
        cities = [source_city]
    if not cities and platform == "instagram" and source.startswith("#"):
        cities = [city for city, pattern in CITY_PATTERNS.items() if pattern.search(source)]
    if not FOOD.search(text):
        return None
    if not cities and INDUSTRY.search(text) and re.search(r"казахстан|қазақстан|kazakhstan", text, re.I):
        cities = ["kazakhstan"]
    if not cities:
        return None
    if EVENT.search(text):
        category = "event"
    elif PROMOTION.search(text):
        category = "promotion"
    elif INDUSTRY.search(text):
        category = "industry"
    else:
        category = "food_news"
    event_date = _event_date(text, published) if category == "event" else None
    if event_date and date.fromisoformat(event_date) < datetime.now(LOCAL_TZ).date():
        return None
    parts = urlsplit(url)
    if parts.netloc.lower() not in {"www.instagram.com", "instagram.com", "www.threads.com",
                                    "threads.com", "www.threads.net", "threads.net"}:
        return None
    clean_url = urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/") + "/", "", ""))
    return {
        "platform": platform,
        "post_id": str(post_id),
        "url": clean_url,
        "author": str(author),
        "source": source,
        "cities": cities,
        "category": category,
        "text": text.strip(),
        "published_at": published.isoformat() if published else None,
        "event_date": event_date,
    }
