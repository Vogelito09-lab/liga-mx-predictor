"""Cliente HTTP compartido: tiempo de espera, reintentos con espera exponencial y pausa entre consultas."""
from __future__ import annotations

import logging
import threading
import time

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import get_settings

log = logging.getLogger(__name__)

USER_AGENT = "LigaMXPredictor/1.0 (proyecto personal, no comercial)"


class SourceError(RuntimeError):
    """La fuente no respondió o respondió algo inutilizable. Los datos existentes no se tocan."""


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


class PoliteClient:
    def __init__(self, min_interval_s: float | None = None, timeout_s: float | None = None):
        s = get_settings()
        self._min_interval = s.http_min_interval_s if min_interval_s is None else min_interval_s
        self._client = httpx.Client(
            timeout=timeout_s or s.http_timeout_s,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,*/*"},
            follow_redirects=True,
        )
        self._last = 0.0
        self._lock = threading.Lock()

    def _wait_turn(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()

    @retry(
        retry=retry_if_exception(_retryable),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def _get(self, url: str, params: dict | None) -> httpx.Response:
        self._wait_turn()
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp

    def get_json(self, url: str, params: dict | None = None) -> dict:
        try:
            return self._get(url, params).json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"GET {url} {params or ''} falló: {exc}") from exc

    def get_text(self, url: str, params: dict | None = None) -> str:
        try:
            return self._get(url, params).text
        except httpx.HTTPError as exc:
            raise SourceError(f"GET {url} falló: {exc}") from exc

    def close(self) -> None:
        self._client.close()
