"""
Unit tests for the URL parser module.
These tests do NOT require a browser or network connection.
"""

import pytest
from src.parser import extract_activity_id, validate_and_parse, build_post_url

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

VALID_CASES = [
    # (input, expected_activity_id)
    ("7302346926123798528", "7302346926123798528"),
    ("  7302346926123798528  ", "7302346926123798528"),  # whitespace
    (
        "https://www.linkedin.com/feed/update/urn:li:activity:7302346926123798528/",
        "7302346926123798528",
    ),
    (
        "https://www.linkedin.com/posts/johndoe_some-title-activity-7302346926123798528-dMnz",
        "7302346926123798528",
    ),
    (
        "https://www.linkedin.com/posts/jane-doe_topic-activity-1234567890123456789-AbCd",
        "1234567890123456789",
    ),
    # URN without trailing slash
    (
        "https://www.linkedin.com/feed/update/urn:li:activity:9876543210987654321",
        "9876543210987654321",
    ),
]

INVALID_CASES = [
    "https://www.linkedin.com/in/johndoe/",           # profile page
    "https://www.linkedin.com/company/google/",        # company page
    "https://www.linkedin.com/jobs/view/1234567/",    # job listing
    "not-a-url",
    "",
    "https://twitter.com/status/12345",
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExtractActivityId:
    @pytest.mark.parametrize("url, expected", VALID_CASES)
    def test_valid_urls(self, url: str, expected: str):
        assert extract_activity_id(url) == expected

    @pytest.mark.parametrize("url", INVALID_CASES)
    def test_invalid_urls(self, url: str):
        assert extract_activity_id(url) is None


class TestBuildPostUrl:
    def test_correct_format(self):
        url = build_post_url("7302346926123798528")
        assert url == "https://www.linkedin.com/feed/update/urn:li:activity:7302346926123798528"

    def test_url_is_string(self):
        assert isinstance(build_post_url("123456789012345"), str)


class TestValidateAndParse:
    def test_returns_tuple(self):
        activity_id, post_url = validate_and_parse("7302346926123798528")
        assert activity_id == "7302346926123798528"
        assert "7302346926123798528" in post_url

    def test_raises_on_invalid(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            validate_and_parse("https://www.linkedin.com/in/johndoe/")

    def test_raises_on_empty(self):
        with pytest.raises(ValueError):
            validate_and_parse("")

    @pytest.mark.parametrize("url, expected_id", VALID_CASES)
    def test_all_valid_formats(self, url: str, expected_id: str):
        activity_id, post_url = validate_and_parse(url)
        assert activity_id == expected_id
        assert activity_id in post_url
