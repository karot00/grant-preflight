"""Tests for the demo service fixtures.

P2.4 scope: the canonical fixture-profile builder ``build_demo_profile``.
P2.5 scope (demo cases, source texts, recordings) is added by its own work
unit. Pure local-fixture tests under the P1.5 outbound-call guard.
"""

import json

import pytest

from errors import AppError
from models import OrganizationProfile
from services.demo_service import FIXTURE_CLOCK, build_demo_profile
from services.evidence import hash_profile

EXPECTED_FACT_IDS = (
    "ORG_ENTITY",
    "ORG_GEOGRAPHY",
    "ORG_MISSION",
    "PROJECT_ACTIVITY",
    "PROJECT_BUDGET",
    "HIST_WORKSHOPS",
    "HIST_ATTENDANCE",
)


# --- P2.4 build_demo_profile ----------------------------------------------------


def test_fixture_clock_is_the_fixed_runbook_timestamp():
    assert FIXTURE_CLOCK.isoformat() == "2026-09-05T12:00:00+00:00"


def test_approved_profile_matches_the_runbook_fixture():
    profile = build_demo_profile(approved=True)
    assert isinstance(profile, OrganizationProfile)
    assert profile.is_synthetic is True
    assert profile.name == "Pirkanmaa Community Heart Association"
    assert profile.entity_type == "registered_association"
    assert profile.country == "FI"
    assert profile.region == "Pirkanmaa"
    assert profile.mission == (
        "Community cardiovascular-health education and peer support."
    )
    assert profile.project_title == "Heart Health Saturdays"
    assert profile.project_activity == "Community workshops"
    assert profile.requested_amount_minor == 400000
    assert profile.currency == "EUR"
    assert profile.schema_version == 1


def test_budget_lines_sum_exactly_to_the_requested_amount():
    profile = build_demo_profile(approved=True)
    assert [(line.label, line.amount_minor) for line in profile.budget_lines] == [
        ("venue", 120000),
        ("materials", 80000),
        ("travel", 60000),
        ("insurance", 40000),
        ("evaluation", 100000),
    ]
    assert sum(line.amount_minor for line in profile.budget_lines) == 400000
    assert (
        sum(line.amount_minor for line in profile.budget_lines)
        == profile.requested_amount_minor
    )


def test_profile_carries_the_seven_fixture_facts_in_order():
    profile = build_demo_profile(approved=True)
    assert tuple(fact.id for fact in profile.facts) == EXPECTED_FACT_IDS
    assert all(fact.is_synthetic for fact in profile.facts)


def test_approved_true_sets_every_approval():
    profile = build_demo_profile(approved=True)
    assert profile.profile_reviewed is True
    assert all(fact.approved for fact in profile.facts)


def test_approved_false_clears_every_approval_without_other_changes():
    approved = build_demo_profile(approved=True)
    unapproved = build_demo_profile(approved=False)
    assert unapproved.profile_reviewed is False
    assert all(fact.approved is False for fact in unapproved.facts)
    approved_dump = approved.model_dump(mode="json")
    unapproved_dump = unapproved.model_dump(mode="json")
    approved_dump["profile_reviewed"] = False
    for fact in approved_dump["facts"]:
        fact["approved"] = False
    assert approved_dump == unapproved_dump


def test_approval_never_removes_synthetic_flags_or_provenance():
    for approved in (True, False):
        profile = build_demo_profile(approved=approved)
        assert profile.is_synthetic is True
        assert all(fact.is_synthetic for fact in profile.facts)
        assert all(fact.provenance for fact in profile.facts)


def test_history_facts_keep_the_honest_wording():
    profile = build_demo_profile(approved=True)
    facts = {fact.id: fact.text for fact in profile.facts}
    assert "4" in facts["HIST_WORKSHOPS"]
    assert "2025" in facts["HIST_WORKSHOPS"]
    assert "80" in facts["HIST_ATTENDANCE"]
    assert "attendances" in facts["HIST_ATTENDANCE"]
    assert "not a count of unique people" in facts["HIST_ATTENDANCE"]
    assert "planned activity, not a completed result" in facts["PROJECT_ACTIVITY"]


def test_builder_returns_detached_data():
    first = build_demo_profile(approved=True)
    second = build_demo_profile(approved=True)
    assert first == second
    assert first is not second
    assert first.facts is not second.facts
    assert first.facts[0] is not second.facts[0]


def test_profile_hash_is_deterministic_and_approval_sensitive():
    assert hash_profile(build_demo_profile(approved=True)) == hash_profile(
        build_demo_profile(approved=True)
    )
    assert hash_profile(build_demo_profile(approved=True)) != hash_profile(
        build_demo_profile(approved=False)
    )


def test_profile_text_stays_within_the_model_bound():
    profile = build_demo_profile(approved=True)
    total = sum(
        len(getattr(profile, name))
        for name in (
            "name",
            "entity_type",
            "country",
            "region",
            "mission",
            "project_title",
            "project_activity",
        )
    )
    total += sum(len(fact.text) + len(fact.provenance) for fact in profile.facts)
    total += sum(len(line.label) for line in profile.budget_lines)
    assert total <= 10000


def test_profile_round_trips_through_json():
    profile = build_demo_profile(approved=True)
    assert OrganizationProfile.model_validate_json(profile.model_dump_json()) == profile


def test_demo_service_class_is_not_implemented_yet():
    from services.demo_service import DemoService

    with pytest.raises(NotImplementedError):
        DemoService()


def test_corrupt_profile_fixture_raises_fixture_mismatch(monkeypatch, tmp_path):
    import services.demo_service as demo_service

    broken = tmp_path / "demo_profile.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(demo_service, "DEMO_PROFILE_PATH", broken)
    with pytest.raises(AppError) as excinfo:
        build_demo_profile(approved=True)
    assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_real_organization_profile_fixture_is_rejected(monkeypatch, tmp_path):
    import services.demo_service as demo_service

    payload = build_demo_profile(approved=True).model_dump(mode="json")
    payload["is_synthetic"] = False
    payload["facts"] = [
        {**fact, "is_synthetic": False} for fact in payload["facts"]
    ]
    realistic = tmp_path / "demo_profile.json"
    realistic.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(demo_service, "DEMO_PROFILE_PATH", realistic)
    with pytest.raises(AppError) as excinfo:
        build_demo_profile(approved=True)
    assert excinfo.value.code == "FIXTURE_MISMATCH"
