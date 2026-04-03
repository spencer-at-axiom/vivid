from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

_PROMPTING_CONFIG_PATH = Path(__file__).with_name("data") / "prompting_presets.json"
_SUPPORTED_FAMILIES = {"sdxl", "sd15", "flux"}


def _normalize_fragment(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def _merge_csv_fragments(*values: str) -> str:
    seen: set[str] = set()
    merged: list[str] = []
    for raw in values:
        for token in str(raw or "").split(","):
            normalized = _normalize_fragment(token).strip(", ")
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(normalized)
    return ", ".join(merged)


@lru_cache(maxsize=1)
def load_prompting_config() -> dict[str, Any]:
    payload = json.loads(_PROMPTING_CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Prompting config is invalid.")
    return payload


def get_prompting_config() -> dict[str, Any]:
    payload = load_prompting_config()
    return {
        "version": int(payload.get("version", 1)),
        "latency_target_ms": int(payload.get("latency_target_ms", 250)),
        "starter_intents": [normalize_starter_intent(item) for item in payload.get("starter_intents", [])],
        "styles": [normalize_style(item) for item in payload.get("styles", [])],
        "negative_prompt_chips": [normalize_negative_chip(item) for item in payload.get("negative_prompt_chips", [])],
    }


def normalize_starter_intent(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError("Starter intent entry is invalid.")
    return {
        "id": str(raw.get("id", "")).strip(),
        "title": str(raw.get("title", "")).strip(),
        "description": str(raw.get("description", "")).strip(),
        "starter_prompt": _normalize_fragment(str(raw.get("starter_prompt", ""))),
        "style_id": str(raw.get("style_id", "none")).strip() or "none",
        "negative_chip_ids": [
            str(item).strip()
            for item in raw.get("negative_chip_ids", [])
            if isinstance(item, str) and str(item).strip()
        ],
        "recommended_model_family": (
            str(raw.get("recommended_model_family", "sdxl")).strip().lower()
            if str(raw.get("recommended_model_family", "sdxl")).strip().lower() in _SUPPORTED_FAMILIES
            else "sdxl"
        ),
        "recommended_model_ids": [
            str(item).strip()
            for item in raw.get("recommended_model_ids", [])
            if isinstance(item, str) and str(item).strip()
        ],
        "aspect_ratio": str(raw.get("aspect_ratio", "square")).strip() or "square",
        "enhancer_fragments": [
            _normalize_fragment(str(item))
            for item in raw.get("enhancer_fragments", [])
            if isinstance(item, str) and _normalize_fragment(str(item))
        ],
    }


def normalize_style(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError("Style entry is invalid.")
    family_defaults_raw = raw.get("family_defaults", {})
    family_defaults: dict[str, dict[str, str]] = {}
    if isinstance(family_defaults_raw, dict):
        for family, family_config in family_defaults_raw.items():
            if str(family).lower() not in _SUPPORTED_FAMILIES:
                continue
            family_payload = family_config if isinstance(family_config, dict) else {}
            family_defaults[str(family).lower()] = {
                "positive": _normalize_fragment(str(family_payload.get("positive", ""))),
                "negative": _normalize_fragment(str(family_payload.get("negative", ""))),
            }
    return {
        "id": str(raw.get("id", "")).strip(),
        "label": str(raw.get("label", "")).strip(),
        "category": str(raw.get("category", "")).strip(),
        "positive": _normalize_fragment(str(raw.get("positive", "{prompt}"))),
        "negative": _normalize_fragment(str(raw.get("negative", ""))),
        "tags": [str(item).strip() for item in raw.get("tags", []) if isinstance(item, str) and str(item).strip()],
        "family_defaults": family_defaults,
    }


def normalize_negative_chip(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError("Negative prompt chip entry is invalid.")
    return {
        "id": str(raw.get("id", "")).strip(),
        "label": str(raw.get("label", "")).strip(),
        "fragment": _normalize_fragment(str(raw.get("fragment", ""))),
        "category": str(raw.get("category", "")).strip(),
        "tags": [str(item).strip() for item in raw.get("tags", []) if isinstance(item, str) and str(item).strip()],
    }


def get_style(style_id: str | None) -> dict[str, Any]:
    config = get_prompting_config()
    requested = str(style_id or "none").strip().lower()
    for style in config["styles"]:
        if str(style["id"]).lower() == requested:
            return style
    return config["styles"][0]


def get_starter_intent(intent_id: str | None) -> dict[str, Any] | None:
    if not intent_id:
        return None
    config = get_prompting_config()
    requested = str(intent_id).strip().lower()
    for intent in config["starter_intents"]:
        if str(intent["id"]).lower() == requested:
            return intent
    return None


def build_prompt_enhancement(
    prompt: str,
    *,
    style_id: str | None = None,
    intent_id: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    config = get_prompting_config()
    base_prompt = _normalize_fragment(prompt)
    if not base_prompt:
        raise ValueError("prompt is required")

    intent = get_starter_intent(intent_id)
    style = get_style(style_id)

    suggestion = base_prompt
    reasons: list[str] = []

    if ", " not in suggestion and len(suggestion.split()) >= 3:
        suggestion = f"{suggestion}, clear focal subject, intentional composition"
        reasons.append("Added baseline subject and composition framing.")

    if intent:
        enhancer_fragments = [
            fragment
            for fragment in intent.get("enhancer_fragments", [])
            if fragment and fragment.lower() not in suggestion.lower()
        ]
        if enhancer_fragments:
            suggestion = _merge_csv_fragments(suggestion, ", ".join(enhancer_fragments[:3]))
            reasons.append(f"Added {intent['title'].lower()}-specific guidance.")

    if style.get("id") and style.get("id") != "none":
        style_tags = [tag for tag in style.get("tags", []) if tag.lower() not in suggestion.lower()]
        if style_tags:
            suggestion = _merge_csv_fragments(suggestion, ", ".join(style_tags[:2]))
            reasons.append(f"Aligned the wording with the {style['label']} style.")

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "original_prompt": base_prompt,
        "suggested_prompt": suggestion,
        "intent_id": intent["id"] if intent else None,
        "style_id": style["id"],
        "reasons": reasons or ["Normalized whitespace and preserved the original subject."],
        "latency_ms": latency_ms,
        "latency_target_ms": int(config.get("latency_target_ms", 250)),
    }
