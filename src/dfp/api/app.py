"""The feature API a decision flow calls: POST /v1/features. Runs on Lambda behind an HTTP API
(Mangum), or under uvicorn locally."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from dfp.service.features import FeatureService


class FeatureRequest(BaseModel):
    entity_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    features: list[str] = Field(min_length=1, max_length=50)


class FeatureOut(BaseModel):
    value: Any
    source: str
    age_s: float | None


class FeatureResponse(BaseModel):
    entity_id: str
    features: dict[str, FeatureOut]


def create_app(service: FeatureService, tenant_for_key: Any) -> FastAPI:
    app = FastAPI(title="decision-feature-platform", version="1.0.0")

    def tenant(x_api_key: str = Header(default="")) -> str:
        t = tenant_for_key(x_api_key) if x_api_key else None
        if t is None:
            raise HTTPException(status_code=401, detail="unknown API key")
        return str(t)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/features", response_model=FeatureResponse)
    async def features(req: FeatureRequest, tenant_id: str = Depends(tenant)) -> FeatureResponse:
        try:
            values = await service.get(tenant_id, req.entity_id, req.features)
        except KeyError as e:
            raise HTTPException(status_code=422, detail=str(e.args[0])) from e
        return FeatureResponse(
            entity_id=req.entity_id,
            features={k: FeatureOut(value=v.value, source=v.source, age_s=v.age_s) for k, v in values.items()},
        )

    return app
