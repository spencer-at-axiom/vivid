from __future__ import annotations

from fastapi import APIRouter

from ..errors import ApiError
from ..prompting import build_prompt_enhancement, get_prompting_config
from ..schemas import PromptEnhanceRequest

router = APIRouter(prefix="/prompting", tags=["prompting"])


@router.get("/config")
async def prompting_config() -> dict[str, object]:
    return {"item": get_prompting_config()}


@router.post("/enhance")
async def enhance_prompt(request: PromptEnhanceRequest) -> dict[str, object]:
    try:
        return {
            "item": build_prompt_enhancement(
                request.prompt,
                style_id=request.style_id,
                intent_id=request.intent_id,
            )
        }
    except ValueError as error:
        raise ApiError(code="prompt_enhance_failed", message="Prompt enhancement failed.", status_code=400, detail=str(error))
