from __future__ import annotations

from collections import defaultdict
from typing import Any

from .validation import MAX_REVIEWS, bounded_list, finite_number

GROUP_WEIGHTS = {"verified_purchase": 0.5, "community": 0.3, "objective": 0.2}


def recency_multiplier(age_days: int) -> float:
    if age_days < 0 or age_days > 36500:
        raise ValueError("age_days must be between 0 and 36500")
    if age_days <= 30: return 3.0
    if age_days <= 90: return 2.0
    if age_days <= 180: return 1.0
    return 0.5


def review_multiplier(review: dict[str, Any]) -> tuple[float, dict[str, float]]:
    sentiment = finite_number(review.get("sentiment", 0), "review.sentiment", minimum=-1, maximum=1)
    age_days = int(finite_number(review.get("age_days", 9999), "review.age_days", minimum=0, maximum=36500))
    parts: dict[str, float] = {"recency": recency_multiplier(age_days)}

    # Media and dispute/follow-up are one combined evidence dimension.
    # This avoids double-amplifying a negative video dispute (5x, not 5x * 1.5).
    if review.get("negative_follow_up"):
        parts["media_interaction"] = 5.0
    elif sentiment < 0 and review.get("merchant_dispute") and review.get("has_video"):
        parts["media_interaction"] = 5.0
    elif sentiment < 0 and review.get("merchant_dispute"):
        parts["media_interaction"] = 3.0
    elif review.get("has_video"):
        parts["media_interaction"] = 1.5
    elif review.get("has_image"):
        parts["media_interaction"] = 1.2
    else:
        parts["media_interaction"] = 1.0

    ratio = review.get("author_product_review_ratio")
    if ratio is not None:
        ratio = finite_number(ratio, "author_product_review_ratio", minimum=0, maximum=1)
    author = 1.0
    if ratio is not None and ratio >= 0.8:
        author *= 0.05
    elif ratio is not None and ratio <= 0.2:
        author *= 1.05
    if review.get("is_kol") or review.get("is_commercial_reviewer"):
        author *= 0.8
    parts["author"] = author

    if review.get("seo_geo_aeo_template") or review.get("non_product_operational_text"):
        parts["content"] = 0.0
    else:
        content = 1.0
        if review.get("obvious_brand_copy"): content *= 0.5
        if review.get("specific_personal_detail"): content *= 1.5
        text_length = int(finite_number(review.get("text_length", 0), "text_length", minimum=0, maximum=100000))
        if text_length > 80 and not review.get("specific_personal_detail"): content *= 0.5
        if review.get("duplicate_positive") and sentiment > 0: content *= 0.8
        parts["content"] = content

    independence = finite_number(review.get("source_independence", 1.0), "source_independence", minimum=0, maximum=1)
    parts["independence"] = independence
    total = 1.0
    for multiplier in parts.values():
        total *= multiplier
    return total, parts


def score_reviews(payload: dict[str, Any]) -> dict[str, Any]:
    reviews = bounded_list(payload.get("reviews", []), "reviews", MAX_REVIEWS)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ignored: list[dict[str, Any]] = []
    heat_signals: list[dict[str, Any]] = []

    for review in reviews:
        if not isinstance(review, dict):
            raise TypeError("all reviews must be objects")
        group = str(review.get("source_group", "community"))
        weight, parts = review_multiplier(review)
        item = {
            "id": review.get("id"),
            "sentiment": finite_number(review.get("sentiment", 0), "sentiment", minimum=-1, maximum=1),
            "weight": round(weight, 6),
            "multipliers": parts,
            "topics": [str(x)[:200] for x in bounded_list(review.get("topics", []), "topics", 50)],
            "source_group": group,
            "sponsored": bool(review.get("sponsored") or review.get("is_kol")),
        }
        if item["sponsored"]:
            heat_signals.append({"id": item["id"], "topics": item["topics"]})
        if weight <= 0:
            ignored.append({**item, "reason": "非商品操作性文本或SEO/GEO/AEO模板"})
        else:
            groups[group].append(item)

    overall = 0.0
    available_weight = 0.0
    group_results: dict[str, Any] = {}
    topic_scores: dict[str, float] = defaultdict(float)
    negative_topics: dict[str, float] = defaultdict(float)

    for group, configured_weight in GROUP_WEIGHTS.items():
        items = groups.get(group, [])
        denominator = sum(item["weight"] for item in items)
        if denominator <= 0:
            group_results[group] = {"status": "no_evidence", "count": 0}
            continue
        sentiment = sum(item["sentiment"] * item["weight"] for item in items) / denominator
        group_results[group] = {
            "status": "available",
            "count": len(items),
            "weighted_sentiment": round(sentiment, 4),
            "evidence_weight": round(denominator, 4),
        }
        overall += sentiment * configured_weight
        available_weight += configured_weight
        for item in items:
            for topic in item["topics"]:
                directional = item["weight"] * (1 if item["sentiment"] >= 0 else -1)
                topic_scores[topic] += directional
                if item["sentiment"] < 0:
                    negative_topics[topic] += item["weight"]

    normalized = overall / available_weight if available_weight else 0.0
    top_topics = sorted(topic_scores.items(), key=lambda kv: abs(kv[1]), reverse=True)[:12]
    top_negative = sorted(negative_topics.items(), key=lambda kv: kv[1], reverse=True)[:8]
    return {
        "overall_evidence_sentiment": round(normalized, 4),
        "groups": group_results,
        "top_weighted_topics": [{"topic": k, "directional_weight": round(v, 4)} for k, v in top_topics],
        "priority_negative_topics": [{"topic": k, "weight": round(v, 4)} for k, v in top_negative],
        "marketing_heat_signals": heat_signals[:20],
        "ignored": ignored,
        "warnings": [
            "分数用于整理证据，不构成真假、欺诈或购买保证",
            "营销内容只用于热度和品牌主张，不直接提高购买匹配度",
        ],
    }
