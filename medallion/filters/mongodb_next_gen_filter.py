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
        self.limit = record.get("limit")
        self.next = record.get("next")

    def process_manifests_next_gen_filter(self, allowed: tuple[str]) -> tuple[list[dict], tuple[str, str] | None]:
        results, _next = self._process_objects_next_gen_filter_raw(allowed)

        return [r["_manifest"] for r in results], _next

    def process_objects_next_gen_filter(self, allowed: tuple[str]) -> tuple[list[dict], tuple[str, str] | None]:
        results, _next = self._process_objects_next_gen_filter_raw(allowed)

        self._remove_id(results)

        return results, _next

    def _process_objects_next_gen_filter_raw(self, allowed: tuple[str]) -> tuple[list[dict], tuple[str, str] | None]:
        # Basic filter pipeline with id, type, added_after, spec_version
        # collection_id is part of the basic filter
        pipeline = self.full_query

        # retrieve version filter
        match_version = self._get_match_version_from_filter(allowed)

        if match_version is None or "all" in match_version:
            results = self._get_all_objects_next(pipeline)

        elif "last" == match_version:
            results = self._get_last_objects_next(pipeline)

        elif "first" == match_version:
            results = self._get_first_objects_next(pipeline)

        elif "," in match_version:
            results = self._get_combined_objects_next(pipeline)

        else:
            results = self._get_specific_version_objects_next(pipeline)

        if self.limit is None:
            return results, None

        if len(results) > self.limit:
            limited_results = results[:self.limit]
            last_returned_item = limited_results[-1]
            return limited_results, (last_returned_item["_manifest"]["date_added"], str(last_returned_item["_id"]))

        return results, None

    @staticmethod
    def _remove_id(results: list[dict]):
        for res in results:
            del res["_id"]

    def _get_match_version_from_filter(self, allowed) -> str | None:
        if "version" not in allowed:
            return None

        if (match_version := self.filter_args.get("match[version]")) is None:
            return "last"

        if "all" in match_version:
            return "all"

        return match_version

    def _get_all_objects_next(self, pipeline: dict) -> list[dict]:
        """Get all versions of each object."""
        return self._get_combined_objects_next(pipeline)

    def _get_specific_version_objects_next(self, pipeline: dict) -> list[dict]:
        """Get only the specific version of each object."""
        return self._get_combined_objects_next(pipeline)

    def _get_last_objects_next(self, pipeline: dict) -> list[dict]:
        """Get only the last versions of each object."""
        return self._get_combined_objects_next(pipeline)

    def _get_first_objects_next(self, pipeline: dict) -> list[dict]:
        """Get only the first versions of each object."""
        return self._get_combined_objects_next(pipeline)

    def _get_combined_objects_next(self, pipeline: dict) -> list[dict]:
        """Oversampling searches with multiple filters."""
        match_version = self.filter_args.get("match[version]", "last")
        self._update_pipeline_with_version_dates(pipeline, match_version)

        results = []
        suffix = self._get_suffix_by_match_filters()

        while self.limit is None or (len(results) < self.limit + 1):
            # 1. Fetch batch: pageSize × OVERSAMPLING_FACTOR documents (sorted by _id)
            limit = self.limit * self.oversampling_factor if self.limit is not None else 500
            temp_results = self._get_sorted_results_with_next_limit_on_objects(pipeline, limit)

            if self._are_cache_objects_finished(temp_results):
                break

            # 3. Bulk query cache for latest/earliest versions
            query_conditions = [{"id": obj["id"]} for obj in temp_results]

            # 4. Filter: keep only docs where doc._version == cache.latest_version
            matching_docs = list(self.api_root_db.objects_version_cache.find({"$or": query_conditions}))
            matching_tuples = self._generate_matching_tuple(suffix, match_version, temp_results, matching_docs)

            # 4. Filter: keep only docs where doc._version == cache.latest_version or earliest_version
            results.extend(
                [
                    temp_result for temp_result in temp_results
                    if (temp_result["id"], temp_result["_manifest"]["version"]) in matching_tuples
                ]
            )

            # 5. Update cursor to last _id seen
            self.next = (temp_results[-1]["_manifest"]["date_added"], temp_results[-1]["_id"])

        return sorted(results, key=lambda x: x["_manifest"]["date_added"])

    @staticmethod
    def _update_pipeline_with_version_dates(pipeline: dict, match_version: str):
        """Update the pipeline with version dates based on match_version.

        If the match_version contains the "all" string, no version filtering is applied.
        Otherwise, the pipeline is updated to include the specified version dates converted to float.
        """
        version_dates = [
            datetime_to_float(string_to_datetime(x))
            for x in match_version.split(",") if (x not in ("last", "first", "all",))
        ] if "all" not in match_version else []

        if version_dates:
            pipeline.update({"_manifest.version": {"$in": version_dates}})

    def _generate_matching_tuple(self, suffix: str, match_version: str, temp_results: list[dict], matching_docs: list[str]) -> set[tuple[str, str]]:
        """Get the matching tuples based on the match_version."""
        if "all" in match_version or "first" not in match_version and "last" not in match_version:
            return self._get_matching_tuple_for_all_match_version(suffix, temp_results, matching_docs)
        else:
            return self._get_matching_tuple_with_generic_match_version(suffix, match_version, matching_docs)

    @staticmethod
    def _get_matching_tuple_for_all_match_version(suffix: str, temp_results: list[dict], matching_docs: list[str]) -> set[tuple[str, str]]:
        """When the match version is 'all'

        - Take all versions if both 2.0 or 2.1 are specified, due to the filter is previously applied.
        - Take only the latest media_type if no spec is provided.
        """
        if suffix:
            matching_tuples = [
                (temp_result["id"], temp_result["_manifest"]["version"]) for temp_result in temp_results
            ]
        else:
            matching_tuples = [
                (temp_result["id"], temp_result["_manifest"]["version"])
                for temp_result in temp_results
                if temp_result["_manifest"]["media_type"] == next(obj for obj in matching_docs if obj["id"] == temp_result["id"])["last_spec"]
            ]
        return set(matching_tuples)

    @staticmethod
    def _get_matching_tuple_with_generic_match_version(suffix: str, match_version: str, matching_docs: list[str]) -> set[tuple[str, str]]:
        matching_tuples = set()

        # If both are specified, it takes the max/min value (2.1 and eventually 2.0)
        if suffix == "_2_0_2_1":
            for doc in matching_docs:
                if "last" in match_version:
                    latest_version_2_1 = doc.get("latest_version_2_1", 0)
                    latest_version_2_0 = doc.get("latest_version_2_0", 0)
                    matching_tuples.add((doc["id"], max(latest_version_2_1, latest_version_2_0),))

                if "first" in match_version:
                    earliest_version_2_1 = doc.get("earliest_version_2_1", float('inf'))
                    earliest_version_2_0 = doc.get("earliest_version_2_0", float('inf'))
                    matching_tuples.add((doc["id"], min(earliest_version_2_1, earliest_version_2_0),))
        # The filter takes in consideration the media type searched.
        elif suffix in ("_2_0", "_2_1"):
            for doc in matching_docs:
                t = [doc["id"]]
                if "last" in match_version:
                    t.append(doc[f"latest_version{suffix}"])
                if "first" in match_version:
                    t.append(doc[f"earliest_version{suffix}"])
                matching_tuples.add(tuple(t))
        # If None of them are specified, it takes whichever is available giving priority to 2.1.
        else:
            for doc in matching_docs:
                if "last" in match_version:
                    matching_tuples.add((doc["id"], doc.get("latest_version_2_1") or doc.get("latest_version_2_0"),))
                if "first" in match_version:
                    matching_tuples.add((doc["id"], doc.get("earliest_version_2_1") or doc.get("earliest_version_2_0"),))

        return matching_tuples

    def _get_suffix_by_match_filters(self) -> str:
        """Given the media_type filters, returns the suffix for the correct field in cache.

        If the media_type are 2.0 and 2.1, then the query is an $in statement.
        Otherwise, it is an $eq statement.
        """
        if '_manifest.media_type' not in self.full_query:
            return ""

        if "$in" in self.full_query['_manifest.media_type']:
            return "_2_0_2_1"
        elif self.full_query['_manifest.media_type']['$eq'] == 'application/stix+json;version=2.0':
            return "_2_0"
        else:
            return "_2_1"

    def _are_cache_objects_finished(self, temp_results: list[dict]) -> bool:
        return len(temp_results) == 0

    def _get_sorted_results_with_next_limit_on_objects(self, pipeline: dict, limit: int) -> list[dict]:
        """Get sorted results by date_added and _id with next and limit applied.

        This method handles the basic pagination request, and giving the filters in the pipeline it runs the query against objects collection.
        The pagination with _next is done based on two fields: date_added and _id.
        The _next filter only applied on date_added, and then the results are filtered in memory to return only those which appear later than _id.
        This solves the following issue:
        Given objects with the following id: A, B, C, D, but sorted by date_added as: A, C, B, D, a query with limit=2 first returns A and C.
        The next query with next=(date_added of C, C) should return B and D, but if we filter for both date_added and _id in the query, B would be skipped as
        its date_added is less than C.
        For this reason, we only filter by date_added in the query, and then filter by _id in memory to retrieve elements that come after the given _id.
        """
        if self.next:
            date_added, _id = self.next
            pipeline.update({"_manifest.date_added": {"$gte": date_added}})

        results = list(
            self.api_root_db.objects.find(
                pipeline,
                sort=[('_manifest.date_added', 1), ('_id', 1)],
                projection={"_collection_id": 0}
            ).limit(limit)
        )

        if self.next:
            for i, val in enumerate(results):
                if val["_id"] == ObjectId(_id):
                    # If the remaining_results is empty even if there are still results to paginate (the query returns the maximum number of results),
                    # it means the sampling window is not large enough to get new results, and it is returning the same items over and over.
                    if len(remaining_results := results[i + 1:]) == 0 and len(results) == limit:
                        del pipeline["_manifest.date_added"]
                        return self._get_sorted_results_with_next_limit_on_objects(pipeline, limit * self.oversampling_factor)

                    return remaining_results

        return results
