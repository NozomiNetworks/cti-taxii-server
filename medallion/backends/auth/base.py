from medallion.license_service import LicenseService


class AuthBackend(object):

    def get_password_hash(self, username):
        """Given a username provide the password hash for verification."""
        raise NotImplementedError()

    def get_username_for_api_key(self, api_key):
        """Given an API key provide the username for verification."""
        raise NotImplementedError()

    def get_user_by_username(self, username):
        """Given a username provide the user object."""
        raise NotImplementedError()

    def can_user_read_collection(self, username: str, collection_license: str) -> bool:
        return LicenseService.can_user_read_collection(self.get_user_by_username(username), collection_license)
