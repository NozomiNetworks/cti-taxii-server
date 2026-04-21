import pytest

from medallion.common import IndicatorType
from medallion.filters.mongodb_filter import MongoDBFilter


class TestMongoDBFilter:

    @pytest.mark.parametrize(
        "indicator_type, expected_prefix",
        [
            (IndicatorType.IPV4, r"\[ipv4\-addr:value\ ="),
            (IndicatorType.DOMAIN, r"\[domain\-name:value\ ="),
            (IndicatorType.URL, r"\[url:value\ ="),
            (IndicatorType.MD5, r"\[file:hashes\.'MD5'\ ="),
            (IndicatorType.SHA1, r"\[file:hashes\.'SHA\-1'\ ="),
            (IndicatorType.SHA256, r"\[file:hashes\.'SHA\-256'\ ="),
        ],
    )
    def test_get_pattern_prefix_from_indicator_type(self, indicator_type, expected_prefix):
        f = MongoDBFilter({}, {}, ())

        assert f._get_pattern_prefix_from_indicator_type(indicator_type) == expected_prefix

    def test_get_pattern_prefix_from_indicator_type_unsupported_raises(self):
        f = MongoDBFilter({}, {}, ())

        with pytest.raises(ValueError, match=r"(?i)unsupported indicator type"):
            f._get_pattern_prefix_from_indicator_type("unsupported")
