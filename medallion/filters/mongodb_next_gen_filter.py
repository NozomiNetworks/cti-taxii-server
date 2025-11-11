from bson import ObjectId
from pymongo.synchronous.database import Database

from .mongodb_filter import MongoDBFilter
from ..common import string_to_datetime, datetime_to_float


class MongoDBNextGenFilter(MongoDBFilter):

    def __init__(self, filter_args, basic_filter, allowed: tuple[str], api_root_db: Database, record: dict = None):
        super(MongoDBNextGenFilter, self).__init__(filter_args, basic_filter, allowed, record)
        self.basic_filter = basic_filter
        self.full_query = self._query_parameters(allowed)
        self.record = record
        self.api_root_db = api_root_db

    def process_next_gen_filter(self, allowed: tuple[str], manifest_info: str) -> tuple[list[dict], str | None]:
        if manifest_info != "objects":
            # Define what to do for manifests
            return [], None

        # Basic filter pipeline with id, type, added_after, spec_version
        # collection_id is part of the basic filter
        pipeline = self.full_query

        # retrieve version filter
        match_version = self._get_match_version_from_filter(allowed)

        if match_version is None:
            # Check if version is not supported
            pass

        elif "all" in match_version:
            results, _next = self._get_all_objects_next(pipeline)

        elif "last" in match_version:
            results, _next = self._get_last_objects_next(pipeline)

        elif "first" in match_version:
            results, _next = self._get_first_objects_next(pipeline)

        elif "," in match_version:
            # Combined filters
            pass
        else:
            # Specific version provided
            results, _next = self._get_specific_version_objects_next(pipeline, match_version)

        return results, str(_next)

    def _get_match_version_from_filter(self, allowed) -> str | None:
        if "version" not in allowed:
            return None

        if (match_version := self.filter_args.get("match[version]")) is None:
            return "last"

        if "all" in match_version:
            return "all"

        return match_version

    def _get_all_objects_next(self, pipeline: dict) -> tuple[list[dict], str | None]:
        limit = self.record["limit"]
        results = self._get_sorted_results_with_next_limit_on_objects(pipeline, limit + 1)
        return results[:-1], results[-1]["_id"] if len(results) > limit else None

    def _get_specific_version_objects_next(self, pipeline: dict, version: str) -> tuple[list[dict], str | None]:
        # Not sure if comparing datetime as float is the best way maybe we should compare with an interval
        pipeline.update({"_manifest.version": {"$eq": datetime_to_float(string_to_datetime(version))}})

        limit = self.record["limit"]
        results = self._get_sorted_results_with_next_limit_on_objects(pipeline, limit + 1)
        return results[:-1], results[-1]["_id"] if len(results) > limit else None

    def _get_last_objects_next(self, pipeline: dict) -> tuple[list[dict], str | None]:
        return self._get_oversampled_last_objects_next(pipeline, "latest_version")

    def _get_first_objects_next(self, pipeline: dict) -> tuple[list[dict], str | None]:
        return self._get_oversampled_last_objects_next(pipeline, "earliest_version")

    def _get_oversampled_last_objects_next(self, pipeline: dict, cache_field: str) -> tuple[list[dict], str | None]:
        limit = self.record["limit"]

        oversampling_factor = 5
        results = []

        while len(results) < limit + 1:
            # 1. Fetch batch: pageSize × OVERSAMPLING_FACTOR documents (sorted by _id)
            temp_results = self._get_sorted_results_with_next_limit_on_objects(
                pipeline,
                limit * oversampling_factor,
            )

            # 3. Bulk query cache for latest/earliest versions
            query_conditions = [
                {
                    "id": obj["id"],
                    cache_field: obj["_manifest"]["version"],
                    "last_spec": obj["_manifest"]["media_type"]
                }
                for obj in temp_results
            ]

            matching_docs_id = [
                doc["id"] for doc in
                self.api_root_db.objects_version_cache.find({
                    "$or": query_conditions
                })
            ]

            # 4. Filter: keep only docs where doc._version == cache.latest_version
            results.extend([temp_result for temp_result in temp_results if temp_result["id"] in matching_docs_id])

            # 5. Update cursor to last _id seen
            self.record["next"] = str(temp_results[-1]["_id"])

        return results[:limit], results[limit]["_id"] if len(results) > limit else None

    def _get_sorted_results_with_next_limit_on_objects(self, pipeline: dict, limit: int) -> list[dict]:
        self._append_next_if_exists(pipeline)
        results = list(self.api_root_db.objects.find(pipeline).sort({"_id": 1}).limit(limit))
        return results

    def _append_next_if_exists(self, pipeline: dict):
        if (_next := self.record.get("next")) is not None:
            pipeline.update({"_id": {"$gte": ObjectId(_next)}})
