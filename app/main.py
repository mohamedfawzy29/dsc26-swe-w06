"""The HTTP layer around explain_stream.

Keep `StreamSettings` and `create_app` exactly as named; the public and hidden tests import
them."""
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field

from app.budget import DailyBudget, estimate_cost_usd
from app.providers import LLMProvider, build_prompt
from app.stream import explain_stream


@dataclass
class StreamSettings:
    ttft_timeout_s: float = 2.0
    total_timeout_s: float = 20.0
    max_output_tokens: int = 400


class ExplainRequest(BaseModel):
    clause_text: str = Field(min_length=1, max_length=8000)
    language: Literal["ar", "en"]


@dataclass
class _Prepared:
    tenant: str
    prompt: str


class _BudgetExhaustedError(Exception):
    pass


def create_app(providers: Sequence[LLMProvider], budget: DailyBudget,
               settings: StreamSettings | None = None) -> FastAPI:
    """Return a NEW FastAPI app exposing POST /v1/clauses/explain."""
    cfg = settings if settings is not None else StreamSettings()
    app = FastAPI()

    @app.exception_handler(_BudgetExhaustedError)
    async def _budget_exhausted_handler(_request: Request, _exc: _BudgetExhaustedError) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            media_type="application/problem+json",
            content={
                "type": "/problems/budget-exhausted",
                "title": "Daily budget exhausted",
                "status": 429,
            },
        )

    def prepare(
        body: ExplainRequest,
        x_tenant_id: Annotated[str, Header(alias="X-Tenant-ID", min_length=1, max_length=64)],
    ) -> _Prepared:
        prompt = build_prompt(body.clause_text, body.language)
        if not providers or budget.remaining(x_tenant_id) < min(
            estimate_cost_usd(p, prompt, cfg.max_output_tokens) for p in providers
        ):
            raise _BudgetExhaustedError()
        return _Prepared(tenant=x_tenant_id, prompt=prompt)

    @app.post("/v1/clauses/explain", response_class=EventSourceResponse)
    async def explain_clause(prep: Annotated[_Prepared, Depends(prepare)]) -> AsyncIterator[ServerSentEvent]:
        async for ev in explain_stream(
            prep.prompt,
            providers,
            tenant=prep.tenant,
            budget=budget,
            ttft_timeout_s=cfg.ttft_timeout_s,
            total_timeout_s=cfg.total_timeout_s,
            max_output_tokens=cfg.max_output_tokens,
        ):
            yield ServerSentEvent(event=ev.kind, data=ev.data)

    return app
