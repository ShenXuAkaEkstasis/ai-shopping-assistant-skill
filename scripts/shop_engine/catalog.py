from __future__ import annotations

from typing import Any

from .validation import bounded_list, finite_number


def analyze_listings(payload: dict[str, Any]) -> dict[str, Any]:
    listings = bounded_list(payload.get("listings", []), "listings", 300)
    results: list[dict[str, Any]] = []
    for listing in listings:
        if not isinstance(listing, dict):
            raise TypeError("all listings must be objects")
        warnings: list[str] = []
        current_sku = listing.get("current_sku")
        variants = bounded_list(listing.get("variants", []), "listing.variants", 200)
        variant_ids = {str(v.get("sku")) for v in variants if isinstance(v, dict) and v.get("sku") is not None}
        link_sales = finite_number(listing.get("link_total_sales", 0), "link_total_sales", minimum=0, maximum=1_000_000_000)
        sku_sales = listing.get("current_sku_sales")
        sku_reviews = listing.get("current_sku_reviews")
        if len(variant_ids) > 1:
            warnings.append("链接包含多个规格或型号，链接总销量不能直接视为当前SKU销量")
        if listing.get("history_reused") is True or listing.get("title_or_model_changed") is True:
            warnings.append("链接可能继承历史商品、旧型号或更换后的累计数据")
        if sku_sales is None and link_sales > 0:
            warnings.append("未取得当前SKU独立销量，销量证据不足")
        if sku_reviews is None and listing.get("link_total_reviews") is not None:
            warnings.append("评论可能跨规格聚合，需按当前SKU和时间范围筛选")
        results.append({
            "id": listing.get("id"),
            "current_sku": current_sku,
            "variant_count": len(variant_ids),
            "current_sku_sales": sku_sales,
            "current_sku_reviews": sku_reviews,
            "link_total_sales": link_sales,
            "safe_to_use_link_sales_as_sku_sales": len(variant_ids) <= 1 and not warnings and sku_sales is not None,
            "warnings": warnings,
        })
    return {"listings": results}
