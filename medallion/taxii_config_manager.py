from flask import current_app


class TaxiiConfigManager:
    def __init__(self):
        self._current_taxii_config = current_app.taxii_config
        self._custom_collections = self._current_taxii_config.get("custom_collections", {})

    def get_mandiant_collection_id(self) -> str:
        return self._custom_collections.get("mandiant", {}).get("id")

    def get_nozomi_networks_collection_id(self) -> str:
        return self._custom_collections.get("nozomi_networks", {}).get("id")
