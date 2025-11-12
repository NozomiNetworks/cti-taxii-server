from bson import ObjectId
from pymongo.synchronous.database import Database

from .mongodb_filter import MongoDBFilter
from ..common import string_to_datetime, datetime_to_float


class MongoDBNextGenFilter(MongoDBFilter):

    def __init__(self, filter_args, basic_filter, allowed: tuple[str], api_root_db: Database, record: dict = None):
        super(MongoDBNextGenFilter, self).__init__(filter_args, basic_filter, allowed, record)
        self.basic_filter = basic_filter
        self.full_query = self._query_parameters(allowed)
        self.api_root_db = api_root_db
        self.oversampling_factor = 5
        self.limit = record["limit"]
        self.next = record.get("next")

    def process_objects_next_gen_filter(self, allowed: tuple[str]) -> tuple[list[dict], str | None]:
        # Basic filter pipeline with id, type, added_after, spec_version
        # collection_id is part of the basic filter
        pipeline = self.full_query

        # retrieve version filter
        match_version = self._get_match_version_from_filter(allowed)

        if match_version is None or "all" in match_version:
            results, _next = self._get_all_objects_next(pipeline)

        elif "last" in match_version:
            results, _next = self._get_last_objects_next(pipeline)

        elif "first" in match_version:
            results, _next = self._get_first_objects_next(pipeline)

        elif "," in match_version:
            # Combined filters
            results, _next = self._get_combined_objects_next(pipeline)
        else:
            # Specific version provided
            results, _next = self._get_specific_version_objects_next(pipeline, match_version)

        results.sort(key=lambda x: x["_manifest"]["date_added"])
        return results, str(_next) if _next else None

    def _get_match_version_from_filter(self, allowed) -> str | None:
        if "version" not in allowed:
            return None

        if (match_version := self.filter_args.get("match[version]")) is None:
            return "last"

        if "all" in match_version:
            return "all"

        return match_version

    def _get_all_objects_next(self, pipeline: dict) -> tuple[list[dict], str | None]:
        results = self._get_sorted_results_with_next_limit_on_objects(pipeline, self.limit + 1)
        return results[:-1], results[-1]["_id"] if len(results) > self.limit else None

    def _get_specific_version_objects_next(self, pipeline: dict, version: str) -> tuple[list[dict], str | None]:
        # Not sure if comparing datetime as float is the best way maybe we should compare with an interval
        pipeline.update({"_manifest.version": {"$eq": datetime_to_float(string_to_datetime(version))}})

        results = self._get_sorted_results_with_next_limit_on_objects(pipeline, self.limit + 1)
        if len(results) > self.limit:
            return results[:-1], results[-1]["_id"]

        return results, None

    def _get_last_objects_next(self, pipeline: dict) -> tuple[list[dict], str | None]:
        return self._get_oversampled_objects_next(pipeline, "latest_version")

    def _get_first_objects_next(self, pipeline: dict) -> tuple[list[dict], str | None]:
        return self._get_oversampled_objects_next(pipeline, "earliest_version")

    def _get_oversampled_objects_next(self, pipeline: dict, cache_field: str) -> tuple[list[dict], str | None]:
        results = []

        while len(results) < self.limit + 1:
            # 1. Fetch batch: pageSize × OVERSAMPLING_FACTOR documents (sorted by _id)
            temp_results = self._get_sorted_results_with_next_limit_on_objects(
                pipeline,
                self.limit * self.oversampling_factor,
            )

            if self._are_cache_objects_are_finished(temp_results):
                break

            # 3. Bulk query cache for latest/earliest versions
            query_conditions = [
                {
                    "id": obj["id"],
                    cache_field: obj["_manifest"]["version"],
                    "last_spec": obj["_manifest"]["media_type"]
                }
                for obj in temp_results
            ]

            matching_docs = self.api_root_db.objects_version_cache.find({"$or": query_conditions})
            matching_tuples = {(doc["id"], doc["last_spec"], doc[cache_field]) for doc in matching_docs}

            # 4. Filter: keep only docs where doc._version == cache.latest_version
            results.extend(
                [
                    temp_result for temp_result in temp_results
                    if (temp_result["id"], temp_result["_manifest"]["media_type"],
                        temp_result["_manifest"]["version"]) in matching_tuples
                ]
            )

            # 5. Update cursor to last _id seen
            self.next = str(temp_results[-1]["_id"])

        results = sorted(results, key=lambda x: x["_manifest"]["date_added"])
        return results[:self.limit], results[self.limit]["_id"] if len(results) > self.limit else None

    def _get_combined_objects_next(self, pipeline: dict) -> tuple[list[dict], str | None]:
        match_version = self.filter_args.get("match[version]")
        version_dates = [
            datetime_to_float(string_to_datetime(x))
            for x in match_version.split(",") if (x != "first" and x != "last")
        ]

        if version_dates:
            pipeline.update({"versions": {"$in": version_dates}})

        results = []

        while len(results) < self.limit + 1:
            # 1. Fetch batch: pageSize × OVERSAMPLING_FACTOR documents (sorted by _id)
            temp_results = self._get_sorted_results_with_next_limit_on_objects(
                pipeline,
                self.limit * self.oversampling_factor,
            )

            if self._are_cache_objects_are_finished(temp_results):
                break

            # 3. Bulk query cache for latest/earliest versions
            query_conditions = []
            for obj in temp_results:
                query = {
                    "id": obj["id"],
                    "last_spec": obj["_manifest"]["media_type"],
                }

                if "last" in match_version:
                    query["latest_version"] = obj["_manifest"]["version"]

                if "first" in match_version:
                    query["earliest_version"] = obj["_manifest"]["version"]

                query_conditions.append(query)

            matching_docs = self.api_root_db.objects_version_cache.find({"$or": query_conditions})

            matching_tuples = set()
            for doc in matching_docs:
                t = [doc["id"], doc["last_spec"], ]
                if "latest_version" in match_version:
                    t.append(doc["latest_version"])
                if "first" in match_version:
                    t.append(doc["earliest_version"])

                matching_tuples.add(tuple(t))

                # 4. Filter: keep only docs where doc._version == cache.latest_version or earliest_version
            results.extend(
                [
                    temp_result for temp_result in temp_results
                    if self._create_comparison_tuple(temp_result, match_version) in matching_tuples
                ]
            )

            # 5. Update cursor to last _id seen
            self.next = str(temp_results[-1]["_id"])

        results = sorted(results, key=lambda x: x["_manifest"]["date"])
        return results[:self.limit], results[self.limit]["_id"] if len(results) > self.limit else None

    def _create_comparison_tuple(self, obj: dict, match_version: str) -> tuple:
        t = [obj["id"], obj["_manifest"]["media_type"], ]
        if "last" in match_version:
            t.append(obj["_manifest"]["version"])
        if "first" in match_version:
            t.append(obj["_manifest"]["version"])
        return tuple(t)

    def _are_cache_objects_are_finished(self, temp_results: list[dict]) -> bool:
        return len(temp_results) == 1 and temp_results[0]["_id"] == ObjectId(self.next)

    def _get_sorted_results_with_next_limit_on_objects(self, pipeline: dict, limit: int) -> list[dict]:
        self._append_next_if_exists(pipeline)
        results = list(self.api_root_db.objects.find(pipeline).sort({"_id": 1}).limit(limit))
        return results

    def _append_next_if_exists(self, pipeline: dict):
        if self.next:
            pipeline.update({"_id": {"$gte": ObjectId(self.next)}})
