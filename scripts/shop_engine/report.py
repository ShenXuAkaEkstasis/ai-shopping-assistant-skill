from __future__ import annotations

from typing import Any


def build_report(result: dict[str, Any]) -> dict[str, Any]:
    ranking = result.get("ranking", {})
    pricing = result.get("pricing", {})
    merchants = result.get("merchants", {})
    reviews = result.get("reviews", {})
    source_quality = result.get("source_quality", {})

    candidate_rows = []
    price_by_candidate = {str(x.get("candidate_id")): x for x in pricing.get("offers", [])}
    merchant_by_id = {str(x.get("id")): x for x in merchants.get("merchants", [])}
    for candidate in ranking.get("ranked", [])[:5]:
        price = price_by_candidate.get(str(candidate.get("id")))
        merchant = merchant_by_id.get(str(price.get("merchant_id"))) if price else None
        candidate_rows.append({
            "match_order": candidate.get("fit_order"),
            "candidate": candidate.get("name") or candidate.get("id"),
            "fit_score": candidate.get("evidence_adjusted_score"),
            "strengths": candidate.get("strengths", []),
            "tradeoffs": candidate.get("tradeoffs", []),
            "realizable_price": price.get("realizable_price") if price else None,
            "pending_price": price.get("potential_price_if_pending_verified") if price else None,
            "channel": price.get("platform") if price else None,
            "merchant_evidence": merchant.get("evidence_level") if merchant else None,
            "unknown": candidate.get("unknown_preferences", []) + candidate.get("unknown_hard_constraints", []),
        })

    warnings = []
    for merchant in merchants.get("merchants", []):
        warnings.extend(merchant.get("warnings", []))
    if source_quality.get("affected_targets"):
        warnings.append("发现疑似SEO/GEO/AEO内容矩阵，相关目标已降低可信度")
    warnings.extend(reviews.get("warnings", []))

    return {
        "title": "购物研究结果",
        "ranking_semantics": "按当前用户主观需求匹配度排序，不是产品客观质量榜",
        "candidate_rows": candidate_rows,
        "priority_review_topics": reviews.get("top_weighted_topics", [])[:8],
        "priority_negative_topics": reviews.get("priority_negative_topics", [])[:5],
        "warnings": list(dict.fromkeys(warnings))[:20],
        "pending_questions": result.get("state", {}).get("pending", []),
        "next_step": "等待用户补充、修改条件或指定需要继续核实的候选",
        "purchase_boundary": "不提交订单、不付款、不索取密码或验证码",
    }
