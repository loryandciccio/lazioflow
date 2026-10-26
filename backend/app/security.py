"""Protezione del backend privato: chiave condivisa e budget globale per processo."""
import hmac
import os
import time
from collections import deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class AccessGuard(BaseHTTPMiddleware):
    def __init__(self, app, api_key=None, limit=None, production=None):
        super().__init__(app)
        self.api_key = os.getenv("LAZIOFLOW_API_KEY", "") if api_key is None else api_key
        self.limit = int(os.getenv("API_REQUESTS_PER_MINUTE", "1200")) if limit is None else limit
        self.production = os.getenv("LAZIOFLOW_ENV", "development") == "production" if production is None else production
        self.requests = deque()
        self.ai_requests = deque()
        self.ai_limit = int(os.getenv("AI_REQUESTS_PER_MINUTE", "30"))

    async def dispatch(self, request, call_next):
        if self.production and not self.api_key:
            return JSONResponse({"detail": "Configurazione accesso mancante"}, status_code=503)
        if self.api_key and not hmac.compare_digest(request.headers.get("x-api-key", "").encode(), self.api_key.encode()):
            return JSONResponse({"detail": "Accesso non autorizzato"}, status_code=401)
        now = time.monotonic()
        queues = [(self.requests, self.limit)]
        if request.url.path in ("/parse", "/understand", "/explain"):
            queues.append((self.ai_requests, self.ai_limit))
        for queue, limit in queues:
            while queue and queue[0] <= now - 60:
                queue.popleft()
            if len(queue) >= limit:
                return JSONResponse({"detail": "Limite temporaneo raggiunto"}, status_code=429,
                                    headers={"Retry-After": "60"})
        for queue, _ in queues:
            queue.append(now)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response
