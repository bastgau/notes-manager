"""Bearer-token authentication, as a pure ASGI middleware."""

import hashlib
import hmac


class BearerAuth:
    """Every request needs the bearer token, except the public routes (/healthz, and /version)."""

    def __init__(self, app, token: str, public: dict[str, tuple[bytes, bytes]] | None = None) -> None:
        self.app = app
        self._digest = hashlib.sha256(token.encode()).digest()
        # path -> (body, content type): answered without authentication
        self._public = {"/healthz": (b"ok", b"text/plain"), **(public or {})}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            return
        if scope["path"] in self._public:
            body, content_type = self._public[scope["path"]]
            return await self._respond(send, 200, body, content_type)
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
