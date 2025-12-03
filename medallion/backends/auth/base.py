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

    def get_all_users(self):
        """Return a list of all users."""
        raise NotImplementedError()

    def add_user(self, user_info: dict):
        """Add a new user to the backend."""
        raise NotImplementedError()

    def format_user_response(self, user) -> dict:
        return {
            "_id": user["_id"],
            "company_name": user.get("company_name"),
            "contact_name": user.get("contact_name"),
            "created": user.get("created"),
            "updated": user.get("updated"),
            "is_admin": user.get("is_admin"),
            "license": user.get("license"),
        }
