from copy import deepcopy
from unittest.mock import MagicMock

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from medallion.filters.mongodb_next_gen_filter import MongoDBNextGenFilter


class TestMongoDBNextGenFilter:

    def test_process_objects_next_gen_filter_specific_version(self):
        mongodb_nextgen_fiter = self.get_mongodb_nextgen_fiter_with_mocks(
            filter_args={"match[version]": "2017-01-27T13:49:53.935Z"},
            basic_filter={},
            allowed=("version",),
            api_root_db=MagicMock(),
            record={"limit": 10, "next": None}
        )

        mongodb_nextgen_fiter.process_objects_next_gen_filter(("version",))
        mongodb_nextgen_fiter._get_specific_version_objects_next.assert_called_once_with({})
        mongodb_nextgen_fiter._get_combined_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_first_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_last_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_all_objects_next.assert_not_called()

    def test_process_objects_next_gen_filter_all(self):
        mongodb_nextgen_fiter = self.get_mongodb_nextgen_fiter_with_mocks(
            filter_args={"match[version]": "all"},
            basic_filter={},
            allowed=("version",),
            api_root_db=MagicMock(),
            record={"limit": 10, "next": None}
        )

        mongodb_nextgen_fiter.process_objects_next_gen_filter(("version",))
        mongodb_nextgen_fiter._get_all_objects_next.assert_called_once_with({})
        mongodb_nextgen_fiter._get_specific_version_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_combined_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_first_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_last_objects_next.assert_not_called()

    def test_process_objects_next_gen_filter_all_no_supported(self):
        mongodb_nextgen_fiter = self.get_mongodb_nextgen_fiter_with_mocks(
            filter_args={},
            basic_filter={},
            allowed=(),
            api_root_db=MagicMock(),
            record={"limit": 10, "next": None}
        )

        mongodb_nextgen_fiter.process_objects_next_gen_filter(("not_supported",))
        mongodb_nextgen_fiter._get_all_objects_next.assert_called_once_with({})
        mongodb_nextgen_fiter._get_specific_version_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_combined_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_first_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_last_objects_next.assert_not_called()

    def test_process_objects_next_gen_filter_last(self):
        mongodb_nextgen_fiter = self.get_mongodb_nextgen_fiter_with_mocks(
            filter_args={},
            basic_filter={},
            allowed=("version",),
            api_root_db=MagicMock(),
            record={"limit": 10, "next": None}
        )

        mongodb_nextgen_fiter.process_objects_next_gen_filter(("version",))
        mongodb_nextgen_fiter._get_last_objects_next.assert_called_once_with({})
        mongodb_nextgen_fiter._get_specific_version_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_combined_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_first_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_all_objects_next.assert_not_called()

    def test_process_objects_next_gen_filter_last_default(self):
        mongodb_nextgen_fiter = self.get_mongodb_nextgen_fiter_with_mocks(
            filter_args={"match[version]": "last"},
            basic_filter={},
            allowed=("version",),
            api_root_db=MagicMock(),
            record={"limit": 10, "next": None}
        )

        mongodb_nextgen_fiter.process_objects_next_gen_filter(("version",))
        mongodb_nextgen_fiter._get_last_objects_next.assert_called_once_with({})
        mongodb_nextgen_fiter._get_specific_version_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_combined_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_first_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_all_objects_next.assert_not_called()

    def test_process_objects_next_gen_filter_first(self):
        mongodb_nextgen_fiter = self.get_mongodb_nextgen_fiter_with_mocks(
            filter_args={"match[version]": "first"},
            basic_filter={},
            allowed=("version",),
            api_root_db=MagicMock(),
            record={"limit": 10, "next": None}
        )

        mongodb_nextgen_fiter.process_objects_next_gen_filter(("version",))
        mongodb_nextgen_fiter._get_first_objects_next.assert_called_once_with({})
        mongodb_nextgen_fiter._get_specific_version_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_combined_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_last_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_all_objects_next.assert_not_called()

    def test_process_objects_next_gen_filter_combined(self):
        mongodb_nextgen_fiter = self.get_mongodb_nextgen_fiter_with_mocks(
            filter_args={"match[version]": "2017-01-27T13:49:53.935Z,2018-02-28T10:30:00.000Z"},
            basic_filter={},
            allowed=("version",),
            api_root_db=MagicMock(),
            record={"limit": 10, "next": None}
        )

        mongodb_nextgen_fiter.process_objects_next_gen_filter(("version",))
        mongodb_nextgen_fiter._get_specific_version_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_first_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_last_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_all_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_combined_objects_next.assert_called_once_with({})

        mongodb_nextgen_fiter = self.get_mongodb_nextgen_fiter_with_mocks(
            filter_args={"match[version]": "2017-01-27T13:49:53.935Z,last"},
            basic_filter={},
            allowed=("version",),
            api_root_db=MagicMock(),
            record={"limit": 10, "next": None}
        )

        mongodb_nextgen_fiter.process_objects_next_gen_filter(("version",))
        mongodb_nextgen_fiter._get_specific_version_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_first_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_last_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_all_objects_next.assert_not_called()
        mongodb_nextgen_fiter._get_combined_objects_next.assert_called_once_with({})

    def get_mongodb_nextgen_fiter_with_mocks(self, **args: dict):
        f = MongoDBNextGenFilter(**args)
        f._get_specific_version_objects_next = MagicMock(return_value=[])
        f._get_combined_objects_next = MagicMock(return_value=[])
        f._get_first_objects_next = MagicMock(return_value=[])
        f._get_last_objects_next = MagicMock(return_value=[])
        f._get_all_objects_next = MagicMock(return_value=[])

        return f


class TestMongoDBNextGenFilterSortDirection:
    """Test suite for _get_sort_direction() method."""

    def test_get_sort_direction_none_returns_ascending(self):
        """Test that None sort_value defaults to ASCENDING."""
        result = MongoDBNextGenFilter._get_sort_direction(None)
        assert result == ASCENDING

    def test_get_sort_direction_asc_lowercase(self):
        """Test that 'asc' returns ASCENDING."""
        result = MongoDBNextGenFilter._get_sort_direction("asc")
        assert result == ASCENDING

    def test_get_sort_direction_asc_uppercase(self):
        """Test that 'ASC' (uppercase) returns ASCENDING."""
        result = MongoDBNextGenFilter._get_sort_direction("ASC")
        assert result == ASCENDING

    def test_get_sort_direction_asc_mixed_case(self):
        """Test that 'Asc' (mixed case) returns ASCENDING."""
        result = MongoDBNextGenFilter._get_sort_direction("Asc")
        assert result == ASCENDING

    def test_get_sort_direction_desc_lowercase(self):
        """Test that 'desc' returns DESCENDING."""
        result = MongoDBNextGenFilter._get_sort_direction("desc")
        assert result == DESCENDING

    def test_get_sort_direction_desc_uppercase(self):
        """Test that 'DESC' (uppercase) returns DESCENDING."""
        result = MongoDBNextGenFilter._get_sort_direction("DESC")
        assert result == DESCENDING

    def test_get_sort_direction_desc_mixed_case(self):
        """Test that 'Desc' (mixed case) returns DESCENDING."""
        result = MongoDBNextGenFilter._get_sort_direction("Desc")
        assert result == DESCENDING

    def test_get_sort_direction_invalid_value_returns_ascending(self):
        """Test that invalid sort_value falls back to ASCENDING."""
        result = MongoDBNextGenFilter._get_sort_direction("invalid")
        assert result == ASCENDING

    def test_get_sort_direction_empty_string_returns_ascending(self):
        """Test that empty string falls back to ASCENDING."""
        result = MongoDBNextGenFilter._get_sort_direction("")
        assert result == ASCENDING

    def test_get_sort_direction_random_string_returns_ascending(self):
        """Test that random string falls back to ASCENDING."""
        result = MongoDBNextGenFilter._get_sort_direction("random_value")
        assert result == ASCENDING


class TestMongoDBNextGenFilterNextPaginationFallback:

    def test_fallback_preserves_existing_added_after_for_ascending(self):
        next_id = ObjectId()
        query_pipelines = []
        batches = [
            [{"_id": next_id, "_manifest": {"date_added": "2024-01-03T00:00:00.000Z"}}],
            [{"_id": ObjectId(), "_manifest": {"date_added": "2024-01-04T00:00:00.000Z"}}],
        ]

        api_root_db = MagicMock()

        class _QueryResult:
            def __init__(self, docs):
                self.docs = docs

            def limit(self, _):
                return self.docs

        def find_side_effect(pipeline, sort):
            query_pipelines.append(deepcopy(pipeline))
            return _QueryResult(batches[len(query_pipelines) - 1])

        api_root_db.objects.find.side_effect = find_side_effect

        mongodb_nextgen_filter = MongoDBNextGenFilter(
            filter_args={"sort": "asc"},
            basic_filter={},
            allowed=(),
            api_root_db=api_root_db,
            record={"limit": 1, "next": ("2024-01-03T00:00:00.000Z", str(next_id))},
        )
        mongodb_nextgen_filter.oversampling_factor = 2

        pipeline = {"_manifest.date_added": {"$gt": "2024-01-01T00:00:00.000Z"}}
        results = mongodb_nextgen_filter._get_sorted_results_with_next_limit_on_objects(pipeline, 1)

        assert results == batches[1]
        assert query_pipelines[0]["_manifest.date_added"] == {
            "$gt": "2024-01-01T00:00:00.000Z",
            "$gte": "2024-01-03T00:00:00.000Z",
        }
        assert query_pipelines[1]["_manifest.date_added"] == {
            "$gt": "2024-01-01T00:00:00.000Z",
            "$gte": "2024-01-03T00:00:00.000Z",
        }

    def test_fallback_preserves_existing_added_after_for_descending(self):
        next_id = ObjectId()
        query_pipelines = []
        batches = [
            [{"_id": next_id, "_manifest": {"date_added": "2024-01-03T00:00:00.000Z"}}],
            [{"_id": ObjectId(), "_manifest": {"date_added": "2024-01-02T00:00:00.000Z"}}],
        ]

        api_root_db = MagicMock()

        class _QueryResult:
            def __init__(self, docs):
                self.docs = docs

            def limit(self, _):
                return self.docs

        def find_side_effect(pipeline, sort):
            query_pipelines.append(deepcopy(pipeline))
            return _QueryResult(batches[len(query_pipelines) - 1])

        api_root_db.objects.find.side_effect = find_side_effect

        mongodb_nextgen_filter = MongoDBNextGenFilter(
            filter_args={"sort": "desc"},
            basic_filter={},
            allowed=(),
            api_root_db=api_root_db,
            record={"limit": 1, "next": ("2024-01-03T00:00:00.000Z", str(next_id))},
        )
        mongodb_nextgen_filter.oversampling_factor = 2

        pipeline = {"_manifest.date_added": {"$gt": "2024-01-01T00:00:00.000Z"}}
        results = mongodb_nextgen_filter._get_sorted_results_with_next_limit_on_objects(pipeline, 1)

        assert results == batches[1]
        assert query_pipelines[0]["_manifest.date_added"] == {
            "$gt": "2024-01-01T00:00:00.000Z",
            "$lte": "2024-01-03T00:00:00.000Z",
        }
        assert query_pipelines[1]["_manifest.date_added"] == {
            "$gt": "2024-01-01T00:00:00.000Z",
            "$lte": "2024-01-03T00:00:00.000Z",
        }
