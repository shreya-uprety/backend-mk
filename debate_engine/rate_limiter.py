from __future__ import annotations
import time
from collections import defaultdict

# ── Configuration ────────────────────────────────────────────────────────

RATE_LIMITS = {
    "max_requests_per_minute": 5,
    "max_requests_per_hour": 30,
    "max_requests_per_day": 200,
    "daily_token_budget": 500_000,
    "consecutive_failure_threshold": 3,
    "circuit_breaker_cooldown_sec": 60,
}

# ── In-memory state (reset on server restart) ────────────────────────────

_request_log: dict[str, list[float]] = defaultdict(list)
_daily_tokens: dict[str, int] = defaultdict(int)
_failure_count: dict[str, int] = defaultdict(int)
_circuit_open_until: dict[str, float] = defaultdict(float)


def _cleanup(key: str, window_sec: int):
    """Remove timestamps older than window."""
    cutoff = time.time() - window_sec
    _request_log[key] = [t for t in _request_log[key] if t > cutoff]


def check_rate_limit(client_id: str = "global") -> tuple[bool, str]:
    """Check if a request is allowed.

    Returns:
        (allowed: bool, reason: str)
    """
    now = time.time()

    # Circuit breaker
    if now < _circuit_open_until[client_id]:
        remaining = int(_circuit_open_until[client_id] - now)
        return False, f"Circuit breaker open. Retry in {remaining}s."

    # Per-minute
    _cleanup(f"{client_id}:min", 60)
    if len(_request_log[f"{client_id}:min"]) >= RATE_LIMITS["max_requests_per_minute"]:
        return False, "Rate limit: max 5 requests per minute."

    # Per-hour
    _cleanup(f"{client_id}:hr", 3600)
    if len(_request_log[f"{client_id}:hr"]) >= RATE_LIMITS["max_requests_per_hour"]:
        return False, "Rate limit: max 30 requests per hour."

    # Per-day
    _cleanup(f"{client_id}:day", 86400)
    if len(_request_log[f"{client_id}:day"]) >= RATE_LIMITS["max_requests_per_day"]:
        return False, "Rate limit: max 200 requests per day."

    # Daily token budget
    today = time.strftime("%Y-%m-%d")
    if _daily_tokens[today] >= RATE_LIMITS["daily_token_budget"]:
        return False, f"Daily token budget exhausted ({RATE_LIMITS['daily_token_budget']} tokens)."

    return True, "ok"


def record_request(client_id: str = "global"):
    """Record a successful request."""
    now = time.time()
    _request_log[f"{client_id}:min"].append(now)
    _request_log[f"{client_id}:hr"].append(now)
    _request_log[f"{client_id}:day"].append(now)
    _failure_count[client_id] = 0


def record_tokens(tokens_used: int):
    """Track daily token consumption."""
    today = time.strftime("%Y-%m-%d")
    _daily_tokens[today] += tokens_used


def record_failure(client_id: str = "global"):
    """Track consecutive failures for circuit breaker."""
    _failure_count[client_id] += 1
    if _failure_count[client_id] >= RATE_LIMITS["consecutive_failure_threshold"]:
        _circuit_open_until[client_id] = (
            time.time() + RATE_LIMITS["circuit_breaker_cooldown_sec"]
        )


def get_daily_budget_remaining() -> int:
    """Get remaining daily token budget."""
    today = time.strftime("%Y-%m-%d")
    return max(0, RATE_LIMITS["daily_token_budget"] - _daily_tokens[today])
