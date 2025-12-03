from medallion.views.users import get_db_password_from_request


class TestUsers:
    def test_get_db_password_from_request_password_hash(self):
        body = {
            "_id": "testuser",
            "password_hash": "hashed_password_123"
        }

        password_hash = get_db_password_from_request(body)
        assert password_hash == "hashed_password_123"

    def test_get_db_password_from_request_password(self):
        body = {
            "_id": "testuser",
            "password": "plain_password_123"
        }

        password_hash = get_db_password_from_request(body)
        assert password_hash.startswith("scrypt:32768:8:1$")
