from __future__ import annotations

from typing import Any

from .validation import MAX_OFFERS, bounded_list, finite_number
from .ranking import derive_weights

MAX_MONEY = 1_000_000_000.0


def money(value: Any, name: str) -> float:
    return finite_number(value, name, minimum=0.0, maximum=MAX_MONEY)


def price_offer(offer: dict[str, Any], desired_bundle_items: set[str] | None = None) -> dict[str, Any]:
    desired_bundle_items = desired_bundle_items or set()
    base = money(offer.get("base_price", 0), "base_price")
    shipping = money(offer.get("shipping", 0), "shipping")
    tax = money(offer.get("tax", 0), "tax")
    required_costs = money(offer.get("required_costs", 0), "required_costs")
    confirmed_discount = 0.0
    potential_discount = 0.0
    applied: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for index, discount in enumerate(bounded_list(offer.get("discounts", []), "discounts", 100)):
        if not isinstance(discount, dict):
            raise TypeError(f"discounts[{index}] must be an object")
        amount = money(discount.get("amount", 0), f"discounts[{index}].amount")
        status = discount.get("eligibility", "unknown")
        name = str(discount.get("name", "未命名优惠"))[:200]
        lawful = discount.get("lawful", True)
        if lawful is False:
            rejected.append({"name": name, "amount": amount, "reason": "不符合平台或政策规则"})
        elif status is True or status == "confirmed":
            confirmed_discount += amount
            applied.append({"name": name, "amount": amount})
        elif status is False or status == "ineligible":
            rejected.append({"name": name, "amount": amount, "reason": discount.get("reason", "不符合资格")})
        else:
            potential_discount += amount
            pending.append({
                "name": name,
                "amount": amount,
                "required_qualification": str(discount.get("required_qualification", "待核实"))[:500],
            })

    membership_cost = 0.0
    membership_analysis = None
    membership = offer.get("membership")
    if membership is not None:
        if not isinstance(membership, dict):
            raise TypeError("membership must be an object")
        cost = money(membership.get("cost", 0), "membership.cost")
        discount = money(membership.get("purchase_discount", 0), "membership.purchase_discount")
        name = str(membership.get("name", "会员"))[:100]
        if membership.get("already_member") is True:
            confirmed_discount += discount
            applied.append({"name": f"{name}优惠", "amount": discount})
            membership_analysis = "已有会员，优惠已计入"
        elif membership.get("can_open_legally") is True and discount > cost:
            membership_cost = cost
            confirmed_discount += discount
            applied.append({"name": f"新开{name}优惠", "amount": discount})
            membership_analysis = f"开通成本 {cost:.2f}，本次净节省 {discount - cost:.2f}"
        elif membership.get("can_open_legally") is True:
            membership_analysis = "仅为本次购买开通会员不划算，未计入"
        else:
            membership_analysis = "会员资格或开通条件未确认，未计入"

    trade_in = offer.get("trade_in")
    trade_in_analysis = None
    trade_in_strategy = None
    if isinstance(trade_in, dict):
        value = money(trade_in.get("value", 0), "trade_in.value")
        rules_verified = trade_in.get("rules_verified") is True
        if trade_in.get("has_eligible_device") is True and rules_verified:
            confirmed_discount += value
            applied.append({"name": "以旧换新", "amount": value})
            trade_in_analysis = "用户有符合规则的旧设备，已计入"
        else:
            potential_discount += value
            pending.append({"name": "以旧换新", "amount": value, "required_qualification": "需核实用户旧设备及官方规则"})
            trade_in_analysis = "未确认可用旧设备，不计入确定价格"

        # Optional lawful acquisition path: only surface it when official rules are verified
        # and acquiring another eligible device is explicitly permitted. It remains a
        # potential strategy until the user actually owns and can lawfully submit it.
        acquisition_cost = money(trade_in.get("eligible_device_acquisition_cost", 0), "trade_in.eligible_device_acquisition_cost")
        acquisition_allowed = trade_in.get("acquisition_allowed_by_rules") is True
        if not trade_in.get("has_eligible_device") and rules_verified and acquisition_allowed and acquisition_cost > 0:
            net_saving = value - acquisition_cost
            trade_in_strategy = {
                "status": "potential",
                "trade_in_value": round(value, 2),
                "acquisition_cost": round(acquisition_cost, 2),
                "estimated_net_saving": round(net_saving, 2),
                "worth_considering": net_saving > 0,
                "requirements": [
                    "官方规则明确允许该设备参与换新",
                    "设备来源和交易方式合法",
                    "用户本人完成购买与换新并承担验机风险",
                ],
            }

    bundle_value = 0.0
    ignored_bundle: list[str] = []
    for item in bounded_list(offer.get("bundle_items", []), "bundle_items", 50):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "赠品"))
        value = money(item.get("user_value", 0), "bundle.user_value")
        if name in desired_bundle_items:
            bundle_value += value
        else:
            ignored_bundle.append(name)

    realizable = base - confirmed_discount + membership_cost + shipping + tax + required_costs
    potential = realizable - potential_discount
    # Gift/bundle value only affects comparison when the user explicitly wants that item.
    comparison_value_price = max(0.0, realizable - bundle_value)
    return {
        "id": offer.get("id"),
        "candidate_id": offer.get("candidate_id"),
        "platform": offer.get("platform"),
        "merchant_id": offer.get("merchant_id"),
        "base_price": round(base, 2),
        "realizable_price": round(max(0.0, realizable), 2),
        "potential_price_if_pending_verified": round(max(0.0, potential), 2),
        "comparison_value_price": round(comparison_value_price, 2),
        "confirmed_discounts": applied,
        "pending_discounts": pending,
        "ineligible_discounts": rejected,
        "membership_analysis": membership_analysis,
        "trade_in_analysis": trade_in_analysis,
        "trade_in_strategy": trade_in_strategy,
        "desired_bundle_value": round(bundle_value, 2),
        "ignored_bundle_items": ignored_bundle,
        "conditions": bounded_list(offer.get("conditions", []), "offer.conditions", 50),
        "rule": "未知或不合规资格不计入可实现价格",
    }


def rank_offers(payload: dict[str, Any]) -> dict[str, Any]:
    offers = bounded_list(payload.get("offers", []), "offers", MAX_OFFERS)
    desired = {str(x) for x in bounded_list(payload.get("desired_bundle_items", []), "desired_bundle_items", 50)}
    priced = [price_offer(x, desired) for x in offers if isinstance(x, dict)]
    merchant_scores = payload.get("merchant_scores", {}) if isinstance(payload.get("merchant_scores", {}), dict) else {}
    merchant_channels = payload.get("merchant_channels", {}) if isinstance(payload.get("merchant_channels", {}), dict) else {}
    preferences = [p for p in bounded_list(payload.get("preferences", []), "preferences", 80) if isinstance(p, dict)]
    relevant = [p for p in preferences if str(p.get("key")) in {"price", "safety", "official", "after_sales"}]
    weights = derive_weights(relevant) if relevant else {"safety": 0.35, "official": 0.25, "price": 0.25, "after_sales": 0.15}

    if priced:
        prices = [x["comparison_value_price"] for x in priced]
        low, high = min(prices), max(prices)
        spread = max(1.0, high - low)
        official_channels = {"brand_official", "platform_self_operated", "official_flagship"}
        for item in priced:
            merchant_id = str(item.get("merchant_id", ""))
            merchant_score = finite_number(merchant_scores.get(merchant_id, 50), "merchant_score", minimum=0, maximum=100) / 100
            channel = str(merchant_channels.get(merchant_id, "unknown"))
            component = {
                "price": 1.0 - (item["comparison_value_price"] - low) / spread if high > low else 1.0,
                "safety": merchant_score,
                "official": 1.0 if channel in official_channels else (0.65 if channel == "authorized_store" else 0.35),
                "after_sales": merchant_score,
            }
            item["channel_match_score"] = round(sum(component.get(k, 0.5) * v for k, v in weights.items()) * 100, 2)
            item["channel_score_components"] = {k: round(component[k], 4) for k in component}
            item["merchant_evidence_score"] = round(merchant_score * 100, 2)
            item["merchant_channel"] = channel

    priced.sort(key=lambda x: (x.get("channel_match_score", 0), -x["realizable_price"]), reverse=True)
    limit = int(finite_number(payload.get("limit", 5), "limit", minimum=1, maximum=5))
    for index, item in enumerate(priced[:limit], 1):
        item["channel_match_order"] = index
    return {"offers": priced[:limit], "all_count": len(priced), "channel_weights": {k: round(v, 6) for k, v in weights.items()}}
