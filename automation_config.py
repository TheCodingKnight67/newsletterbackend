"""Server-only configuration; never put API keys in React environment variables."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from runtime_env import is_production

load_dotenv()


@dataclass
class Settings:
    model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"))
    mode: str = field(default_factory=lambda: os.getenv("AUTOMATION_MODE", "preview"))
    output_tokens: int = field(default_factory=lambda: int(os.getenv("MAX_OUTPUT_TOKENS", "1000")))
    research_tokens: int = field(default_factory=lambda: int(os.getenv("RESEARCH_OUTPUT_TOKENS", "1800")))
    input_limit: int = field(default_factory=lambda: int(os.getenv("MAX_INPUT_TOKENS", "16000")))
    search_allowance: int = field(default_factory=lambda: int(os.getenv("SEARCH_INPUT_TOKEN_ALLOWANCE", "50000")))
    request_budget: float = field(default_factory=lambda: float(os.getenv("REQUEST_BUDGET_USD", "0.50")))
    monthly_budget: float = field(default_factory=lambda: float(os.getenv("MONTHLY_BUDGET_USD", "5.00")))
    input_price: float = field(default_factory=lambda: float(os.getenv("INPUT_USD_PER_MILLION", "3")))
    output_price: float = field(default_factory=lambda: float(os.getenv("OUTPUT_USD_PER_MILLION", "15")))
    search_price: float = field(default_factory=lambda: float(os.getenv("SEARCH_USD", "0.01")))
    characters_dir: Path = field(default_factory=lambda: Path(os.getenv("CHARACTERS_DIR", "characters")))
    timezone: str = field(default_factory=lambda: os.getenv("SCHEDULE_TIMEZONE", "Europe/London"))
    morning_hour: int = field(default_factory=lambda: int(os.getenv("MORNING_HOUR", "8")))
    bedtime_hour: int = field(default_factory=lambda: int(os.getenv("BEDTIME_HOUR", "21")))
    poll_seconds: int = field(default_factory=lambda: int(os.getenv("WORKER_POLL_SECONDS", "10")))
    attempts: int = field(default_factory=lambda: int(os.getenv("MAX_GENERATION_ATTEMPTS", "3")))
    scheduler: bool = field(default_factory=lambda: os.getenv("SCHEDULER_ENABLED", "false" if is_production() else "true").lower() == "true")

    def __post_init__(self):
        if self.mode not in {"preview", "send"}:
            raise ValueError("AUTOMATION_MODE must be preview or send")
        if not 128 <= self.output_tokens <= 8192 or not 512 <= self.research_tokens <= 8192:
            raise ValueError("Invalid output token limit")
        if min(self.input_limit, self.search_allowance, self.poll_seconds, self.attempts) <= 0:
            raise ValueError("Limits must be positive")
        if min(self.request_budget, self.monthly_budget, self.input_price, self.output_price, self.search_price) <= 0:
            raise ValueError("Budgets and prices must be positive")
        if not 0 <= self.morning_hour < self.bedtime_hour <= 23:
            raise ValueError("Schedule hours must be ordered and between 0 and 23")
        ZoneInfo(self.timezone)

    def price(self, inputs, outputs, searches=0):
        return (inputs * self.input_price + outputs * self.output_price) / 1_000_000 + searches * self.search_price
