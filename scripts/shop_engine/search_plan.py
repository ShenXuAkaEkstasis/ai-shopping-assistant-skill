from __future__ import annotations

from typing import Any

from .validation import bounded_list

CATEGORY_PLATFORMS = {
    "CN": {
        "electronics": ["品牌官网", "京东", "天猫"],
        "3c": ["品牌官网", "京东", "天猫"],
        "fashion": ["淘宝", "天猫", "京东"],
        "clothing": ["淘宝", "天猫", "京东"],
        "daily_goods": ["京东", "拼多多", "淘宝"],
        "novelty": ["抖音电商", "淘宝", "拼多多"],
        "secondhand": ["闲鱼", "转转"],
        "default": ["品牌官网", "京东", "天猫", "淘宝"],
    },
    "US": {
        "electronics": ["品牌官网", "Amazon", "Best Buy", "Walmart"],
        "fashion": ["品牌官网", "Amazon", "Nordstrom", "Macy's"],
        "secondhand": ["eBay", "Swappa", "Facebook Marketplace"],
        "default": ["品牌官网", "Amazon", "Walmart", "eBay"],
    },
    "TH": {
        "default": ["品牌官网", "Shopee", "Lazada"],
        "electronics": ["品牌官网", "Lazada", "Shopee"],
    },
}


def _country_code(location: dict[str, Any]) -> str:
    raw = str(location.get("country", location.get("label", ""))).lower()
    if any(x in raw for x in ("china", "中国", "cn")): return "CN"
    if any(x in raw for x in ("united states", "usa", "美国", "us")): return "US"
    if any(x in raw for x in ("thailand", "泰国", "th")): return "TH"
    return "CN" if str(location.get("currency", "")).upper() == "CNY" else "US"


def create_search_plan(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get("state", {}) if isinstance(payload.get("state", {}), dict) else {}
    category = str(state.get("category", "default")).lower()
    location = state.get("resolved_location", {}) if isinstance(state.get("resolved_location", {}), dict) else {}
    country = _country_code(location)
    region_map = CATEGORY_PLATFORMS.get(country, CATEGORY_PLATFORMS["US"])
    platforms = region_map.get(category, region_map.get("default", []))
    platform_limit = state.get("platform_limit")
    if platform_limit:
        allowed = {str(x).lower() for x in (platform_limit if isinstance(platform_limit, list) else [platform_limit])}
        platforms = [p for p in platforms if p.lower() in allowed] or list(allowed)

    needs = payload.get("needs", {}) if isinstance(payload.get("needs", {}), dict) else {}
    login_fields = [
        key for key in ("member_price", "account_coupon", "regional_subsidy", "site_search", "expanded_reviews", "stock_by_location")
        if needs.get(key) is True
    ]
    authorization = bool(login_fields)
    depth = str(state.get("search_depth", "normal"))
    page_budget = {"normal": [30, 50], "deep": [50, 100], "quick": [10, 20]}.get(depth, [30, 50])
    user_rejected_auth = payload.get("browser_authorization") is False

    return {
        "country_profile": country,
        "platform_priority": platforms,
        "public_research_first": True,
        "browser_authorization_required": authorization and not user_rejected_auth,
        "authorization_reason": login_fields,
        "fallback_when_denied": "使用官网、公开页面、公开讨论和用户截图；标注覆盖不足" if user_rejected_auth else None,
        "research_page_budget": {"min": page_budget[0], "max": page_budget[1]},
        "stop_after_report": True,
        "safety": [
            "用户在官方页面亲自登录、输入验证码并接受协议",
            "只读取当前任务需要的可见信息",
            "停止在提交订单和付款之前",
        ],
        "provided_sources": bounded_list(payload.get("provided_sources", []), "provided_sources", 100),
    }
