"""Bearer-token authentication, as a pure ASGI middleware."""

import hashlib
import hmac


class BearerAuth:
    """Every request needs the bearer token, except GET /healthz."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self._digest = hashlib.sha256(token.encode()).digest()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            return
        if scope["path"] == "/healthz":
            return await self._respond(send, 200, b"ok", b"text/plain")
        header = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        scheme, _, credential = header.partition(" ")
        given = hashlib.sha256(credential.strip().encode()).digest()
        if scheme.lower() != "bearer" or not hmac.compare_digest(given, self._digest):
            return await self._respond(
                send, 401, b'{"error":"unauthorized"}', b"application/json",
                [(b"www-authenticate", b"Bearer")],
            )
        return await self.app(scope, receive, send)

    @staticmethod
    async def _respond(send, status, body, content_type, extra=()):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", content_type),
                                (b"content-length", str(len(body)).encode()), *extra]})
        await send({"type": "http.response.body", "body": body})
