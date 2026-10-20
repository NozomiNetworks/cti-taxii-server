from medallion.common import APPLICATION_INSTANCE


def test_strict_slashes_disabled():
    # RFC-002: both slash variants of a route are served directly, without a
    # 308 redirect round trip.
    assert APPLICATION_INSTANCE.url_map.strict_slashes is False
