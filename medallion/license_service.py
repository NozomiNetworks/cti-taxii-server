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

        return cls.can_user_license_read_collection(user_license, collection_license)

    @classmethod
    def remove_not_licensed_collection_to_user(cls, current_user_license, collections: list[dict]) -> list[dict]:
        licensed_collections = []
        for collection in collections:
            if not cls.can_user_license_read_collection(current_user_license, collection.get("license", "")):
                continue

            del collection["license"]
            licensed_collections.append(collection)

        return licensed_collections

    @classmethod
    def can_user_license_read_collection(cls, user_license: str, collection_license: str) -> bool:
        return collection_license in cls._user_license_map[user_license]

    @classmethod
    def get_most_permissive_user_license(cls) -> str | None:
        return max(cls._user_license_map, key=lambda k: len(cls._user_license_map[k]))

    @classmethod
    def get_max_privileged_license(cls) -> str:
        return cls._user_license_map[cls.get_most_permissive_user_license()]
