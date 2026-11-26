"""The streaming core: provider fallback, two deadlines, budget reserve/settle.

Keep `Event` and `explain_stream` exactly as named; the public and hidden tests import them."""
import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field

from app.budget import DailyBudget, actual_cost_usd, estimate_cost_usd
from app.providers import LLMProvider, ProviderError


@dataclass(frozen=True)
class Event:
    kind: str                       # "meta" | "token" | "done" | "error"
    data: dict = field(default_factory=dict)


async def explain_stream(prompt: str, providers: Sequence[LLMProvider], *, tenant: str,
                         budget: DailyBudget, ttft_timeout_s: float, total_timeout_s: float,
                         max_output_tokens: int) -> AsyncIterator[Event]:
    """Yield Event("meta", ...), Event("token", ...)* and a final Event("done" | "error", ...)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + total_timeout_s
    attempted = False

    for provider in providers:
        time_left = deadline - loop.time()
        if time_left <= 0:
            yield Event("error", {"code": "deadline_exceeded", "partial": False})
            return

        estimated = estimate_cost_usd(provider, prompt, max_output_tokens)
        if not budget.try_reserve(tenant, estimated):
            continue

        attempted = True
        tokens_produced = 0
        settled = False

        def settle_once(actual: float) -> None:
            nonlocal settled
            if not settled:
                settled = True
                budget.settle(tenant, estimated, actual)

        try:
            async with aclosing(provider.stream(prompt, max_output_tokens)) as stream:
                time_left = deadline - loop.time()
                if time_left <= 0:
                    settle_once(0.0)
                    yield Event("error", {"code": "deadline_exceeded", "partial": False})
                    return

                ttft = min(ttft_timeout_s, time_left)
                try:
                    first_token = await asyncio.wait_for(anext(stream), timeout=ttft)
                except TimeoutError:
                    settle_once(0.0)
                    if deadline - loop.time() <= 0:
                        yield Event("error", {"code": "deadline_exceeded", "partial": False})
                        return
                    continue
                except (StopAsyncIteration, ProviderError):
                    settle_once(0.0)
                    continue

                tokens_produced = 1
                yield Event("meta", {"provider": provider.name})
                yield Event("token", {"text": first_token})

                while True:
                    time_left = deadline - loop.time()
                    if time_left <= 0:
                        actual = actual_cost_usd(provider, prompt, tokens_produced)
                        settle_once(actual)
                        yield Event("error", {"code": "deadline_exceeded", "partial": True})
                        return

                    try:
                        token = await asyncio.wait_for(anext(stream), timeout=time_left)
                    except StopAsyncIteration:
                        actual = actual_cost_usd(provider, prompt, tokens_produced)
                        settle_once(actual)
                        yield Event("done", {
                            "provider": provider.name,
                            "output_tokens": tokens_produced,
                            "cost_usd": actual,
                        })
                        return
                    except TimeoutError:
                        actual = actual_cost_usd(provider, prompt, tokens_produced)
                        settle_once(actual)
                        yield Event("error", {"code": "deadline_exceeded", "partial": True})
                        return
                    except ProviderError:
                        actual = actual_cost_usd(provider, prompt, tokens_produced)
                        settle_once(actual)
                        yield Event("error", {"code": "upstream_interrupted", "partial": True})
                        return

                    tokens_produced += 1
                    yield Event("token", {"text": token})
        finally:
            settle_once(actual_cost_usd(provider, prompt, tokens_produced) if tokens_produced else 0.0)

    if not attempted:
        yield Event("error", {"code": "budget_exhausted"})
    else:
        yield Event("error", {"code": "all_providers_failed"})
