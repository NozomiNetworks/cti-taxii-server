from flask import current_app


class TaxiiConfigManager:
    def __init__(self):
        self._current_taxii_config = current_app.taxii_config
        self._collections = self._current_taxii_config.get("collections", {})

    def get_mandiant_collection_id(self) -> str:
        return self._collections.get("mandiant", {}).get("id")

    def get_nozomi_networks_collection_id(self) -> str:
        return self._collections.get("nozomi_networks", {}).get("id")
