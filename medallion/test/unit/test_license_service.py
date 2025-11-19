from medallion.license_service import LicenseService


class TestLicenseService:
    def test_can_user_read_collection(self):
        # Emtpy user
        assert LicenseService.can_user_read_collection(None, "nozomi") is False

        # User without license
        assert LicenseService.can_user_read_collection({}, "nozomi") is False

        # Nozomi user can read nozomi only
        nozomi_user = {"license": "nozomi"}
        assert LicenseService.can_user_read_collection(nozomi_user, "nozomi") is True
        assert LicenseService.can_user_read_collection(nozomi_user, "mandiant") is False

        # Mandiant user can read all
        mandiant_user = {"license": "mandiant"}
        assert LicenseService.can_user_read_collection(mandiant_user, "nozomi") is True
        assert LicenseService.can_user_read_collection(mandiant_user, "mandiant") is True

    def test_get_most_permissive_user_license(self):
        LicenseService._user_license_map = {
            LicenseService._mandiant_license: (LicenseService._nozomi_license, LicenseService._mandiant_license,),
            LicenseService._nozomi_license: (LicenseService._nozomi_license,),
        }
        most_permissive_license = LicenseService.get_most_permissive_user_license()
        assert most_permissive_license == LicenseService._mandiant_license

    def test_get_max_privileged_license(self):
        LicenseService._user_license_map = {
            LicenseService._mandiant_license: (LicenseService._nozomi_license, LicenseService._mandiant_license,),
            LicenseService._nozomi_license: (LicenseService._nozomi_license,),
        }
        max_license = LicenseService.get_max_privileged_license()
        assert max_license == (LicenseService._nozomi_license, LicenseService._mandiant_license,)

    def test_remove_not_licensed_collection_to_user(self):
        collections = [
            {"id": "1", "license": "nozomi"},
            {"id": "2", "license": "mandiant"},
        ]

        # Nozomi user
        nozomi_user = "nozomi"
        filtered_collections = LicenseService.remove_not_licensed_collection_to_user(nozomi_user, collections)
        assert len(filtered_collections) == 1
        assert filtered_collections[0]["id"] == "1"

        # Mandiant user
        collections = [
            {"id": "1", "license": "nozomi"},
            {"id": "2", "license": "mandiant"},
            {"id": "3", "license": "ibm"},
        ]
        mandiant_user = "mandiant"
        filtered_collections = LicenseService.remove_not_licensed_collection_to_user(mandiant_user, collections)
        assert len(filtered_collections) == 2
