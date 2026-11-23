import asyncio

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

from app.config import settings


MAX_WEBSOCKET_MESSAGE_BYTES = 8192


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def secured_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Cache-Control"] = "no-store"
                if settings.ENABLE_HSTS and scope.get("scheme") == "https":
                    headers["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        await self.app(scope, receive, secured_send)


class RequestBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        lengths = headers.getlist("content-length")
        if len(lengths) > 1 or (lengths and not lengths[0].isascii()) or (
            lengths and (not lengths[0].isdigit() or "transfer-encoding" in headers)
        ):
            return await JSONResponse({"detail": "Invalid request framing."}, 400)(scope, receive, send)
        limit = settings.MAX_REQUEST_BODY_BYTES
        # Reject an oversized decimal without converting an arbitrarily long header to an integer.
        length = (lengths[0].lstrip("0") or "0") if lengths else "0"
        if len(length) > len(str(limit)) or int(length) > limit:
            return await JSONResponse({"detail": "Request body is too large."}, 413)(scope, receive, send)
        if (scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"} and
                not lengths and "transfer-encoding" not in headers):
            return await self.app(scope, receive, send)

        buffered = bytearray()
        try:
            async with asyncio.timeout(10):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(buffered) + len(chunk) > limit:
                        return await JSONResponse({"detail": "Request body is too large."}, 413)(scope, receive, send)
                    buffered.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            return await JSONResponse({"detail": "Request body timed out."}, 408)(scope, receive, send)

        pending = True

        async def replay():
            nonlocal pending
            if pending:
                pending = False
                return {"type": "http.request", "body": bytes(buffered), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
