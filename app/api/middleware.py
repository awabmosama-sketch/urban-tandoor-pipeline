"""
Request ID middleware. Adds X-Request-ID to every response.
If the client sent X-Request-ID, it's preserved; otherwise a UUID4 is generated.
Runs outermost so even error responses carry an ID.
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("X-Request-ID")
        request_id = incoming if incoming else str(uuid.uuid4())
        # Stash on request state so handlers can log it
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
