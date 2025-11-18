import base64

from flask import Request, Response

from medallion.common import ADMIN_USER, MEDIA_TYPE_TAXII_V21


class AuthenticationMiddleware:
    def __init__(self, app: callable, wsgi_app: callable) -> None:
        self.app = app
        self.wsgi_app = wsgi_app
        self.unauthorized_response = Response(
            response="Unauthorized Access",
            status=401,
            mimetype=MEDIA_TYPE_TAXII_V21,
        )

    def __call__(self, environ: dict, start_response: callable):
        rq = Request(environ)

        # Avoid validate healthcheck path
        if self._is_healthcheck_path(rq):
            return self.wsgi_app(environ, start_response)

        # If the username is not set the request is unauthorized
        if (username := self._get_username_from_auth(rq)) is None:
            return self.unauthorized_response(environ, start_response)

        # If the user is admin or the backend is not set (running with no MongoDB), allow the request
        if self._is_user_admin(username) or not self._auth_backend_is_set():
            return self.wsgi_app(environ, start_response)

        if (collection := self._extract_collection_id(rq)) is None or (api_root := self._extract_api_root(rq)) is None:
            return self.wsgi_app(environ, start_response)

        collection_license = self.app.medallion_backend.get_collection_license(api_root, collection)

        if self.app.auth_backend.can_user_read_collection(username, collection_license):
            return self.wsgi_app(environ, start_response)

        return self.unauthorized_response(environ, start_response)

    def _is_healthcheck_path(self, rq: Request) -> bool:
        return rq.path == '/ping'

    def _auth_backend_is_set(self) -> bool:
        return hasattr(self.app, "auth_backend")

    def _is_user_admin(self, username: str) -> bool:
        return username == ADMIN_USER

    def _get_username_from_auth(self, rq: Request) -> str | None:
        """Extract username from HTTP Basic Auth header, and return None if not present."""
        auth_header = rq.headers.get('Authorization', '')

        if not auth_header.startswith('Basic '):
            return None

        # Decode base64 credentials
        credentials = base64.b64decode(auth_header[6:]).decode('utf-8')
        username, _ = credentials.split(':', 1)
        return username

    def _extract_collection_id(self, rq: Request) -> str | None:
        """Extract collection_id from URL path.

        Assuming URL pattern: /api_root/collections/{collection_id}/...
        """
        path_parts = rq.path.strip('/').split('/')

        if 'collections' in path_parts:
            idx = path_parts.index('collections')
            if idx + 1 < len(path_parts):
                return path_parts[idx + 1]
        return None

    def _extract_api_root(self, rq: Request) -> str | None:
        """Extract api_root from URL path.

        Assuming first path segment is api_root:: /api_root/...
        """
        path_parts = rq.path.strip('/').split('/')
        return path_parts[0] if path_parts else None
