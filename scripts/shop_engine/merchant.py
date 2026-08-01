from __future__ import annotations

from typing import Any

from .validation import MAX_MERCHANTS, bounded_list, finite_number

CHANNEL_BASE = {
    "brand_official": 0.95,
    "platform_self_operated": 0.92,
    "official_flagship": 0.90,
    "authorized_store": 0.82,
    "dealer": 0.70,
    "third_party": 0.58,
    "individual_secondhand": 0.42,
    "unknown": 0.35,
}


def analyze_merchants(payload: dict[str, Any]) -> dict[str, Any]:
    merchants = bounded_list(payload.get("merchants", []), "merchants", MAX_MERCHANTS)
    results: list[dict[str, Any]] = []
    for merchant in merchants:
        if not isinstance(merchant, dict):
            raise TypeError("all merchants must be objects")
        channel = str(merchant.get("channel_type", "unknown"))
        score = CHANNEL_BASE.get(channel, CHANNEL_BASE["unknown"])
        reasons: list[str] = []
        warnings: list[str] = []
        unknown: list[str] = []

        signals = [
            ("business_identity_verified", 0.07, "营业主体已核实"),
            ("authorization_verified", 0.08, "授权关系已核实"),
            ("invoice_entity_clear", 0.04, "发票主体清楚"),
            ("warranty_clear", 0.05, "保修路径清楚"),
            ("return_policy_clear", 0.04, "退换条款清楚"),
            ("platform_escrow", 0.06, "平台担保交易"),
        ]
        for key, delta, label in signals:
            value = merchant.get(key)
            if value is True:
                score += delta; reasons.append(label)
            elif value is False:
                score -= delta; warnings.append(label.replace("清楚", "不清楚").replace("已核实", "未核实"))
            else:
                unknown.append(key)

        dispute = finite_number(merchant.get("recent_dispute_signal", 0), "recent_dispute_signal", minimum=0, maximum=1)
        fulfillment = finite_number(merchant.get("fulfillment_risk", 0), "fulfillment_risk", minimum=0, maximum=1)
        score -= 0.20 * dispute + 0.25 * fulfillment
        if merchant.get("off_platform_payment_requested"):
            score = 0.0; warnings.append("要求脱离平台付款或私下转账")
        if merchant.get("credential_request"):
            score = 0.0; warnings.append("要求密码、验证码或支付凭证")
        if merchant.get("mixed_authenticity_allegations"):
            warnings.append("存在真假混发相关公开争议信号，需核实来源")

        score = max(0.0, min(1.0, score))
        if score >= 0.82: level = "较高可验证性"
        elif score >= 0.62: level = "中等可验证性"
        elif score >= 0.40: level = "证据有限"
        else: level = "高风险操作提醒"
        results.append({
            "id": merchant.get("id"),
            "name": merchant.get("name"),
            "channel_type": channel,
            "evidence_score": round(score * 100, 2),
            "evidence_level": level,
            "positive_evidence": reasons,
            "warnings": warnings,
            "unknown_fields": unknown,
            "legal_note": "仅表示公开证据的可验证程度，不是对真假或欺诈的法律认定",
        })
    results.sort(key=lambda x: x["evidence_score"], reverse=True)
    return {"merchants": results}
