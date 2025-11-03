from typing import Optional, List

from pymongo.synchronous.database import Database

from medallion.common import cast_filter_match_version_to_dates


class MongoDBResultCounter:
    def __init__(self, database: Database):
        self.database = database

    def get_count_by_current_filters(
            self,
            match_version: Optional[str],
            collection_id: str,
            pipeline: List[dict],
            unwind: bool
    ):
        # If filters are not specified, then returns the count of all manifests (i.e., first versions)
        if not match_version:
            return self.count_first_or_last(collection_id)

        # If all versions are requested, then return the count of all objects in the collection
        if "all" in match_version:
            return self.count_all_objects_in_collection(collection_id)

        actual_dates = cast_filter_match_version_to_dates(match_version)
        request_first = "first" in match_version
        request_last = "last" in match_version

        # If no specific dates are requested, check if first and/or last versions are requested
        if len(actual_dates) == 0:
            if request_first and request_last:
                return self.count_first_and_last(collection_id)
            else:
                return self.count_first_or_last(collection_id)

        # When specific dates are requested along with first and/or last versions, fall back to the old counting method
        if request_first or request_last:
            return self.old_count(pipeline, unwind)

        # Otherwise, count the specific dates requested
        return self.count_specific_dates(collection_id, actual_dates)

    def count_all_objects_in_collection(self, collection_id: str) -> int:
        return self.database.objects.count_documents({"_collection_id": collection_id})

    def count_first_or_last(self, collection_id: str) -> int:
        return self.database.manifests.count_documents({"_collection_id": collection_id})

    def count_first_and_last(self, collection_id: str) -> int:
        return self.database.manifests.aggregate(
            [
                {"$match": {"_collection_id": collection_id}},
                {
                    "$group": {
                        "_id": None,
                        "total_count": {
                            "$sum": {
                                "$cond": [{"$eq": [{"$size": "$versions"}, 1]}, 1, 2]
                            }
                        }
                    }
                },
                {
                    "$project": {"total_count": 1, "_id": 0}
                }
            ]
        )

    def count_specific_dates(self, collection_id: str, actual_dates: List[float]) -> int:
        return self.database.objects.count_documents(
            {
                "$and": [
                    {"_collection_id": collection_id},
                    {
                        "$or": [
                            {"modified": {"$in": actual_dates}},
                            {"$and": [
                                {"created": {"$in": actual_dates}},
                                {"modified": {"$exists": False}}
                            ]}
                        ]
                    }
                ]
            }
        )

    def old_count(self, pipeline: List[dict], unwind: bool) -> int:
        count_pipeline = list(pipeline)
        if unwind:
            count_pipeline.append({"$unwind": "$versions"})
        count_pipeline.append({"$count": "total_count"})
        count_result = list(self.database.manifests.aggregate(count_pipeline))

        if len(count_result) == 0:
            # No results
            return 0

        count = count_result[0]["total_count"]
        return count
