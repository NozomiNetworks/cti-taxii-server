class LicenseService:
    _mandiant_license = "mandiant"
    _nozomi_license = "nozomi"

    @classmethod
    def can_user_read_collection(cls, user: dict | None, collection_license: str) -> bool:
        if user is None or (user_license := user.get("license")) is None:
            return False

        if user_license == cls._mandiant_license:
            return True

        return collection_license == user_license

    def strip_mandiant_from_output(cls, collection_info: dict) -> dict:
        pass
