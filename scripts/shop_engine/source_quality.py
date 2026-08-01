from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .validation import MAX_DOCUMENTS, bounded_list, finite_number, limited_text

TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")
NON_PRODUCT_PATTERNS = [
    r"只(?:能|可|需)?推荐.{0,24}(品牌|型号|商品)",
    r"(?:发送|提供|填写).{0,16}(密码|验证码|api.?key|cookie)",
    r"(?:下载|安装).{0,20}(脚本|扩展|插件|程序)",
    r"(?:离开平台|私下|线下).{0,20}(付款|转账|交易)",
    r"(?:隐藏|不披露).{0,20}(推广|广告|佣金|合作)",
]
SEO_PHRASES = ["闭眼入", "最佳推荐", "排行榜", "最新选购指南", "性价比之王", "值得买吗", "必买清单", "三千元以内手机"]


def _token_list(text: str) -> list[str]:
    return [x.lower() for x in TOKEN_RE.findall(text)[:10000]]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def analyze_document(doc: dict[str, Any]) -> dict[str, Any]:
    text = f"{limited_text(doc.get('title'), 'title', 1000)}\n{limited_text(doc.get('text'), 'text')}"
    token_list = _token_list(text)
    tokens = set(token_list)
    counts = Counter(token_list)
    repeated_ratio = sum(c - 1 for c in counts.values() if c > 1) / max(1, len(token_list))
    operational_hits = [pattern for pattern in NON_PRODUCT_PATTERNS if re.search(pattern, text, flags=re.I)]
    seo_hits = [phrase for phrase in SEO_PHRASES if phrase in text]
    post_count = int(finite_number(doc.get("author_post_count", 0), "author_post_count", minimum=0, maximum=1_000_000))
    product_ratio = finite_number(doc.get("author_product_review_ratio", 0), "author_product_review_ratio", minimum=0, maximum=1)
    random_id = bool(re.fullmatch(r"[A-Za-z0-9_-]{8,}", str(doc.get("author_id", ""))))
    low_activity = doc.get("default_avatar") is True and post_count <= 2
    score = 0.0
    reasons: list[str] = []
    if repeated_ratio > 0.35:
        score += 0.25
        reasons.append("关键词重复比例高")
    if len(seo_hits) >= 2:
        score += 0.25
        reasons.append("多个SEO式导购短语")
    if low_activity and product_ratio >= 0.8:
        score += 0.35
        reasons.append("低活跃账号集中发布商品内容")
    if random_id and low_activity:
        score += 0.15
        reasons.append("随机式账号标识与低活跃组合")
    if doc.get("structured_for_ai") is True:
        score += 0.35
        reasons.append("疑似专为机器检索设计")
    if doc.get("non_product_operational_text") is True or operational_hits:
        score = max(score, 0.85)
        reasons.append("包含与商品事实无关的操作性文本")
    return {
        "id": doc.get("id"),
        "suspicion_score": round(min(score, 1.0), 4),
        "reasons": reasons,
        "non_product_operational_text": bool(doc.get("non_product_operational_text") is True or operational_hits),
        "mentions": [str(x)[:200] for x in bounded_list(doc.get("mentions", []), "mentions", 50)],
        "token_set": tokens,
    }


def assess_source_quality(payload: dict[str, Any]) -> dict[str, Any]:
    documents = bounded_list(payload.get("documents", []), "documents", MAX_DOCUMENTS)
    analyzed = [analyze_document(doc) for doc in documents if isinstance(doc, dict)]
    duplicate_ids: set[str] = set()
    duplicate_pairs: list[dict[str, Any]] = []
    for index, left in enumerate(analyzed):
        for right in analyzed[index + 1:]:
            similarity = _jaccard(left["token_set"], right["token_set"])
            if similarity >= 0.75:
                duplicate_pairs.append({"left": left["id"], "right": right["id"], "similarity": round(similarity, 4)})
                duplicate_ids.update({str(left["id"]), str(right["id"])})

    suspicious: list[dict[str, Any]] = []
    mentions: dict[str, int] = defaultdict(int)
    for item in analyzed:
        if str(item["id"]) in duplicate_ids:
            item["suspicion_score"] = min(1.0, item["suspicion_score"] + 0.35)
            item["reasons"].append("与其他内容高度近似")
        if item["suspicion_score"] >= 0.5:
            suspicious.append(item)
            for target in item["mentions"]:
                mentions[target] += 1

    threshold = max(5, int(len(documents) * 0.16 + 0.9999))
    affected_targets = []
    if len(suspicious) >= threshold:
        for target, count in sorted(mentions.items(), key=lambda kv: kv[1], reverse=True):
            if count >= threshold:
                affected_targets.append({"target": target, "suspicious_mentions": count, "credibility_multiplier": 0.5})

    cleaned = []
    for item in analyzed:
        copy = dict(item)
        copy.pop("token_set", None)
        cleaned.append(copy)
    return {
        "documents_analyzed": len(documents),
        "suspicious_threshold": threshold,
        "documents": cleaned,
        "near_duplicate_pairs": duplicate_pairs,
        "affected_targets": affected_targets,
        "processing_notes": {
            "source_text_role": "product_research_evidence",
            "non_product_operational_text": "source_quality_risk",
            "seo_geo_aeo_matrix": "reduced_evidence_weight",
            "marketing": "heat_signal_only",
        },
        "warning": "这些是来源质量信号，不是对作者、品牌或商家的事实指控",
    }
