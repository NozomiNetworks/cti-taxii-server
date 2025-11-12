from bson import ObjectId
from pymongo.synchronous.database import Database

from ..common import datetime_to_float, string_to_datetime
from .mongodb_filter import MongoDBFilter


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

        elif "last" == match_version:
            results, _next = self._get_last_objects_next(pipeline)

        elif "first" == match_version:
            results, _next = self._get_first_objects_next(pipeline)

        elif "," in match_version:
            results, _next = self._get_combined_objects_next(pipeline)

        else:
            results, _next = self._get_specific_version_objects_next(pipeline, match_version)

        # Sort the results, which may be out of order due to sorting by _id
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
        """Get all versions of each object."""
        results = self._get_sorted_results_with_next_limit_on_objects(pipeline, self.limit + 1)
        return results[:-1], results[-1]["_id"] if len(results) > self.limit else None

    def _get_specific_version_objects_next(self, pipeline: dict, version: str) -> tuple[list[dict], str | None]:
        """Get only the specific version of each object."""
        pipeline.update({"_manifest.version": {"$eq": datetime_to_float(string_to_datetime(version))}})

        results = self._get_sorted_results_with_next_limit_on_objects(pipeline, self.limit + 1)
        if len(results) > self.limit:
            return results[:-1], results[-1]["_id"]

        return results, None

    def _get_last_objects_next(self, pipeline: dict) -> tuple[list[dict], str | None]:
        """Get only the last versions of each object."""
        return self._get_combined_objects_next(pipeline)

    def _get_first_objects_next(self, pipeline: dict) -> tuple[list[dict], str | None]:
        """Get only the first versions of each object."""
        return self._get_combined_objects_next(pipeline)

    def _get_combined_objects_next(self, pipeline: dict) -> tuple[list[dict], str | None]:
        """Oversampling searches with multiple filters."""
        match_version = self.filter_args.get("match[version]", "last")
        version_dates = [
            datetime_to_float(string_to_datetime(x))
            for x in match_version.split(",") if (x != "first" and x != "last")
        ]

        if version_dates:
            pipeline.update({"versions": {"$in": version_dates}})

        results = []
        suffix = self._get_suffix_by_match_filters()

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
                query = {"id": obj["id"]}
                query_conditions.append(query)

            # 4. Filter: keep only docs where doc._version == cache.latest_version
            # The filter takes in consideration the media type searched.
            # If none or both is specified instead, it takes the most recent (2.1 and eventually 2.0)
            matching_docs = self.api_root_db.objects_version_cache.find({"$or": query_conditions})
            matching_tuples = set()
            if not suffix or suffix == "_2_0_2_1":
                for doc in matching_docs:
                    if "last" in match_version:
                        matching_tuples.add((doc["id"], doc.get("latest_version_2_1") or doc.get("latest_version_2_0"),))
                    if "first" in match_version:
                        matching_tuples.add((doc["id"], doc.get("earliest_version_2_1") or doc.get("earliest_version_2_0"),))
            elif suffix in ("_2_0", "_2_1"):
                for doc in matching_docs:
                    t = [doc["id"]]
                    if "last" in match_version:
                        t.append(doc[f"latest_version{suffix}"])
                    if "first" in match_version:
                        t.append(doc[f"earliest_version{suffix}"])

                    matching_tuples.add(tuple(t))

            # 4. Filter: keep only docs where doc._version == cache.latest_version or earliest_version
            results.extend(
                [
                    temp_result for temp_result in temp_results
                    if (temp_result["id"], temp_result["_manifest"]["version"]) in matching_tuples
                ]
            )

            # 5. Update cursor to last _id seen
            self.next = str(temp_results[-1]["_id"])

        results = sorted(results, key=lambda x: x["_manifest"]["date_added"])
        return results[:self.limit], results[self.limit]["_id"] if len(results) > self.limit else None

    def _get_suffix_by_match_filters(self) -> str:
        """Given the media_type filters, returns the suffix for the correct field in cache.

        If the media_type are 2.0 and 2.1, then the query is an $in statement.
        Otherwise, it is an $eq statement.
        """
        suffix = ""
        if '_manifest.media_type' in self.full_query:
            if "$in" in self.full_query['_manifest.media_type']:
                suffix = "_2_0_2_1"
            elif self.full_query['_manifest.media_type']['$eq'] == 'application/stix+json;version=2.0':
                suffix = "_2_0"
            else:
                suffix = "_2_1"
        return suffix

    def _are_cache_objects_are_finished(self, temp_results: list[dict]) -> bool:
        return len(temp_results) == 1 and temp_results[0]["_id"] == ObjectId(self.next)

    def _get_sorted_results_with_next_limit_on_objects(self, pipeline: dict, limit: int) -> list[dict]:
        """Get sorted results by _id with next and limit on objects collection.

        This is the basic method to retrieve the results from the objects collection.
        """
        self._append_next_if_exists(pipeline)
        results = list(self.api_root_db.objects.find(pipeline).sort({"_id": 1}).limit(limit))
        return results

    def _append_next_if_exists(self, pipeline: dict):
        """Append the next parameter to the pipeline if it exists."""
        if self.next:
            pipeline.update({"_id": {"$gte": ObjectId(self.next)}})
