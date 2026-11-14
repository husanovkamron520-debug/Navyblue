"""Asset provenance manifest and duplicate-media critic for generated decks."""
from __future__ import annotations

import hashlib
from collections import Counter


def _asset_id(value):
    if isinstance(value, (bytes, bytearray)):
        return hashlib.sha256(bytes(value)).hexdigest()
    if isinstance(value, str):
        return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()
    return None


def _record(slide, slide_index, asset_index, value, metadata):
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "slide_index": slide_index,
        "slide_title": str(slide.get("title") or "")[:140],
        "asset_index": asset_index,
        "asset_id": _asset_id(value),
        "source_type": str(metadata.get("source_type") or "unattributed"),
        "provider": str(metadata.get("provider") or metadata.get("generator") or "unknown"),
        "credit": str(metadata.get("credit") or "")[:400],
        "license_status": str(metadata.get("license_status") or "not_recorded"),
        "query": str(metadata.get("query") or "")[:180],
        "visual_kind": str(metadata.get("visual_kind") or slide.get("_visual_kind") or "")[:100],
    }


def build_asset_manifest(slides):
    """Describe slide assets and report missing provenance or repeated media."""
    records = []
    seen = {}
    issues = []
    for index, slide in enumerate(slides or []):
        if not isinstance(slide, dict):
            continue
        per_slide = []
        single = slide.get("_img")
        if single is not None:
            per_slide.append(_record(slide, index, 0, single, slide.get("_asset")))
        multiple = slide.get("_imgs") if isinstance(slide.get("_imgs"), list) else []
        assets_meta = slide.get("_assets") if isinstance(slide.get("_assets"), list) else []
        for asset_index, value in enumerate(multiple):
            if value is None:
                continue
            meta = assets_meta[asset_index] if asset_index < len(assets_meta) else {}
            per_slide.append(_record(slide, index, asset_index + 1, value, meta))

        for record in per_slide:
            records.append(record)
            if record["source_type"] == "unattributed":
                issues.append({"slide": index + 1, "severity": "medium",
                               "code": "missing_asset_provenance",
                               "message": "Rasm mavjud, lekin manba yoki generator metama'lumoti yo'q"})
            if record["source_type"] == "retrieved" and not record["credit"]:
                issues.append({"slide": index + 1, "severity": "medium",
                               "code": "missing_asset_credit",
                               "message": "Tashqi rasm uchun attribution ma'lumoti yo'q"})
            digest = record["asset_id"]
            if digest and digest in seen:
                issues.append({"slide": index + 1, "severity": "high",
                               "code": "duplicate_asset",
                               "message": f"Rasm oldingi asset bilan takrorlangan (birinchi slayd: {seen[digest] + 1})"})
            elif digest:
                seen[digest] = index
        slide["_asset_manifest_count"] = len(per_slide)

    source_counts = Counter(x["source_type"] for x in records)
    return {
        "asset_count": len(records),
        "slide_count_with_assets": len({x["slide_index"] for x in records}),
        "source_counts": dict(source_counts),
        "records": records,
        "issue_count": len(issues),
        "issues": issues,
        "passed": not any(x["severity"] == "high" for x in issues),
    }
