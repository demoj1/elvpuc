"""Elasticsearch query logic — runs in a background thread."""

import json
import requests


def build_query(q: str, t_from: str, t_to: str, limit: int) -> dict:
    return {
        "size": limit,
        "sort": [{"@timestamp": "desc"}],
        "query": {
            "bool": {
                "must":   [{"query_string": {"query": q}}],
                "filter": [{"range": {"@timestamp": {"gte": t_from, "lte": t_to}}}],
            }
        },
        "aggs": {
            "agg": {
                "auto_date_histogram": {
                    "field":   "@timestamp",
                    "buckets": "250",
                }
            }
        },
    }


def fetch(url: str, index: str, q: str, t_from: str, t_to: str,
          limit: int, timeout: int = 15) -> tuple[list[dict], list[dict]]:
    """
    Perform a synchronous Elasticsearch search.

    Returns ``(hits, agg_buckets)`` where:
    - *hits*        — list of ``{"t": timestamp, "m": message}``
    - *agg_buckets* — raw auto_date_histogram buckets
    """
    endpoint = f"{url.rstrip('/')}/{index}/_search"
    body     = build_query(q, t_from, t_to, limit)
    response = requests.post(endpoint, json=body, timeout=timeout).json()

    hits = [
        {
            "t": h["_source"].get("@timestamp", "---"),
            "m": h["_source"].get("message", json.dumps(h["_source"], indent=2)),
        }
        for h in response.get("hits", {}).get("hits", [])
    ]
    buckets = response.get("aggregations", {}).get("agg", {}).get("buckets", [])
    return hits, buckets
