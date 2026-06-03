"""Tests for the username site registry and input validation."""

from __future__ import annotations

import pytest

from app.modules.username.registry import available_categories, filter_sites, load_sites
from app.services.username_service import UsernameService


def test_sites_load_and_are_well_formed():
    sites = load_sites()
    assert len(sites) >= 10
    for site in sites:
        assert "{}" in site.url, f"{site.name} url must be a template"
        assert site.check in ("status", "message")
        if site.check == "message":
            assert site.found_messages or site.error_messages


def test_categories_present():
    cats = available_categories()
    assert {"dev", "social"} <= set(cats)


def test_filter_sites_by_category():
    dev_sites = filter_sites(["dev"])
    assert dev_sites
    assert all(s.category == "dev" for s in dev_sites)


@pytest.mark.parametrize("username", ["torvalds", "a_b-c.d", "User123", "x"])
def test_valid_usernames(username):
    assert UsernameService.validate_username(username) == username


@pytest.mark.parametrize("username", ["bad!name", "'; DROP TABLE", "a" * 65, "", "   ", "-lead"])
def test_invalid_usernames(username):
    with pytest.raises(ValueError):
        UsernameService.validate_username(username)
