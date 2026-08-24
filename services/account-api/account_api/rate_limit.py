from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque

from fastapi import Request
from starlette.responses import JSONResponse

from account_api.config import Settings


@dataclass(frozen=True, slots=True)
class RateRule:
    limit: int
    window_seconds: int


class InProcessRateLimiter:
    """Small per-process limiter suitable for the account-service edge.

    This intentionally does not pretend to be a distributed global limiter.
    Multi-replica deployments should put a shared limiter at the ingress layer
    or replace this implementation with a shared store. It still provides a
    useful application-layer guard for single-instance deployments and CI.
    """

    def __init__(self) -> None:
        self._events: dict[tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: str, bucket: str, rule: RateRule) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - rule.window_seconds
        async with self._lock:
            queue = self._events[(key, bucket)]
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if len(queue) >= rule.limit:
                retry = max(1, int(rule.window_seconds - (now - queue[0])))
                return False, retry
            queue.append(now)
            return True, 0


def request_identity(request: Request) -> str:
    # Do not trust forwarded headers implicitly. A production reverse proxy can
    # enforce its own distributed limiter or rewrite request.client safely.
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rule_for_request(request: Request, settings: Settings) -> tuple[str, RateRule] | None:
    path = request.url.path
    if path == "/v1/auth/login":
        return "login", RateRule(settings.login_attempts_per_5_minutes, 300)
    if path == "/v1/auth/signup":
        return "signup", RateRule(settings.signup_attempts_per_10_minutes, 600)
    if path == "/v1/auth/refresh":
        return "refresh", RateRule(settings.refresh_attempts_per_minute, 60)
    if path.startswith("/v1/"):
        return "authenticated", RateRule(settings.authenticated_requests_per_minute, 60)
    return None


def install_account_guard_middleware(app, settings: Settings) -> None:
    limiter = InProcessRateLimiter()

    @app.middleware("http")
    async def deployment_and_rate_guard(request: Request, call_next):
        path = request.url.path

        if path.startswith("/v1/") and path != "/v1/config" and not settings.auth_enabled:
            return JSONResponse(
                {"detail": "account features are disabled for this deployment"},
                status_code=404,
            )

        if settings.abuse_controls_enabled:
            match = rule_for_request(request, settings)
            if match is not None:
                bucket, rule = match
                allowed, retry_after = await limiter.allow(request_identity(request), bucket, rule)
                if not allowed:
                    return JSONResponse(
                        {"detail": "too many requests"},
                        status_code=429,
                        headers={"Retry-After": str(retry_after)},
                    )

        return await call_next(request)
