"""Tests for the demo service fixtures.

P2.4 scope: the canonical fixture-profile builder ``build_demo_profile``.
P2.5 scope: the five deterministic funding cases (source texts, authored
extractions/reviews/drafts, loaders) and the recording-bundle validation.
Pure local-fixture tests under the P1.5 outbound-call guard.
"""

import json
import uuid
from datetime import timedelta
from pathlib import Path

import pytest

from errors import AppError
from models import (
    Draft,
    GenerationMeta,
    OrganizationProfile,
    ReviewSet,
)
from services.demo_service import (
    CLARIFICATION_MAX_WORDS,
    DEMO_CASES_PATH,
    DEMO_RECORDINGS_PATH,
    FIXTURE_CLOCK,
    GENERIC_PROPOSAL_SECTIONS,
    SOURCE_TEXTS_DIR,
    DemoCase,
    DemoCasesFile,
    DemoRecording,
    build_demo_profile,
    build_loaded_case,
    build_unreviewed_reviews,
    load_demo_cases,
    load_demo_recordings,
    validate_recording_bundle,
    validate_recording_collection,
)
from services.evidence import (
    draft_fingerprint,
    grant_id,
    hash_profile,
    hash_source,
)
from settings import DRAFT_PROMPT_VERSION, EXTRACTION_PROMPT_VERSION

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


# --- P2.5 helpers ------------------------------------------------------------------


def raw_cases() -> list[DemoCase]:
    payload = json.loads(DEMO_CASES_PATH.read_text(encoding="utf-8"))
    return DemoCasesFile.model_validate(payload).cases


def raw_case(case_id: str) -> DemoCase:
    return next(case for case in raw_cases() if case.case_id == case_id)


def loaded_case(case_id: str):
    return next(case for case in load_demo_cases() if case.case_id == case_id)


EXPECTED_DECISIONS = {
    "eligible": "pursue",
    "excluded": "skip",
    "unclear": "clarify",
    "expired": "skip",
    "wrong_region": "skip",
}

EXPECTED_REQUIREMENT_COUNTS = {
    "eligible": 6,
    "excluded": 5,
    "unclear": 6,
    "expired": 6,
    "wrong_region": 6,
}

EXACT_CLAUSES = {
    "eligible": [
        "Registered associations operating in Pirkanmaa, Finland may apply.",
        "The grant supports community cardiovascular-health workshops.",
        "Requests must be in EUR and must not exceed EUR 5,000.",
        "Venue, materials, travel, insurance, and evaluation costs are eligible.",
        "Applications close on 15 October 2026 at 13:00 Europe/Helsinki.",
    ],
    "excluded": [
        "Only accredited universities may apply. Registered associations are not eligible.",
        "The grant supports community cardiovascular-health workshops.",
        "Requests must be in EUR and must not exceed EUR 5,000.",
        "Applications close on 15 October 2026 at 13:00 Europe/Helsinki.",
    ],
    "unclear": [
        "Registered associations operating in Pirkanmaa, Finland may apply.",
        "The grant supports community cardiovascular-health workshops.",
        "Eligible costs and mandatory co-funding are defined in Annex A. Annex A is not included in this text.",
        "Applications close on 15 October 2026 at 13:00 Europe/Helsinki.",
    ],
    "expired": [
        "Registered associations operating in Pirkanmaa, Finland may apply.",
        "Applications close on 31 August 2026 at 13:00 Europe/Helsinki.",
    ],
    "wrong_region": [
        "Only registered associations operating in Uusimaa, Finland may apply.",
        "The grant supports community cardiovascular-health workshops.",
        "Applications close on 15 October 2026 at 13:00 Europe/Helsinki.",
    ],
}


# --- P2.5 source texts ----------------------------------------------------------------


@pytest.mark.parametrize("case_id", sorted(EXACT_CLAUSES))
def test_source_texts_contain_the_exact_runbook_clauses(case_id):
    text = (SOURCE_TEXTS_DIR / f"{case_id}.txt").read_text(encoding="utf-8")
    for clause in EXACT_CLAUSES[case_id]:
        assert clause in text, (case_id, clause)


def test_source_texts_do_not_leak_other_cases():
    eligible = (SOURCE_TEXTS_DIR / "eligible.txt").read_text(encoding="utf-8")
    assert "Annex A" not in eligible
    assert "Uusimaa" not in eligible
    assert "31 August" not in eligible
    unclear = (SOURCE_TEXTS_DIR / "unclear.txt").read_text(encoding="utf-8")
    assert "Venue, materials, travel, insurance, and evaluation costs are eligible." not in unclear
    excluded = (SOURCE_TEXTS_DIR / "excluded.txt").read_text(encoding="utf-8")
    assert "Pirkanmaa, Finland may apply" not in excluded


# --- P2.5 demo case loading -------------------------------------------------------------


def test_load_demo_cases_returns_the_five_cases_with_expected_decisions():
    cases = load_demo_cases()
    assert [case.case_id for case in cases] == [
        "eligible",
        "excluded",
        "unclear",
        "expired",
        "wrong_region",
    ]
    for case in cases:
        assert case.expected_decision == EXPECTED_DECISIONS[case.case_id]


def test_case_sources_are_synthetic_fixtures_at_the_fixture_clock():
    for case in load_demo_cases():
        source = case.source
        assert source.kind == "synthetic"
        assert source.fixture_id == case.case_id
        assert source.source_url is None
        assert source.fetched_at is None
        assert source.content_type is None
        assert source.is_synthetic is True
        assert source.supplied_at == FIXTURE_CLOCK
        assert source.source_hash == hash_source(source.text)


def test_case_grants_are_assembled_with_authored_metadata():
    profile = build_demo_profile(approved=True)
    for case in load_demo_cases():
        grant = case.grant
        assert grant.id == grant_id(case.source)
        assert grant.extraction_profile_hash == hash_profile(profile)
        assert grant.created_at == FIXTURE_CLOCK
        assert grant.updated_at == FIXTURE_CLOCK
        meta = grant.extraction_meta
        assert meta.origin == "authored"
        assert meta.model_id is None
        assert meta.response_id is None
        assert meta.generated_at == FIXTURE_CLOCK
        assert meta.prompt_version == EXTRACTION_PROMPT_VERSION
        assert [r.id for r in grant.requirements] == [
            f"R{index:03d}"
            for index in range(1, EXPECTED_REQUIREMENT_COUNTS[case.case_id] + 1)
        ]


def test_authored_quotes_produce_true_evidence_flags():
    for case in load_demo_cases():
        assert all(r.evidence_valid for r in case.grant.requirements), case.case_id
        metadata = case.grant.metadata_evidence_valid
        assert metadata["foundation"] is True
        assert metadata["title"] is True
        assert metadata["amount"] is True
        assert metadata["deadline"] is True
        assert not any(key.startswith("section:") for key in metadata)


def test_reviewed_review_ids_match_normalized_requirement_ids():
    for case in load_demo_cases():
        assert sorted(item.requirement_id for item in case.reviewed_reviews.items) == sorted(
            r.id for r in case.grant.requirements
        )
        assert all(item.reviewed for item in case.reviewed_reviews.items)


def test_reviewed_fixtures_satisfy_the_review_invariants():
    profile = build_demo_profile(approved=True)
    known_fact_ids = {fact.id for fact in profile.facts}
    for case in load_demo_cases():
        for item in case.reviewed_reviews.items:
            assert item.reason.strip(), (case.case_id, item.requirement_id)
            assert set(item.fact_ids) <= known_fact_ids


def test_case_review_flags_match_the_runbook_outcomes():
    cases = {case.case_id: case for case in load_demo_cases()}
    assert cases["unclear"].reviewed_reviews.source_complete is False
    assert cases["unclear"].reviewed_reviews.items[4].status == "unknown"
    assert "Annex A" in cases["unclear"].grant.extraction.missing_information[0]
    assert cases["excluded"].reviewed_reviews.items[0].status == "fails"
    assert cases["excluded"].reviewed_reviews.mission_fit == "high"
    assert cases["expired"].reviewed_reviews.items[5].status == "fails"
    assert cases["wrong_region"].reviewed_reviews.items[1].status == "fails"
    assert all(item.status == "meets" for item in cases["eligible"].reviewed_reviews.items)
    for case in cases.values():
        assert case.reviewed_reviews.source_complete is (case.case_id != "unclear")
        assert case.reviewed_reviews.coverage_reviewed is True
        assert case.reviewed_reviews.deadline_reviewed is True
        assert case.reviewed_reviews.profile_reviewed is True
        assert case.reviewed_reviews.fit_reviewed is True


def test_expired_deadline_is_before_the_fixture_clock():
    case = loaded_case("expired")
    assert case.grant.extraction.deadline.at < FIXTURE_CLOCK
    for case_id in ("eligible", "excluded", "unclear", "wrong_region"):
        assert loaded_case(case_id).grant.extraction.deadline.at > FIXTURE_CLOCK


def test_unreviewed_variants_have_all_review_flags_false():
    for case in load_demo_cases():
        unreviewed = case.unreviewed_reviews
        assert unreviewed.source_complete is False
        assert unreviewed.coverage_reviewed is False
        assert unreviewed.deadline_reviewed is False
        assert unreviewed.profile_reviewed is False
        assert unreviewed.application_instructions_reviewed is False
        assert unreviewed.fit_reviewed is False
        assert unreviewed.mission_fit == "unknown"
        assert len(unreviewed.items) == len(case.grant.requirements)
        for item in unreviewed.items:
            assert item.reviewed is False
            assert item.status == "unknown"
            assert item.fact_ids == []
            assert item.reason == "Not reviewed"
    assert build_unreviewed_reviews(loaded_case("eligible").grant) == (
        loaded_case("eligible").unreviewed_reviews
    )


# --- P2.5 authored drafts -----------------------------------------------------------------


def test_eligible_authored_proposal_uses_the_six_default_sections():
    draft = loaded_case("eligible").draft
    assert draft is not None
    assert draft.kind == "proposal"
    assert [(section.id, section.title) for section in draft.sections] == list(
        GENERIC_PROPOSAL_SECTIONS
    )
    total_words = sum(len(section.generated_text.split()) for section in draft.sections)
    assert 800 <= total_words <= 1200
    assert all(section.word_limit is None for section in draft.sections)
    assert all(section.edited_text is None for section in draft.sections)


def test_unclear_authored_clarification_is_one_short_email_section():
    draft = loaded_case("unclear").draft
    assert draft is not None
    assert draft.kind == "clarification"
    assert [section.id for section in draft.sections] == ["clarification"]
    total_words = sum(len(section.generated_text.split()) for section in draft.sections)
    assert total_words <= CLARIFICATION_MAX_WORDS
    assert "Annex A" in draft.sections[0].generated_text


@pytest.mark.parametrize("case_id", ["excluded", "expired", "wrong_region"])
def test_skip_cases_carry_no_authored_draft(case_id):
    assert loaded_case(case_id).draft is None
    assert raw_case(case_id).authored_draft_result is None


def test_authored_draft_metadata_and_fingerprint():
    profile = build_demo_profile(approved=True)
    for case_id in ("eligible", "unclear"):
        case = loaded_case(case_id)
        draft = case.draft
        assert draft.meta.origin == "authored"
        assert draft.meta.model_id is None
        assert draft.meta.response_id is None
        assert draft.meta.generated_at == FIXTURE_CLOCK
        assert draft.meta.prompt_version == DRAFT_PROMPT_VERSION
        assert draft.is_synthetic is True
        assert draft.assessment_id == str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"grant-preflight:authored-assessment:{case_id}")
        )
        assert draft.id == str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"grant-preflight:authored-draft:{case_id}")
        )
        assert draft.input_fingerprint == draft_fingerprint(
            case.grant, profile, case.reviewed_reviews, draft.kind
        )


def test_authored_drafts_reference_only_known_profile_facts():
    known = {fact.id for fact in build_demo_profile(approved=True).facts}
    for case_id in ("eligible", "unclear"):
        draft = loaded_case(case_id).draft
        for section in draft.sections:
            assert set(section.fact_ids) <= known
            assert section.placeholders == []


def test_attendance_wording_is_preserved_in_the_authored_proposal():
    draft = loaded_case("eligible").draft
    combined = " ".join(section.generated_text for section in draft.sections)
    assert "attendances" in combined
    assert "not unique people" in combined
    assert "80 unique" not in combined.lower()
    assert "does not claim a specific number of unique beneficiaries" in combined


# --- P2.5 loader determinism, detachment, round-trip -------------------------------------------


def test_load_demo_cases_is_deterministic_and_detached():
    first = load_demo_cases()
    second = load_demo_cases()
    assert [case.grant for case in first] == [case.grant for case in second]
    assert [case.draft for case in first] == [case.draft for case in second]
    assert first[0].grant is not second[0].grant


def test_loaded_records_round_trip_through_json():
    case = loaded_case("eligible")
    assert type(case.grant).model_validate_json(case.grant.model_dump_json()) == case.grant
    assert Draft.model_validate_json(case.draft.model_dump_json()) == case.draft
    assert ReviewSet.model_validate_json(
        case.reviewed_reviews.model_dump_json()
    ) == case.reviewed_reviews


def test_no_fixture_implies_a_real_grant_or_real_nonprofit():
    for case in load_demo_cases():
        assert case.source.is_synthetic is True
        assert case.grant.source.is_synthetic is True
        if case.draft is not None:
            assert case.draft.is_synthetic is True
        assert "Foundation" in case.grant.extraction.foundation.value


# --- P2.5 loader rejection paths --------------------------------------------------------------------


def profile_for_cases() -> OrganizationProfile:
    return build_demo_profile(approved=True)


def test_source_file_outside_the_allowlist_is_rejected():
    case = raw_case("eligible")
    for source_file in ("../demo_profile.json", "funding_sources.json", "/etc/passwd"):
        with pytest.raises(AppError) as excinfo:
            build_loaded_case(case.model_copy(update={"source_file": source_file}), profile_for_cases())
        assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_case_id_must_match_the_source_basename():
    case = raw_case("eligible")
    with pytest.raises(AppError) as excinfo:
        build_loaded_case(case.model_copy(update={"case_id": "excluded"}), profile_for_cases())
    assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_review_id_mismatch_is_rejected():
    case = raw_case("eligible")
    reviews = case.authored_reviews.model_copy(
        update={"items": case.authored_reviews.items[:5]}
    )
    with pytest.raises(AppError) as excinfo:
        build_loaded_case(case.model_copy(update={"authored_reviews": reviews}), profile_for_cases())
    assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_skip_case_with_a_draft_is_rejected():
    case = raw_case("excluded").model_copy(
        update={"authored_draft_result": raw_case("eligible").authored_draft_result}
    )
    with pytest.raises(AppError) as excinfo:
        build_loaded_case(case, profile_for_cases())
    assert excinfo.value.code == "FIXTURE_MISMATCH"
    assert "skip" in excinfo.value.message


def test_draft_with_unknown_fact_references_is_rejected():
    case = raw_case("eligible")
    sections = [
        section.model_copy(update={"fact_ids": [*section.fact_ids, "INVENTED_FACT"]})
        if section.id == "executive_summary"
        else section
        for section in case.authored_draft_result.sections
    ]
    mutated = case.model_copy(
        update={
            "authored_draft_result": case.authored_draft_result.model_copy(
                update={"sections": sections}
            )
        }
    )
    with pytest.raises(AppError) as excinfo:
        build_loaded_case(mutated, profile_for_cases())
    assert excinfo.value.code == "FIXTURE_MISMATCH"
    assert "INVENTED_FACT" in excinfo.value.message


def test_proposal_sections_must_match_the_prescribed_ids_in_order():
    case = raw_case("eligible")
    result = case.authored_draft_result
    dropped = result.model_copy(update={"sections": result.sections[:5]})
    with pytest.raises(AppError):
        build_loaded_case(
            case.model_copy(update={"authored_draft_result": dropped}), profile_for_cases()
        )
    reordered = result.model_copy(
        update={"sections": [result.sections[1], result.sections[0], *result.sections[2:]]}
    )
    with pytest.raises(AppError):
        build_loaded_case(
            case.model_copy(update={"authored_draft_result": reordered}), profile_for_cases()
        )
    retitled = result.model_copy(
        update={
            "sections": [
                result.sections[0].model_copy(update={"title": "Summary"}),
                *result.sections[1:],
            ]
        }
    )
    with pytest.raises(AppError):
        build_loaded_case(
            case.model_copy(update={"authored_draft_result": retitled}), profile_for_cases()
        )


def test_clarification_over_the_word_maximum_is_rejected():
    case = raw_case("unclear")
    result = case.authored_draft_result
    long_text = " ".join(["word"] * (CLARIFICATION_MAX_WORDS + 1))
    overlong = result.model_copy(
        update={
            "sections": [result.sections[0].model_copy(update={"text": long_text})]
        }
    )
    with pytest.raises(AppError) as excinfo:
        build_loaded_case(
            case.model_copy(update={"authored_draft_result": overlong}), profile_for_cases()
        )
    assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_proposal_over_the_hard_maximum_is_rejected():
    case = raw_case("eligible")
    result = case.authored_draft_result
    huge = " ".join(["word"] * 1500)
    overlong = result.model_copy(
        update={
            "sections": [result.sections[0].model_copy(update={"text": huge}), *result.sections[1:]]
        }
    )
    with pytest.raises(AppError) as excinfo:
        build_loaded_case(
            case.model_copy(update={"authored_draft_result": overlong}), profile_for_cases()
        )
    assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_cases_file_must_contain_exactly_the_five_unique_cases(monkeypatch, tmp_path):
    payload = json.loads(DEMO_CASES_PATH.read_text(encoding="utf-8"))

    duplicated = tmp_path / "duplicated.json"
    duplicated.write_text(
        json.dumps({**payload, "cases": [*payload["cases"], payload["cases"][0]]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("services.demo_service.DEMO_CASES_PATH", duplicated)
    with pytest.raises(AppError) as excinfo:
        load_demo_cases()
    assert excinfo.value.code == "FIXTURE_MISMATCH"
    assert "unique" in excinfo.value.message

    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(
        json.dumps({**payload, "cases": payload["cases"][:4]}), encoding="utf-8"
    )
    monkeypatch.setattr("services.demo_service.DEMO_CASES_PATH", incomplete)
    with pytest.raises(AppError) as excinfo:
        load_demo_cases()
    assert excinfo.value.code == "FIXTURE_MISMATCH"
    assert "five known cases" in excinfo.value.message


def test_corrupt_cases_file_is_fixture_mismatch(monkeypatch, tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("services.demo_service.DEMO_CASES_PATH", broken)
    with pytest.raises(AppError) as excinfo:
        load_demo_cases()
    assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_missing_source_text_file_is_fixture_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr("services.demo_service.SOURCE_TEXTS_DIR", tmp_path)
    with pytest.raises(AppError) as excinfo:
        load_demo_cases()
    assert excinfo.value.code == "FIXTURE_MISMATCH"


# --- P2.5 recordings ------------------------------------------------------------------------


def make_recorded_bundle(case, *, assessment_id="assessment-live-1"):
    profile = build_demo_profile(approved=True)
    recorded_at = FIXTURE_CLOCK + timedelta(days=1)
    draft = Draft(
        id=str(uuid.uuid4()),
        assessment_id=assessment_id,
        kind=case.draft.kind,
        sections=case.draft.sections,
        meta=GenerationMeta(
            origin="recorded",
            model_id="gemini-3.5-flash",
            prompt_version=DRAFT_PROMPT_VERSION,
            generated_at=recorded_at,
            response_id="resp-live-1",
            input_tokens=900,
            output_tokens=950,
        ),
        input_fingerprint=draft_fingerprint(
            case.grant, profile, case.reviewed_reviews, case.draft.kind
        ),
        is_synthetic=True,
    )
    return DemoRecording(
        case_id=case.case_id,
        source_assessment_id=assessment_id,
        grant_snapshot=case.grant,
        profile_snapshot=profile,
        reviews=case.reviewed_reviews,
        draft=draft,
    )


def test_shipped_recordings_file_is_empty_and_valid():
    assert load_demo_recordings() == []
    payload = json.loads(DEMO_RECORDINGS_PATH.read_text(encoding="utf-8"))
    assert payload == {"schema_version": 1, "recordings": []}


def test_correctly_captured_bundle_passes_validation():
    case = loaded_case("eligible")
    recording = make_recorded_bundle(case)
    validate_recording_bundle(recording, case)
    validate_recording_collection([recording], load_demo_cases())
    assert recording.draft.input_fingerprint == case.draft.input_fingerprint


def test_bundle_from_another_case_is_rejected():
    recording = make_recorded_bundle(loaded_case("eligible"))
    with pytest.raises(AppError) as excinfo:
        validate_recording_bundle(recording, loaded_case("unclear"))
    assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_edited_source_text_or_hash_is_rejected():
    case = loaded_case("eligible")
    recording = make_recorded_bundle(case)
    edited_text = recording.grant_snapshot.model_copy(
        update={
            "source": case.source.model_copy(
                update={"text": case.source.text + " Edited privately."}
            )
        }
    )
    with pytest.raises(AppError):
        validate_recording_bundle(
            recording.model_copy(update={"grant_snapshot": edited_text}), case
        )
    consistent_edit = "Registered associations operating in Pirkanmaa, Finland may apply. Only."
    edited_both = recording.grant_snapshot.model_copy(
        update={
            "source": case.source.model_copy(
                update={"text": consistent_edit, "source_hash": hash_source(consistent_edit)}
            )
        }
    )
    with pytest.raises(AppError):
        validate_recording_bundle(
            recording.model_copy(update={"grant_snapshot": edited_both}), case
        )


def test_edited_or_unapproved_profile_is_rejected_even_when_synthetic():
    case = loaded_case("eligible")
    recording = make_recorded_bundle(case)
    edited_profile = recording.profile_snapshot.model_copy(
        update={"mission": "A privately edited mission statement."}
    )
    assert edited_profile.is_synthetic is True
    with pytest.raises(AppError):
        validate_recording_bundle(
            recording.model_copy(update={"profile_snapshot": edited_profile}), case
        )
    with pytest.raises(AppError):
        validate_recording_bundle(
            recording.model_copy(
                update={"profile_snapshot": build_demo_profile(approved=False)}
            ),
            case,
        )


def test_wrong_extraction_profile_hash_is_rejected():
    case = loaded_case("eligible")
    recording = make_recorded_bundle(case)
    mutated = recording.grant_snapshot.model_copy(
        update={"extraction_profile_hash": "0" * 64}
    )
    with pytest.raises(AppError):
        validate_recording_bundle(
            recording.model_copy(update={"grant_snapshot": mutated}), case
        )


def test_review_id_mismatch_in_bundle_is_rejected():
    case = loaded_case("eligible")
    recording = make_recorded_bundle(case)
    mutated = recording.reviews.model_copy(update={"items": recording.reviews.items[:5]})
    with pytest.raises(AppError):
        validate_recording_bundle(recording.model_copy(update={"reviews": mutated}), case)


def test_wrong_draft_assessment_association_is_rejected():
    case = loaded_case("eligible")
    recording = make_recorded_bundle(case)
    mutated = recording.draft.model_copy(update={"assessment_id": "another-assessment"})
    with pytest.raises(AppError) as excinfo:
        validate_recording_bundle(recording.model_copy(update={"draft": mutated}), case)
    assert excinfo.value.code == "FIXTURE_MISMATCH"
    assert "assessment ID" in excinfo.value.message


def test_wrong_draft_fingerprint_is_rejected():
    case = loaded_case("eligible")
    recording = make_recorded_bundle(case)
    mutated = recording.draft.model_copy(update={"input_fingerprint": "0" * 64})
    with pytest.raises(AppError):
        validate_recording_bundle(recording.model_copy(update={"draft": mutated}), case)


def test_duplicate_case_ids_are_rejected():
    case = loaded_case("eligible")
    recording = make_recorded_bundle(case)
    with pytest.raises(AppError) as excinfo:
        validate_recording_collection([recording, recording], load_demo_cases())
    assert excinfo.value.code == "FIXTURE_MISMATCH"
    assert "one recording bundle per case" in excinfo.value.message


def test_duplicate_extraction_lookup_keys_are_rejected():
    eligible = loaded_case("eligible")
    first = make_recorded_bundle(eligible)
    impostor = make_recorded_bundle(eligible, assessment_id="assessment-live-2")
    impostor = impostor.model_copy(update={"case_id": "unclear"})
    with pytest.raises(AppError) as excinfo:
        validate_recording_collection([first, impostor], load_demo_cases())
    assert excinfo.value.code == "FIXTURE_MISMATCH"
    assert "extraction lookup keys" in excinfo.value.message


def test_duplicate_draft_fingerprints_are_rejected():
    eligible = loaded_case("eligible")
    unclear = loaded_case("unclear")
    first = make_recorded_bundle(eligible)
    second = make_recorded_bundle(unclear, assessment_id="assessment-live-2")
    second = second.model_copy(
        update={
            "draft": second.draft.model_copy(
                update={"input_fingerprint": first.draft.input_fingerprint}
            )
        }
    )
    with pytest.raises(AppError) as excinfo:
        validate_recording_collection([first, second], load_demo_cases())
    assert excinfo.value.code == "FIXTURE_MISMATCH"
    assert "fingerprint" in excinfo.value.message


def test_recording_for_unknown_case_is_rejected():
    eligible = loaded_case("eligible")
    recording = make_recorded_bundle(eligible)
    unknown = recording.model_copy(update={"case_id": "nonexistent"})
    with pytest.raises(AppError) as excinfo:
        validate_recording_collection([unknown], load_demo_cases())
    assert excinfo.value.code == "FIXTURE_MISMATCH"
    assert "unknown case" in excinfo.value.message


def test_recordings_file_shape_is_validated(monkeypatch, tmp_path):
    broken = tmp_path / "recordings.json"
    broken.write_text('{"schema_version": 1, "recordings": [{}]}', encoding="utf-8")
    monkeypatch.setattr("services.demo_service.DEMO_RECORDINGS_PATH", broken)
    with pytest.raises(AppError) as excinfo:
        load_demo_recordings()
    assert excinfo.value.code == "FIXTURE_MISMATCH"
