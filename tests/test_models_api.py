"""Tests for backend/models/api.py request models — currently just the
CVSS vector validator on UpdateThreatRequest (Week 4b-3)."""

import pytest
from pydantic import ValidationError

from backend.models.api import UpdateThreatRequest


def test_update_threat_request_accepts_valid_cvss_vector():
    req = UpdateThreatRequest(cvss_vector="AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")
    assert req.cvss_vector == "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"


def test_update_threat_request_accepts_none_cvss_vector():
    req = UpdateThreatRequest()
    assert req.cvss_vector is None


@pytest.mark.parametrize(
    "bad_vector",
    [
        "not a vector",
        "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H",  # missing A
        "AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",  # invalid AV value
    ],
)
def test_update_threat_request_rejects_malformed_cvss_vector(bad_vector):
    with pytest.raises(ValidationError):
        UpdateThreatRequest(cvss_vector=bad_vector)
