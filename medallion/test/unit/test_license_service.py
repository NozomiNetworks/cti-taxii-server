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
