from requests import Request

from medallion import APPLICATION_INSTANCE


class AuthService:
    ADMIN_USER = 'nozominetworks'

    def __init__(self, rq: Request, current_user: str):
        self.rq = rq
        self._current_user = current_user

    def can_user_access_collection(self) -> bool:
        # Avoid validate healthcheck path
        if self._is_healthcheck_path(self.rq):
            return True

        # If the user is admin or the backend is not set (running with no MongoDB), allow the request
        if self.is_user_admin(self._current_user):
            return True

        if (
                (collection := self._extract_collection_id(self.rq)) is None or
                (api_root := self._extract_api_root(self.rq)) is None
        ):
            return False

        collection_license = APPLICATION_INSTANCE.medallion_backend.get_collection_license(api_root, collection)

        if APPLICATION_INSTANCE.auth_backend.can_user_read_collection(self._current_user, collection_license):
            return True

        return False

    def _is_healthcheck_path(self, rq: Request) -> bool:
        return rq.path == '/ping'

    @classmethod
    def is_user_admin(cls, username: str) -> bool:
        """Check if the user has admin privileges.

        If the auth backend is not set, it checks the username only.
        Otherwise, it queries the auth backend for user details.
        """
        if not hasattr(APPLICATION_INSTANCE, "auth_backend"):
            return username == cls.ADMIN_USER

        return APPLICATION_INSTANCE.auth_backend.get_user_by_username(username).get("is_admin", False)

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
