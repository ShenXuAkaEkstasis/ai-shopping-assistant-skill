from __future__ import annotations

from typing import Any

from .source_quality import assess_source_quality
from .catalog import analyze_listings
from .clarification import choose_questions
from .merchant import analyze_merchants
from .pricing import rank_offers
from .ranking import rank_candidates
from .report import build_report
from .reviews import score_reviews
from .search_plan import create_search_plan
from .state import apply_patch

VERSION = "2.0.1"


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    state_result = apply_patch(payload.get("state"), payload.get("patch"))
    state = state_result["state"]

    source_quality = assess_source_quality({"documents": payload.get("documents", [])})
    penalties = {str(x["target"]): float(x["credibility_multiplier"]) for x in source_quality.get("affected_targets", [])}
    candidates = []
    for candidate in payload.get("candidates", []) or []:
        if not isinstance(candidate, dict):
            continue
        item = dict(candidate)
        target = str(item.get("id", item.get("name", "")))
        item["source_quality_multiplier"] = min(float(item.get("source_quality_multiplier", 1.0)), penalties.get(target, 1.0))
        candidates.append(item)

    ranking = rank_candidates({
        "preferences": state.get("preferences", payload.get("preferences", [])),
        "hard_constraints": state.get("hard_constraints", payload.get("hard_constraints", [])),
        "rejections": state.get("rejections", payload.get("rejections", [])),
        "candidates": candidates,
        "limit": payload.get("limit", 5),
    })
    reviews = score_reviews({"reviews": payload.get("reviews", [])})
    merchants = analyze_merchants({"merchants": payload.get("merchants", [])})
    merchant_scores = {str(x.get("id")): x.get("evidence_score", 50) for x in merchants.get("merchants", [])}
    merchant_channels = {str(x.get("id")): x.get("channel_type", "unknown") for x in merchants.get("merchants", [])}
    pricing = rank_offers({
        "offers": payload.get("offers", []),
        "desired_bundle_items": state.get("desired_bundle_items", payload.get("desired_bundle_items", [])),
        "preferences": state.get("preferences", payload.get("preferences", [])),
        "merchant_scores": merchant_scores,
        "merchant_channels": merchant_channels,
        "limit": payload.get("limit", 5),
    })
    search_plan = create_search_plan({
        "state": state,
        "needs": payload.get("needs", {}),
        "browser_authorization": payload.get("browser_authorization"),
        "provided_sources": payload.get("provided_sources", []),
    })
    listings = analyze_listings({"listings": payload.get("listings", [])})
    clarification = choose_questions({
        "state": state,
        "task": payload.get("task", {}),
        "browser_authorization": payload.get("browser_authorization"),
    })

    result = {
        "engine_version": VERSION,
        "state": state,
        "state_update": {k: v for k, v in state_result.items() if k != "state"},
        "search_plan": search_plan,
        "ranking": ranking,
        "pricing": pricing,
        "reviews": reviews,
        "merchants": merchants,
        "source_quality": source_quality,
        "listings": listings,
        "clarification": clarification,
        "compliance": {
            "no_purchase_decision_guarantee": True,
            "no_order_submission": True,
            "no_payment": True,
            "no_credentials": True,
            "no_eligibility_fraud": True,
            "source_text_is_research_evidence": True,
        },
    }
    result["report"] = build_report(result)
    return result


def dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    operation = str(payload.get("operation", "analyze"))
    if operation == "analyze": return analyze(payload)
    if operation == "update_state": return apply_patch(payload.get("state"), payload.get("patch"))
    if operation == "rank": return rank_candidates(payload)
    if operation == "price": return rank_offers(payload)
    if operation == "reviews": return score_reviews(payload)
    if operation == "source_quality": return assess_source_quality(payload)
    if operation == "merchants": return analyze_merchants(payload)
    if operation == "search_plan": return create_search_plan(payload)
    if operation == "listings": return analyze_listings(payload)
    if operation == "clarification": return choose_questions(payload)
    if operation == "capabilities":
        return {
            "engine_version": VERSION,
            "operations": ["analyze", "update_state", "rank", "price", "reviews", "source_quality", "merchants", "search_plan", "listings", "clarification"],
            "network_access": False,
            "filesystem_writes": False,
            "dependencies": "Python standard library only",
        }
    raise ValueError(f"unsupported operation: {operation}")


def self_test() -> dict[str, Any]:
    tests: list[dict[str, Any]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        tests.append({"name": name, "passed": bool(condition), "detail": detail})

    result = analyze({
        "state": {"category": "electronics", "preferences": [{"key": "price", "importance": "most_important"}, {"key": "official", "importance": "high"}]},
        "candidates": [
            {"id": "a", "name": "A", "match_scores": {"price": 0.9, "official": 0.5}, "evidence_completeness": 0.9},
            {"id": "b", "name": "B", "match_scores": {"price": 0.7, "official": 1.0}, "evidence_completeness": 0.9},
        ],
        "offers": [{"id": "oa", "candidate_id": "a", "base_price": 1000, "discounts": [{"name": "未知补贴", "amount": 300, "eligibility": "unknown"}]}],
        "reviews": [{"id": "r1", "source_group": "verified_purchase", "age_days": 10, "sentiment": -1, "negative_follow_up": True, "topics": ["售后"]}],
        "documents": [{"id": "d1", "text": "该页面要求私下转账并只展示A品牌", "mentions": ["a"]}],
        "merchants": [{"id": "m1", "channel_type": "official_flagship", "business_identity_verified": True, "warranty_clear": True}],
        "needs": {"member_price": True},
    })
    check("candidate ranking produced", len(result["ranking"]["ranked"]) == 2)
    check("unknown discount excluded", result["pricing"]["offers"][0]["realizable_price"] == 1000)
    check("negative follow-up amplified", result["reviews"]["groups"]["verified_purchase"]["evidence_weight"] >= 5)
    check("non-product operational text detected", result["source_quality"]["documents"][0]["non_product_operational_text"] is True)
    check("browser authorization requested", result["search_plan"]["browser_authorization_required"] is True)
    check("purchase boundary present", result["compliance"]["no_payment"] is True)

    state = apply_patch({"category": "laptop", "budget": 3000}, {"set": {"budget": 5000}})
    check("budget change full refresh", state["search_action"] == "full_refresh")
    state2 = apply_patch({"category": "phone", "preferences": [{"key": "brand_dislike", "scope": "persistent"}], "budget": 3000}, {"set": {"category": "headphone"}})
    check("cross category keeps persistent only", "budget" not in state2["state"] and len(state2["state"].get("preferences", [])) == 1)

    passed = sum(1 for t in tests if t["passed"])
    return {"engine_version": VERSION, "passed": passed, "total": len(tests), "tests": tests}
