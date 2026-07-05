"""Tests for backend/models/enums.py — ModelStatus transition validation."""

import pytest

from backend.models.enums import is_valid_model_status_transition


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("pending", "in_progress"),
        ("in_progress", "completed"),
        ("in_progress", "failed"),
        ("completed", "in_progress"),
        ("completed", "in_review"),
        ("completed", "archived"),
        ("failed", "in_progress"),
        ("in_review", "approved"),
        ("in_review", "completed"),
        ("in_review", "archived"),
        ("approved", "in_review"),
        ("approved", "archived"),
    ],
)
def test_valid_transitions(current, new):
    assert is_valid_model_status_transition(current, new) is True


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("pending", "completed"),
        ("pending", "in_review"),
        ("pending", "archived"),
        ("in_progress", "in_review"),
        ("in_progress", "approved"),
        ("in_progress", "archived"),
        ("completed", "failed"),
        ("failed", "completed"),
        ("archived", "in_review"),
        ("archived", "approved"),
        ("archived", "in_progress"),
        ("approved", "completed"),
    ],
)
def test_invalid_transitions(current, new):
    assert is_valid_model_status_transition(current, new) is False


@pytest.mark.parametrize("status", ["pending", "in_progress", "completed", "archived"])
def test_noop_transition_always_allowed(status):
    assert is_valid_model_status_transition(status, status) is True


def test_unknown_status_strings_are_rejected():
    assert is_valid_model_status_transition("pending", "not_a_real_status") is False
    assert is_valid_model_status_transition("not_a_real_status", "pending") is False
