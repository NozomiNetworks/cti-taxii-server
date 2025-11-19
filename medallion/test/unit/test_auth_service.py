from unittest.mock import MagicMock, patch

import pytest

from medallion.auth_service import AuthService


class TestAuthService:
    def test_is_healthcheck_path(self, auth_middleware):
        environ = {'PATH_INFO': '/ping'}
        rq = MagicMock()
        rq.path = environ['PATH_INFO']
        assert auth_middleware._is_healthcheck_path(rq) is True

        environ = {'PATH_INFO': '/other'}
        rq.path = environ['PATH_INFO']
        assert auth_middleware._is_healthcheck_path(rq) is False

    def test_is_user_admin_auth_backend_not_set(self, auth_middleware):
        assert auth_middleware.is_user_admin('admin') is False
        assert auth_middleware.is_user_admin('mandiant') is False
        assert auth_middleware.is_user_admin('nozominetworks') is True

    def test_is_user_admin_auth_backend_set(self, auth_middleware):
        with patch("medallion.auth_service.APPLICATION_INSTANCE") as app_instance:
            mock_auth_backend = MagicMock()
            mock_auth_backend.get_user_by_username.side_effect = lambda username: {
                'nozominetworks': {'is_admin': True},
                'user': {'is_admin': False}
            }.get(username, {})
            app_instance.auth_backend = mock_auth_backend

            assert auth_middleware.is_user_admin('admin') is False
            assert auth_middleware.is_user_admin('user') is False
            assert auth_middleware.is_user_admin('nozominetworks') is True

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
        return AuthService(MagicMock(), "username")
