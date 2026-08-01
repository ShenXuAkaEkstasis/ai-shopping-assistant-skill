from __future__ import annotations

from typing import Any

from .validation import bounded_list


def choose_questions(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get("state", {}) if isinstance(payload.get("state", {}), dict) else {}
    task = payload.get("task", {}) if isinstance(payload.get("task", {}), dict) else {}
    questions: list[dict[str, Any]] = []

    def add(key: str, question: str, impact: str, options: list[str] | None = None) -> None:
        if any(q["key"] == key for q in questions):
            return
        item: dict[str, Any] = {"key": key, "question": question, "impact": impact}
        if options: item["options"] = options
        questions.append(item)

    if not state.get("category") and not task.get("specific_product"):
        add("use_case", "主要想解决什么使用需求？", "决定品类和候选范围")
    if task.get("gift") is True and not state.get("recipient"):
        add("recipient", "礼物主要送给谁？", "影响品类、风格与使用门槛")
    if task.get("price_sensitive") is True and not (state.get("currency") or state.get("resolved_location", {}).get("currency")):
        add("currency", "按哪个地区和币种比较？", "决定平台、税费和真实价格")
    if task.get("specific_product") and not state.get("condition"):
        add("condition", "默认只看全新正规渠道，可以吗？", "决定是否扩大到官翻或二手", ["全新正规渠道", "可接受官翻", "可接受二手"])
    if task.get("needs_account_price") is True and payload.get("browser_authorization") is None:
        add("browser_authorization", "是否授权读取登录后可见的价格和优惠？", "决定能否核实会员价、账户券和地区资格", ["授权", "不授权，使用公开信息"])
    if task.get("unknown_discount_qualification") is True:
        add("qualification", "需要核实哪项优惠资格？", "未知资格不能计入确定到手价")

    hard_constraints = bounded_list(state.get("hard_constraints", []), "hard_constraints", 80)
    if task.get("no_candidates") is True and hard_constraints:
        add("relax_constraint", "当前条件没有候选，愿意放宽哪一项？", "决定下一轮可进入的产品线")

    priority = {"决定品类和候选范围": 100, "决定平台、税费和真实价格": 95, "决定能否核实会员价、账户券和地区资格": 90,
                "决定下一轮可进入的产品线": 85, "影响品类、风格与使用门槛": 80, "决定是否扩大到官翻或二手": 75,
                "未知资格不能计入确定到手价": 70}
    questions.sort(key=lambda q: priority.get(q["impact"], 0), reverse=True)
    return {"questions": questions[:3], "ask_only_if_material": True, "count": min(3, len(questions))}
