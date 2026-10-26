"""Client HTTP verso il backend LazioFlow. Nessuna logica di ranking o di safety qui: solo chiamate."""
from __future__ import annotations

import httpx
import os

from .config import BACKEND_TIMEOUT_S, BACKEND_URL


class BackendError(Exception):
    pass


class Api:
    def __init__(self, base_url: str = BACKEND_URL, timeout: float = BACKEND_TIMEOUT_S):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        key = os.getenv("LAZIOFLOW_API_KEY", "")
        self.headers = {"X-API-Key": key} if key else {}

    @staticmethod
    def _decode(response: httpx.Response) -> dict:
        if response.status_code >= 300:
            raise BackendError(f"backend {response.status_code}")
        try:
            data = response.json()
        except ValueError as ex:
            raise BackendError("risposta del backend non valida") from ex
        if not isinstance(data, dict):
            raise BackendError("risposta del backend non valida")
        return data

    async def _post(self, path: str, body: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as c:
                r = await c.post(f"{self.base_url}{path}", json=body)
        except httpx.HTTPError as e:
            raise BackendError(f"backend non raggiungibile ({type(e).__name__})") from e
        return self._decode(r)

    async def _get(self, path: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as c:
                r = await c.get(f"{self.base_url}{path}")
        except httpx.HTTPError as e:
            raise BackendError(f"backend non raggiungibile ({type(e).__name__})") from e
        return self._decode(r)

    async def understand(self, text: str) -> dict:
        return await self._post("/understand", {"text": text})

    async def recommend(self, category: str, lat: float, lng: float, preference: str = "balanced",
                        age_group: str = "unknown", facility_type: str | None = None, limit: int = 3) -> dict:
        body = {"category": category, "location": {"lat": lat, "lng": lng}, "preference": preference,
                "age_group": age_group, "limit": limit}
        if facility_type:
            body["facility_type"] = facility_type
        return await self._post("/recommend", body)

    async def explain(self, text: str, recommendations: list[dict]) -> dict:
        return await self._post("/explain", {"text": text, "recommendations": recommendations})

    async def health(self) -> dict:
        return await self._get("/health")

    async def ps_live(self) -> dict:
        return await self._get("/ps/live")

    async def sources(self) -> dict:
        return await self._get("/sources")

    async def coverage(self) -> dict:
        return await self._get("/coverage")
