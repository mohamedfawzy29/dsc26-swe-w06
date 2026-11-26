"""Per-request cost estimate and a per-tenant daily spend cap for AI calls.

Keep these names exactly (the public and hidden tests import them)."""
from collections.abc import Callable
from datetime import UTC, date, datetime

from app.providers import LLMProvider


def estimate_cost_usd(provider: LLMProvider, prompt: str, max_output_tokens: int) -> float:
    """Worst case: every allowed output token is produced.

    (count_tokens(prompt) * price_in_per_mtok + max_output_tokens * price_out_per_mtok) / 1e6
    """
    return (provider.count_tokens(prompt) * provider.price_in_per_mtok + max_output_tokens * provider.price_out_per_mtok)/1_000_000


def actual_cost_usd(provider: LLMProvider, prompt: str, output_tokens: int) -> float:
    """The same formula with the tokens actually produced."""
    return (provider.count_tokens(prompt) * provider.price_in_per_mtok + output_tokens * provider.price_out_per_mtok)/1_000_000


class DailyBudget:
    """Per-tenant spend limit in USD. Budgets are per (tenant, today()) date; a new date
    starts from zero."""


    def __init__(self, limit_usd: float, today: Callable[[], date] = lambda: datetime.now(UTC).date()):
        self.limit_usd = limit_usd
        self.today = today
        self._spend: dict[tuple[str, date], float] = {}

    def remaining(self, tenant: str) -> float:
        """How much `tenant` can still spend today."""
        key = (tenant, self.today())
        return self.limit_usd - self._spend.get(key, 0.0)

    def try_reserve(self, tenant: str, amount: float) -> bool:
        """Reserve `amount` for `tenant` and return True, only if amount <= remaining(tenant)."""
        if amount <= self.remaining(tenant):
            key = (tenant, self.today())
            self._spend[key] = self._spend.get(key, 0.0) + amount
            return True
        return False

    def settle(self, tenant: str, reserved: float, actual: float) -> None:
        """Replace a reservation with the actual cost (actual may be 0, or more or less than
        reserved)."""
        key = (tenant, self.today())
        self._spend[key] = self._spend.get(key, 0.0) - reserved + actual
