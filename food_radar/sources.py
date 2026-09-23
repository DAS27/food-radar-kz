"""Fetch public social posts through Apify Actors."""

from __future__ import annotations

import json
import os
import ssl
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


@dataclass(frozen=True)
class Job:
    platform: str
    source: str
    actor: str
    payload: dict[str, Any]


def _tls_context() -> ssl.SSLContext:
    bundle = os.environ.get("SSL_CERT_FILE")
    if not bundle:
        try:
            import certifi
        except ImportError as exc:
            raise ValueError(
                "Missing certifi CA bundle. Run: python3 -m pip install -e ."
            ) from exc
        bundle = certifi.where()
    try:
        return ssl.create_default_context(cafile=bundle)
    except (OSError, ssl.SSLError) as exc:
        raise ValueError(f"Cannot load CA bundle {bundle}: {exc}") from exc


def build_jobs(config: dict[str, Any]) -> list[Job]:
    jobs: list[Job] = []
    limit = int(config.get("instagram_results_per_source", 10))
    if not 1 <= limit <= 100:
        raise ValueError("instagram_results_per_source must be between 1 and 100")
    for profile in config.get("instagram_profiles", []):
        username = str(profile).strip().lstrip("@").lower()
        if username:
            jobs.append(Job("instagram", username, "apify~instagram-scraper", {
                "directUrls": [f"https://www.instagram.com/{username}/"],
                "resultsType": "posts",
                "resultsLimit": limit,
                "onlyPostsNewerThan": "7 days",
                "skipPinnedPosts": True,
            }))
    for hashtag in config.get("instagram_hashtags", []):
        tag = str(hashtag).strip().lstrip("#").lower()
        if tag:
            jobs.append(Job("instagram", f"#{tag}", "apify~instagram-scraper", {
                "directUrls": [f"https://www.instagram.com/explore/tags/{parse.quote(tag)}/"],
                "resultsType": "posts",
                "resultsLimit": limit,
                "onlyPostsNewerThan": "7 days",
                "skipPinnedPosts": True,
            }))
    threads_limit = int(config.get("threads_results_per_query", 15))
    if not 1 <= threads_limit <= 100:
        raise ValueError("threads_results_per_query must be between 1 and 100")
    for query in config.get("threads_queries", []):
        query = str(query).strip()
        if query:
            jobs.append(Job("threads", query, "themineworks~threads-scraper", {
                "mode": "search",
                "searchQuery": query,
                "maxPosts": threads_limit,
                "resultType": "recent",
                "includeReplies": False,
                "includeReposts": False,
            }))
    return jobs


def run_job(job: Job, token: str, max_charge_usd: float = 0.10) -> list[dict[str, Any]]:
    if not 0 < max_charge_usd <= 5:
        raise ValueError("max_charge_usd must be greater than 0 and at most 5")
    params = parse.urlencode({"maxTotalChargeUsd": max_charge_usd, "format": "json", "clean": "true"})
    url = f"https://api.apify.com/v2/actors/{job.actor}/run-sync-get-dataset-items?{params}"
    payload = json.dumps(job.payload).encode("utf-8")
    req = request.Request(url, payload, {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }, method="POST")
    try:
        with request.urlopen(req, timeout=310, context=_tls_context()) as response:
            data = json.load(response)
    except error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"Apify returned HTTP {exc.code}: {detail}") from exc
    except (error.URLError, TimeoutError) as exc:
        if isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
            raise ValueError(
                "TLS certificate verification failed. Check SSL_CERT_FILE or your network's trusted CA bundle."
            ) from exc
        raise RuntimeError(f"Apify request failed: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError(f"Apify returned an unexpected response for {job.source}")
    return [item for item in data if isinstance(item, dict)]
