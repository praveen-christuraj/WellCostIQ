"""Receive-level limits, including multipart bytes before Starlette spools files."""
from fastapi import HTTPException
from starlette.responses import JSONResponse


class BodySizeLimitMiddleware:
    def __init__(self, app, *, json_bytes: int, multipart_bytes: int, backup_bytes: int):
        self.app = app
        self.json_bytes = json_bytes
        self.multipart_bytes = multipart_bytes
        self.backup_bytes = backup_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        multipart = any(k.lower() == b"content-type" and v.lower().startswith(b"multipart/") for k, v in headers)
        limit = self.multipart_bytes if multipart else self.json_bytes
        if multipart and scope["method"] == "POST" and scope["path"].rstrip("/") == "/api/v1/backup/jobs/import":
            limit = self.backup_bytes
        lengths = [v for k, v in headers if k.lower() == b"content-length"]
        if lengths and (len(lengths) != 1 or not lengths[0] or any(c < 48 or c > 57 for c in lengths[0]) or len(lengths[0]) > 20):
            return await JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)(scope, receive, send)
        if lengths and int(lengths[0]) > limit:
            return await JSONResponse({"detail": "The request body is too large."}, status_code=413)(scope, receive, send)
        received = 0
        exceeded = False
        replaced = False

        async def bounded_receive():
            nonlocal received, exceeded
            if exceeded:
                raise HTTPException(413, "The request body is too large.")
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise HTTPException(413, "The request body is too large.")
            return message

        async def bounded_send(message):
            # Multipart parsers may translate receive errors to 400. Preserve 413.
            nonlocal replaced
            if exceeded:
                if message["type"] == "http.response.start" and not replaced:
                    replaced = True
                    await JSONResponse({"detail": "The request body is too large."}, status_code=413)(scope, receive, send)
                return
            await send(message)

        await self.app(scope, bounded_receive, bounded_send)
