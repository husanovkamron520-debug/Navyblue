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


def build_asset_manifest(slides):
    """Describe slide assets and report missing provenance or unintended reuse."""
    records = []
    seen = {}
    issues = []
    for index, slide in enumerate(slides or []):
        if not isinstance(slide, dict):
            continue
        asset_meta = slide.get("_asset") if isinstance(slide.get("_asset"), dict) else {}
        single = slide.get("_img")
        multiple = slide.get("_imgs") if isinstance(slide.get("_imgs"), list) else []
        assets = [x for x in ([single] if single is not None else []) + multiple if x is not None]
        assets_meta = slide.get("_assets") if isinstance(slide.get("_assets"), list) else []
        if not assets:
            continue
        per_slide = []
        for asset_index, value in enumerate(assets):
            digest = _asset_id(value)
            meta = {}
            if asset_index == 0 and asset_meta:
                meta.update(asset_meta)
            elif asset_index < len(assets_meta):
                raw_meta = assets_meta[asset_index]
                if isinstance(raw_meta, dict):
                    meta.update(raw_meta)
            source = str(meta.get("source_type") or "unattributed")
            provider = str(meta.get("provider") or meta.get("generator") or "unknown")
            record = {
                "slide_index": index,
                "slide_title": str(slide.get("title") or "")[:140],
                "asset_index": asset_index,
                "asset_id": digest,
                "source_type": source,
                "provider": provider,
                "credit": str(meta.get("credit") or "")[:240],
                "license_status": str(meta.get("license_status") or "not_recorded"),
                "query": str(meta.get("query") or "")[:180],
                "visual_kind": str(meta.get("visual_kind") or slide.get("_visual_kind") or "")[:100],
            }
            records.append(record)
            per_slide.append(record)
            if source == "unattributed":
                issues.append({"slide": index + 1, "severity": "medium", "code": "missing_asset_provenance",
                               "message": "Rasm mavjud, lekin manba/generator metama'lumoti yo'q"})
            if digest and digest in seen:
                prior = seen[digest]
                issues.append({"slide": index + 1, "severity": "medium", "code": "duplicate_asset",
                               "message": f"Rasm {prior + 1}-slaydda ham ishlatilgan"})
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
