from __future__ import annotations

from typing import Any, Iterable

from .validation import MAX_CANDIDATES, bounded_list, finite_number

IMPORTANCE_FIXED: dict[str, float | None] = {
    "only": 1.0,
    "exclusive": 1.0,
    "critical": 0.75,
    "must": 0.75,
    "most_important": 0.60,
    "high": 0.40,
    "normal": None,
    "medium": None,
    "low": 0.10,
}


def _compare(actual: Any, op: str, expected: Any) -> bool:
    if op == "eq": return actual == expected
    if op == "neq": return actual != expected
    if op == "lt": return actual < expected
    if op == "lte": return actual <= expected
    if op == "gt": return actual > expected
    if op == "gte": return actual >= expected
    if op == "in": return actual in expected
    if op == "not_in": return actual not in expected
    if op == "contains": return expected in actual
    if op == "truthy": return bool(actual)
    if op == "range":
        low, high = expected
        return low <= actual <= high
    raise ValueError(f"unsupported operator: {op}")


def derive_weights(preferences: list[dict[str, Any]]) -> dict[str, float]:
    if not preferences:
        return {}
    explicit_present = any(p.get("weight") is not None for p in preferences)
    if explicit_present:
        raw = {
            str(p["key"]): finite_number(p.get("weight", 0.0), f"weight.{p.get('key')}", minimum=0.0, maximum=1_000_000.0)
            for p in preferences
        }
        total = sum(raw.values())
        if total <= 0:
            return {str(p["key"]): 1.0 / len(preferences) for p in preferences}
        return {k: v / total for k, v in raw.items()}

    exclusive = [p for p in preferences if p.get("importance") in {"only", "exclusive"}]
    if exclusive:
        selected = str(exclusive[-1]["key"])
        return {str(p["key"]): 1.0 if str(p["key"]) == selected else 0.0 for p in preferences}

    fixed: dict[str, float] = {}
    flexible: list[str] = []
    for preference in preferences:
        key = str(preference["key"])
        value = IMPORTANCE_FIXED.get(str(preference.get("importance", "normal")), None)
        if value is None:
            flexible.append(key)
        else:
            fixed[key] = value
    fixed_total = sum(fixed.values())
    if fixed_total >= 1.0:
        normalized = {k: v / fixed_total for k, v in fixed.items()}
        normalized.update({key: 0.0 for key in flexible})
        return normalized
    remaining = 1.0 - fixed_total
    if flexible:
        share = remaining / len(flexible)
        fixed.update({key: share for key in flexible})
    elif fixed_total > 0:
        fixed = {k: v / fixed_total for k, v in fixed.items()}
    return fixed


def _check_constraints(candidate: dict[str, Any], constraints: Iterable[dict[str, Any]]) -> tuple[list[str], list[str]]:
    attributes = candidate.get("attributes", {})
    if not isinstance(attributes, dict):
        raise TypeError("candidate.attributes must be an object")
    failed: list[str] = []
    unknown: list[str] = []
    for rule in constraints:
        key = str(rule["key"])
        if key not in attributes or attributes[key] is None:
            unknown.append(key)
            continue
        try:
            if not _compare(attributes[key], str(rule.get("op", "eq")), rule.get("value")):
                failed.append(key)
        except (TypeError, ValueError):
            unknown.append(key)
    return failed, unknown


def rank_candidates(payload: dict[str, Any]) -> dict[str, Any]:
    preferences = bounded_list(payload.get("preferences", []), "preferences", 80)
    constraints = bounded_list(payload.get("hard_constraints", []), "hard_constraints", 80)
    rejections = set(str(x) for x in bounded_list(payload.get("rejections", []), "rejections", 200))
    candidates = bounded_list(payload.get("candidates", []), "candidates", MAX_CANDIDATES)
    for label, items in (("preferences", preferences), ("hard_constraints", constraints), ("candidates", candidates)):
        if not all(isinstance(x, dict) for x in items):
            raise TypeError(f"all {label} entries must be objects")

    weights = derive_weights(preferences)
    ranked: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    insufficient: list[dict[str, Any]] = []

    for candidate in candidates:
        cid = str(candidate.get("id", ""))
        labels = {str(x) for x in bounded_list(candidate.get("labels", []), "candidate.labels", 100)}
        rejected_matches = sorted(rejections & labels)
        if rejected_matches:
            excluded.append({"id": cid, "reason": "explicit_rejection", "matches": rejected_matches})
            continue
        failed, unknown_hard = _check_constraints(candidate, constraints)
        if failed:
            excluded.append({"id": cid, "reason": "hard_constraint", "failed_constraints": failed})
            continue

        scores = candidate.get("match_scores", {})
        if not isinstance(scores, dict):
            raise TypeError("candidate.match_scores must be an object")
        weighted_sum = 0.0
        known_weight = 0.0
        contributions: dict[str, float] = {}
        unknown_preferences: list[str] = []
        for key, weight in weights.items():
            raw = scores.get(key)
            if raw is None:
                unknown_preferences.append(key)
                continue
            score = finite_number(raw, f"match_scores.{key}", minimum=0.0, maximum=1.0)
            weighted_sum += score * weight
            known_weight += weight
            contributions[key] = round(score * weight, 6)

        fit = weighted_sum / known_weight if known_weight else finite_number(candidate.get("default_fit", 0.5), "default_fit", minimum=0, maximum=1)
        completeness = finite_number(candidate.get("evidence_completeness", 0.7), "evidence_completeness", minimum=0.0, maximum=1.0)
        credibility = finite_number(candidate.get("evidence_credibility", 0.7), "evidence_credibility", minimum=0.0, maximum=1.0)
        source_quality_multiplier = finite_number(candidate.get("source_quality_multiplier", 1.0), "source_quality_multiplier", minimum=0.0, maximum=1.0)
        adjusted = fit * (0.80 + 0.12 * completeness + 0.08 * credibility) * source_quality_multiplier
        item = {
            "id": cid,
            "name": candidate.get("name"),
            "fit_score": round(fit * 100, 2),
            "evidence_adjusted_score": round(adjusted * 100, 2),
            "weight_contributions": contributions,
            "unknown_preferences": unknown_preferences,
            "unknown_hard_constraints": unknown_hard,
            "strengths": bounded_list(candidate.get("strengths", []), "candidate.strengths", 20),
            "tradeoffs": bounded_list(candidate.get("tradeoffs", []), "candidate.tradeoffs", 20),
            "note": "排序仅表示与当前用户需求的匹配程度，不是商品客观质量排名",
        }
        (insufficient if unknown_hard else ranked).append(item)

    ranked.sort(key=lambda x: (x["evidence_adjusted_score"], x["fit_score"]), reverse=True)
    limit = int(finite_number(payload.get("limit", 5), "limit", minimum=1, maximum=5))
    for index, item in enumerate(ranked[:limit], start=1):
        item["fit_order"] = index

    limiting_constraints: list[dict[str, Any]] = []
    if not ranked and excluded:
        counter: dict[str, int] = {}
        for item in excluded:
            for key in item.get("failed_constraints", []):
                counter[key] = counter.get(key, 0) + 1
        limiting_constraints = [
            {"key": key, "excluded_candidates": count}
            for key, count in sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:5]
        ]

    return {
        "weights": {k: round(v, 6) for k, v in weights.items()},
        "ranked": ranked[:limit],
        "insufficient_evidence": insufficient[:limit],
        "excluded": excluded,
        "limiting_constraints": limiting_constraints,
        "ranking_semantics": "用户需求匹配排序",
    }
