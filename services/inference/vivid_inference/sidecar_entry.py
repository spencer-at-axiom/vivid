from __future__ import annotations

import uvicorn

from vivid_inference.config import get_settings
from vivid_inference.main import app


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
