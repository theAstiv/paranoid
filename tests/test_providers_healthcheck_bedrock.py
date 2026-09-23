"""Tests for ping_bedrock and _map_bedrock_probe_error in healthcheck.py."""

import botocore.exceptions as _bce

from backend.providers.healthcheck import _map_bedrock_probe_error


def test_map_bedrock_probe_read_timeout_classified_as_timeout():
    """botocore.ReadTimeoutError must map to error='timeout', not 'network_error'."""
    exc = _bce.ReadTimeoutError(endpoint_url="https://bedrock.us-east-1.amazonaws.com")
    result = _map_bedrock_probe_error(exc, "some-model", "us-east-1")
    assert result["error"] == "timeout"
    assert "timed out" in result["message"].lower()


def test_map_bedrock_probe_connect_timeout_classified_as_timeout():
    """botocore.ConnectTimeoutError must map to error='timeout'."""
    exc = _bce.ConnectTimeoutError(endpoint_url="https://bedrock.us-east-1.amazonaws.com")
    result = _map_bedrock_probe_error(exc, "some-model", "us-east-1")
    assert result["error"] == "timeout"


def test_map_bedrock_probe_no_credentials():
    """NoCredentialsError maps to error='invalid_api_key'."""
    exc = _bce.NoCredentialsError()
    result = _map_bedrock_probe_error(exc, "some-model", "us-east-1")
    assert result["error"] == "invalid_api_key"
    assert "credentials" in result["message"].lower()


def test_map_bedrock_probe_access_denied():
    """AccessDeniedException maps to error='invalid_api_key' with region in message."""
    exc = _bce.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "Access denied"}},
        "Converse",
    )
    result = _map_bedrock_probe_error(exc, "some-model", "eu-west-1")
    assert result["error"] == "invalid_api_key"
    assert "eu-west-1" in result["message"]


def test_map_bedrock_probe_throttling():
    """ThrottlingException maps to error='rate_limited'."""
    exc = _bce.ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Too many requests"}},
        "Converse",
    )
    result = _map_bedrock_probe_error(exc, "some-model", "us-east-1")
    assert result["error"] == "rate_limited"


def test_map_bedrock_probe_unknown_falls_back_to_network_error():
    """An unrecognised exception maps to error='network_error'."""
    exc = ConnectionError("some network issue")
    result = _map_bedrock_probe_error(exc, "some-model", "us-east-1")
    assert result["error"] == "network_error"
    assert "some network issue" in result["message"]


def test_map_bedrock_probe_empty_region_uses_default_in_message():
    """When region is empty, the timeout message says 'default'."""
    exc = _bce.ReadTimeoutError(endpoint_url="https://example.com")
    result = _map_bedrock_probe_error(exc, "some-model", "")
    assert "default" in result["message"]
