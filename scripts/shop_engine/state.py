from __future__ import annotations

from copy import deepcopy
from typing import Any

from .validation import bounded_list, ensure_object

SCOPE_AFFECTING_KEYS = {
    "category", "budget", "currency", "condition", "used_allowed", "refurbished_allowed",
    "region", "country", "city", "product_line", "platform_limit", "hard_constraints",
}
TASK_SCOPED_KEYS = {
    "recipient", "gift", "budget", "currency", "use_case", "deadline", "platform_limit",
    "invoice", "delivery", "installation", "packaging", "condition", "used_allowed",
    "refurbished_allowed", "hard_constraints", "preferences", "pending_questions",
}


def _merge_unique(existing: list[Any], additions: list[Any], key: str | None = None) -> list[Any]:
    result = list(existing)
    if key:
        index = {str(item.get(key)): i for i, item in enumerate(result) if isinstance(item, dict) and key in item}
        for item in additions:
            if isinstance(item, dict) and key in item and str(item[key]) in index:
                result[index[str(item[key])]] = item
            else:
                result.append(item)
    else:
        for item in additions:
            if item not in result:
                result.append(item)
    return result


def resolve_location(location: dict[str, Any] | None) -> dict[str, Any]:
    location = ensure_object(location or {}, "location")
    candidates = [
        ("user_declared", location.get("user_declared")),
        ("conversation", location.get("conversation")),
        ("ip", location.get("ip")),
        ("locale", location.get("locale")),
    ]
    for source, value in candidates:
        if isinstance(value, dict) and any(value.get(k) for k in ("country", "region", "city", "currency")):
            return {"source": source, **value}
        if isinstance(value, str) and value.strip():
            return {"source": source, "label": value.strip()}
    return {"source": "unknown"}


def apply_patch(state: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    current = deepcopy(ensure_object(state or {}, "state"))
    patch = ensure_object(patch or {}, "patch")
    before_category = current.get("category")
    changes: list[str] = []
    scope_change = False

    for key, value in ensure_object(patch.get("set", {}), "patch.set").items():
        if current.get(key) != value:
            current[key] = value
            changes.append(key)
            scope_change = scope_change or key in SCOPE_AFFECTING_KEYS

    for key in bounded_list(patch.get("unset", []), "patch.unset", 100):
        key = str(key)
        if key in current:
            current.pop(key, None)
            changes.append(key)
            scope_change = scope_change or key in SCOPE_AFFECTING_KEYS

    list_ops = [
        ("add_hard_constraints", "hard_constraints", "key"),
        ("add_preferences", "preferences", "key"),
        ("add_rejections", "rejections", None),
        ("add_confirmed_eligibility", "confirmed_eligibility", "name"),
        ("add_pending", "pending", "name"),
    ]
    for op, target, unique_key in list_ops:
        additions = bounded_list(patch.get(op, []), f"patch.{op}", 100)
        if additions:
            current[target] = _merge_unique(bounded_list(current.get(target, []), target, 500), additions, unique_key)
            changes.append(target)
            scope_change = scope_change or target == "hard_constraints"

    remove_keys = {
        "remove_hard_constraints": "hard_constraints",
        "remove_preferences": "preferences",
        "remove_pending": "pending",
    }
    for op, target in remove_keys.items():
        keys = {str(x) for x in bounded_list(patch.get(op, []), f"patch.{op}", 100)}
        if keys:
            old = bounded_list(current.get(target, []), target, 500)
            current[target] = [item for item in old if not (isinstance(item, dict) and str(item.get("key", item.get("name"))) in keys)]
            changes.append(target)
            scope_change = scope_change or target == "hard_constraints"

    after_category = current.get("category")
    category_changed = before_category is not None and after_category is not None and before_category != after_category
    if category_changed:
        persistent_preferences = [
            p for p in bounded_list(current.get("preferences", []), "preferences", 500)
            if isinstance(p, dict) and p.get("scope") == "persistent"
        ]
        persistent_rejections = bounded_list(current.get("rejections", []), "rejections", 500)
        preserved = {k: v for k, v in current.items() if k not in TASK_SCOPED_KEYS}
        preserved["category"] = after_category
        preserved["preferences"] = persistent_preferences
        preserved["rejections"] = persistent_rejections
        current = preserved
        scope_change = True
        changes.append("category_context_reset")

    current["resolved_location"] = resolve_location(current.get("location"))
    current["stage"] = current.get("stage", "discovery")
    current["search_depth"] = current.get("search_depth", "normal")
    current["revision"] = int(current.get("revision", 0)) + 1

    return {
        "state": current,
        "changes": sorted(set(changes)),
        "search_action": "full_refresh" if scope_change else ("incremental_refresh" if changes else "reuse_current"),
        "reason": "范围条件变化会引入或排除新的产品线" if scope_change else "仅补充或更新现有筛选条件",
    }
