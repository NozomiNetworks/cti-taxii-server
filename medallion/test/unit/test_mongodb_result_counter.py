from unittest.mock import MagicMock

import pytest

from medallion.filters.mongodb_result_counter import MongoDBResultCounter


class TestMongoDBResultCounter:

    def test_old_count_with_unwind_no_results(self, mongodb_result_counter):
        mongodb_result_counter.database.manifests.aggregate.return_value = []
        assert mongodb_result_counter.old_count([{"simple": "filter"}], unwind=True) == 0
        mongodb_result_counter.database.manifests.aggregate.assert_called_once_with(
            [{"simple": "filter"}, {'$unwind': '$versions'}, {'$count': 'total_count'}]
        )

    def test_old_count_with_no_unwind_no_results(self, mongodb_result_counter):
        mongodb_result_counter.database.manifests.aggregate.return_value = []
        assert mongodb_result_counter.old_count([{"simple": "filter"}], False) == 0
        mongodb_result_counter.database.manifests.aggregate.assert_called_once_with(
            [{"simple": "filter"}, {'$count': 'total_count'}]
        )

    def test_old_count_with_unwind_with_results(self, mongodb_result_counter):
        mongodb_result_counter.database.manifests.aggregate.return_value = [{"total_count": 5}]
        assert mongodb_result_counter.old_count([{"simple": "filter"}], unwind=True) == 5

    def test_count_specific_dates(self, mongodb_result_counter):
        mongodb_result_counter.database.objects.count_documents.return_value = 10
        actual_dates = [123456789.0, 987654321.0]
        assert mongodb_result_counter.count_specific_dates("collection_id_1", actual_dates) == 10
        mongodb_result_counter.database.objects.count_documents.assert_called_once_with(
            {
                "$and": [
                    {"_collection_id": "collection_id_1"},
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

    def test_count_first_and_last(self, mongodb_result_counter):
        mongodb_result_counter.database.manifests.count_documents.return_value = 10
        assert mongodb_result_counter.count_first_or_last("collection_id_2") == 10
        mongodb_result_counter.database.manifests.count_documents.assert_called_once_with(
            {"_collection_id": "collection_id_2"}
        )

    def test_count_all_objects_in_collection(self, mongodb_result_counter):
        mongodb_result_counter.database.objects.count_documents.return_value = 15
        assert mongodb_result_counter.count_all_objects_in_collection("collection_id_3") == 15
        mongodb_result_counter.database.objects.count_documents.assert_called_once_with(
            {"_collection_id": "collection_id_3"}
        )

    @pytest.fixture
    def mongodb_result_counter(self):
        mock_db = MagicMock()
        return MongoDBResultCounter(mock_db)

    def test_get_count_by_current_filters_no_filters(self, mongodb_result_counter_with_mock_methods):
        assert mongodb_result_counter_with_mock_methods.get_count_by_current_filters(
            match_version=None,
            collection_id="collection_id_4",
            pipeline=[],
            unwind=False,
        ) == 40
        mongodb_result_counter_with_mock_methods.old_count.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_specific_dates.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_first_or_last.assert_called_once_with("collection_id_4")
        mongodb_result_counter_with_mock_methods.count_all_objects_in_collection.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_first_and_last.assert_not_called()

    def test_get_count_by_current_filters_all_filter(self, mongodb_result_counter_with_mock_methods):
        assert mongodb_result_counter_with_mock_methods.get_count_by_current_filters(
            match_version="all",
            collection_id="collection_id_5",
            pipeline=[],
            unwind=False,
        ) == 50

        mongodb_result_counter_with_mock_methods.count_all_objects_in_collection.assert_called_once_with(
            "collection_id_5")

        assert mongodb_result_counter_with_mock_methods.get_count_by_current_filters(
            match_version="all,first,all",
            collection_id="collection_id_5",
            pipeline=[],
            unwind=False,
        ) == 50

        assert mongodb_result_counter_with_mock_methods.get_count_by_current_filters(
            match_version="all,2025-01-21T00 19 40.000Z",
            collection_id="collection_id_5",
            pipeline=[],
            unwind=False,
        ) == 50

        assert mongodb_result_counter_with_mock_methods.count_all_objects_in_collection.call_count == 3
        mongodb_result_counter_with_mock_methods.old_count.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_specific_dates.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_first_or_last.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_first_and_last.assert_not_called()

    def test_get_count_by_current_filters_first_or_last_filter(self, mongodb_result_counter_with_mock_methods):
        assert mongodb_result_counter_with_mock_methods.get_count_by_current_filters(
            match_version="first",
            collection_id="collection_id_6",
            pipeline=[],
            unwind=False,
        ) == 40

        assert mongodb_result_counter_with_mock_methods.get_count_by_current_filters(
            match_version="last",
            collection_id="collection_id_6",
            pipeline=[],
            unwind=False,
        ) == 40

        assert mongodb_result_counter_with_mock_methods.count_first_or_last.call_count == 2
        mongodb_result_counter_with_mock_methods.old_count.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_specific_dates.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_all_objects_in_collection.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_first_and_last.assert_not_called()

    def test_get_count_by_current_filters_first_and_last_filter(self, mongodb_result_counter_with_mock_methods):
        assert mongodb_result_counter_with_mock_methods.get_count_by_current_filters(
            match_version="first,last",
            collection_id="collection_id_7",
            pipeline=[],
            unwind=False,
        ) == 60

        mongodb_result_counter_with_mock_methods.count_first_and_last.assert_called_once_with("collection_id_7")
        mongodb_result_counter_with_mock_methods.old_count.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_specific_dates.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_first_or_last.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_all_objects_in_collection.assert_not_called()

    def test_get_count_by_current_filters_specific_dates(self, mongodb_result_counter_with_mock_methods):
        assert mongodb_result_counter_with_mock_methods.get_count_by_current_filters(
            match_version="2025-01-21T00:19:40.000Z,2024-12-31T23:59:59.000Z",
            collection_id="collection_id_8",
            pipeline=[{"some": "pipeline"}],
            unwind=True,
        ) == 30

        mongodb_result_counter_with_mock_methods.count_specific_dates.assert_called_once_with(
            "collection_id_8", [1737418780.0, 1735689599.0]
        )
        mongodb_result_counter_with_mock_methods.old_count.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_first_or_last.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_all_objects_in_collection.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_first_and_last.assert_not_called()

    def test_get_count_by_current_filters_old_count(self, mongodb_result_counter_with_mock_methods):
        assert mongodb_result_counter_with_mock_methods.get_count_by_current_filters(
            match_version="2025-01-21T00:19:40.000Z,first",
            collection_id="collection_id_9",
            pipeline=[{"another": "pipeline"}],
            unwind=False,
        ) == 20

        assert mongodb_result_counter_with_mock_methods.get_count_by_current_filters(
            match_version="2025-01-21T00:19:40.000Z,last",
            collection_id="collection_id_9",
            pipeline=[{"another": "pipeline"}],
            unwind=False,
        ) == 20

        assert mongodb_result_counter_with_mock_methods.get_count_by_current_filters(
            match_version="2025-01-21T00:19:40.000Z,first,last",
            collection_id="collection_id_9",
            pipeline=[{"another": "pipeline"}],
            unwind=False,
        ) == 20

        assert mongodb_result_counter_with_mock_methods.old_count.call_count == 3

        mongodb_result_counter_with_mock_methods.count_specific_dates.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_first_or_last.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_all_objects_in_collection.assert_not_called()
        mongodb_result_counter_with_mock_methods.count_first_and_last.assert_not_called()

    @pytest.fixture
    def mongodb_result_counter_with_mock_methods(self):
        mock_db = MagicMock()
        counter = MongoDBResultCounter(mock_db)
        counter.old_count = MagicMock(return_value=20)
        counter.count_specific_dates = MagicMock(return_value=30)
        counter.count_first_or_last = MagicMock(return_value=40)
        counter.count_all_objects_in_collection = MagicMock(return_value=50)
        counter.count_first_and_last = MagicMock(return_value=60)
        return counter
