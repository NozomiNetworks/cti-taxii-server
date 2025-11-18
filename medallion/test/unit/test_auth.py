from unittest.mock import MagicMock

import pytest

from medallion.middleware.auth import AuthenticationMiddleware


class TestAuthenticationMiddleware:
    def test_is_healthcheck_path(self, auth_middleware):
        environ = {'PATH_INFO': '/ping'}
        rq = MagicMock()
        rq.path = environ['PATH_INFO']
        assert auth_middleware._is_healthcheck_path(rq) is True

        environ = {'PATH_INFO': '/other'}
        rq.path = environ['PATH_INFO']
        assert auth_middleware._is_healthcheck_path(rq) is False

    def test_auth_backend_is_set(self, auth_middleware):
        auth_middleware.app = MagicMock()
        auth_middleware.app.auth_backend = MagicMock()
        assert auth_middleware._auth_backend_is_set() is True

        del auth_middleware.app.auth_backend
        assert auth_middleware._auth_backend_is_set() is False

    def test_is_user_admin(self, auth_middleware):
        assert auth_middleware._is_user_admin('admin') is False
        assert auth_middleware._is_user_admin('mandiant') is False
        assert auth_middleware._is_user_admin('nozominetworks') is True

    def test_get_username_from_auth(self, auth_middleware):
        rq = MagicMock()
        rq.headers = {'Authorization': 'Basic dXNlcjpwYXNz'}  # base64 for 'user:pass'
        assert auth_middleware._get_username_from_auth(rq) == 'user'

    def test_extract_collection_id(self, auth_middleware):
        rq = MagicMock()
        rq.path = '/root1/collections/collection1/objects/'
        assert auth_middleware._extract_collection_id(rq) == 'collection1'

    def test_extract_api_root(self, auth_middleware):
        rq = MagicMock()
        rq.path = '/root1/collections/collection1/objects/'
        assert auth_middleware._extract_api_root(rq) == 'root1'

    @pytest.fixture
    def auth_middleware(self):
        return AuthenticationMiddleware(MagicMock(), MagicMock())
