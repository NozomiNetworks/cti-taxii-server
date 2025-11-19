class LicenseService:
    _mandiant_license = "mandiant"
    _nozomi_license = "nozomi"

    _user_license_map = {
        _mandiant_license: (_nozomi_license, _mandiant_license,),
        _nozomi_license: (_nozomi_license,),
    }

    @classmethod
    def can_user_read_collection(cls, user: dict | None, collection_license: str) -> bool:
        if user is None or (user_license := user.get("license")) is None:
            return False

        return collection_license in cls._user_license_map[user_license]

    def strip_mandiant_from_output(cls, collection_info: dict) -> dict:
        pass
