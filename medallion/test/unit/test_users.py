from medallion.views.users import (
    get_db_password_from_request, obfuscate_username
)


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

    def test_obfuscate_username_email(self):
        assert obfuscate_username("matteo.corradini@gmail.com") == "m*****i@gmail.com"

    def test_obfuscate_username_plain_username(self):
        assert obfuscate_username("nozominetworks") == "n*****s"

    def test_obfuscate_username_short_value(self):
        # Values too short to obfuscate are returned unchanged.
        assert obfuscate_username("a") == "a"
        assert obfuscate_username("") == ""
