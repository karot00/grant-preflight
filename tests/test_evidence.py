"""Tests for the P2.3 canonical hashing, IDs, and extraction validation
(services/evidence.py).

Pure in-memory tests under the P1.5 outbound-call guard. The fixed test clock
is 2026-09-05T12:00:00Z per the runbook, never the machine clock.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from models import (
    ApplicationSection,
    BudgetLine,
    Deadline,
    ExtractedRequirement,
    ExtractionResult,
    Fact,
    GenerationMeta,
    Grant,
    OrganizationProfile,
    QuotedValue,
    RequirementReview,
    ReviewSet,
    ReviewStatus,
    SourceSnapshot,
)
from services.evidence import (
    draft_fingerprint,
    grant_id,
    hash_extraction,
    hash_profile,
    hash_reviews,
    hash_source,
    normalize_for_quote,
    validate_extraction,
)

TEST_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

SOURCE_TEXT = (
    "Registered associations operating in Pirkanmaa, Finland may apply.\n"
    "The grant supports community cardiovascular-health workshops.\n"
    "Requests must be in EUR and must not exceed EUR 5,000.\n"
    "Applications close on 15 October 2026 at 13:00 Europe/Helsinki."
)


# --- factories ---------------------------------------------------------------


def make_profile(fact_ids=("ORG_ENTITY", "ORG_GEOGRAPHY"), **overrides) -> OrganizationProfile:
    data = dict(
        is_synthetic=True,
        name="Pirkanmaa Community Heart Association",
        entity_type="registered_association",
        country="FI",
        region="Pirkanmaa",
        mission="Community cardiovascular-health education and peer support.",
        project_title="Heart Health Saturdays",
        project_activity="Community workshops",
        requested_amount_minor=400000,
        currency="EUR",
        budget_lines=[
            BudgetLine(label="venue", amount_minor=120000),
            BudgetLine(label="materials", amount_minor=80000),
        ],
        facts=[
            Fact(
                id=fact_id,
                text=f"Fact text for {fact_id}.",
                approved=True,
                provenance="fixture",
                is_synthetic=True,
            )
            for fact_id in fact_ids
        ],
        profile_reviewed=True,
    )
    data.update(overrides)
    return OrganizationProfile(**data)


def make_source(**overrides) -> SourceSnapshot:
    data = dict(
        kind="synthetic",
        fixture_id="eligible",
        source_url=None,
        text=SOURCE_TEXT,
        source_hash=hash_source(SOURCE_TEXT),
        supplied_at=TEST_NOW,
        fetched_at=None,
        content_type=None,
        is_synthetic=True,
    )
    data.update(overrides)
    return SourceSnapshot(**data)


def make_extracted_requirement(**overrides) -> ExtractedRequirement:
    data = dict(
        dimension="applicant_type",
        description="Applicant must be a registered association in Pirkanmaa.",
        quote="Registered associations operating in Pirkanmaa, Finland may apply.",
        suggested_status="meets",
        suggested_fact_ids=["ORG_ENTITY", "ORG_GEOGRAPHY"],
        reason="The quoted clause names the organization type and region.",
    )
    data.update(overrides)
    return ExtractedRequirement(**data)


def make_section(**overrides) -> ApplicationSection:
    data = dict(
        id="model-supplied-id",
        title="Project description",
        instructions="Describe the project.",
        word_limit=300,
        quote="Describe the project.",
    )
    data.update(overrides)
    return ApplicationSection(**data)


def make_extraction(**overrides) -> ExtractionResult:
    data = dict(
        foundation=QuotedValue(value="Community Health Foundation", quote=None),
        title=QuotedValue(value=None, quote=None),
        amount=QuotedValue(value="EUR 5,000", quote="must not exceed EUR 5,000"),
        amount_min_minor=None,
        amount_max_minor=500000,
        currency="EUR",
        focus_areas=["cardiovascular health"],
        deadline=Deadline(
            kind="datetime",
            raw_text="15 October 2026 at 13:00 Europe/Helsinki",
            quote="Applications close on 15 October 2026 at 13:00 Europe/Helsinki.",
            at=datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc),
            on=None,
            timezone="Europe/Helsinki",
        ),
        requirements=[make_extracted_requirement()],
        application_sections=[make_section()],
        mission_fit="high",
        fit_reasons=["Workshops are the core activity."],
        missing_information=[],
        coverage_incomplete=False,
    )
    data.update(overrides)
    return ExtractionResult(**data)


def make_meta(**overrides) -> GenerationMeta:
    data = dict(
        origin="live",
        model_id="gemini-3.5-flash",
        prompt_version="1",
        generated_at=TEST_NOW,
        response_id="resp-1",
        input_tokens=100,
        output_tokens=200,
    )
    data.update(overrides)
    return GenerationMeta(**data)


def make_review_set(requirement_ids=("R001",), **overrides) -> ReviewSet:
    data = dict(
        items=[
            RequirementReview(
                requirement_id=requirement_id,
                status="meets",
                reviewed=True,
                fact_ids=["ORG_ENTITY"],
                reason="Reviewed against the quoted clause.",
            )
            for requirement_id in requirement_ids
        ],
        source_complete=True,
        coverage_reviewed=True,
        deadline_reviewed=True,
        profile_reviewed=True,
        application_instructions_reviewed=True,
        mission_fit="high",
        fit_reviewed=True,
    )
    data.update(overrides)
    return ReviewSet(**data)


def make_grant(**overrides) -> Grant:
    source = overrides.pop("source", make_source())
    extraction = overrides.pop("extraction", make_extraction())
    profile = overrides.pop("profile", make_profile())
    meta = overrides.pop("meta", make_meta())
    now = overrides.pop("now", TEST_NOW)
    assert not overrides, f"unexpected overrides: {sorted(overrides)}"
    return validate_extraction(source, extraction, profile, meta, now)


# --- normalize_for_quote -------------------------------------------------------


def test_normalize_collapses_whitespace_runs_and_strips_ends():
    assert normalize_for_quote("  a \t\n b  ") == "a b"
    assert normalize_for_quote("a\n\n\nb") == "a b"
    assert normalize_for_quote("") == ""
    assert normalize_for_quote("   ") == ""


def test_normalize_preserves_case_and_punctuation():
    text = "Only ACCREDITED universities may apply; registered associations are NOT eligible."
    assert normalize_for_quote(text) == text


# --- hash_source -----------------------------------------------------------------


def test_hash_source_is_a_deterministic_sha256_hex_digest():
    digest = hash_source(SOURCE_TEXT)
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)
    assert hash_source(SOURCE_TEXT) == digest


def test_hash_source_ignores_whitespace_differences_only():
    assert hash_source("a  b") == hash_source("a\nb") == hash_source("  a b  ")
    assert hash_source("a b") != hash_source("a  b c")
    assert hash_source("A b") != hash_source("a b")


# --- hash_profile -------------------------------------------------------------------


def test_hash_profile_is_stable_across_fact_order():
    first = make_profile(fact_ids=("ORG_ENTITY", "ORG_GEOGRAPHY"))
    second = make_profile(fact_ids=("ORG_GEOGRAPHY", "ORG_ENTITY"))
    assert hash_profile(first) == hash_profile(second)


def test_hash_profile_is_stable_across_construction_order():
    first = make_profile()
    second = OrganizationProfile(
        profile_reviewed=True,
        facts=first.facts,
        budget_lines=first.budget_lines,
        currency="EUR",
        requested_amount_minor=400000,
        project_activity="Community workshops",
        project_title="Heart Health Saturdays",
        mission=first.mission,
        region="Pirkanmaa",
        country="FI",
        entity_type="registered_association",
        name="Pirkanmaa Community Heart Association",
        is_synthetic=True,
    )
    assert hash_profile(first) == hash_profile(second)


def test_hash_profile_changes_with_every_field_and_approval_flag():
    baseline = hash_profile(make_profile())
    assert hash_profile(make_profile(name="Another Association")) != baseline
    assert hash_profile(make_profile(requested_amount_minor=399999)) != baseline
    assert hash_profile(make_profile(profile_reviewed=False)) != baseline
    assert hash_profile(make_profile(budget_lines=[BudgetLine(label="venue", amount_minor=120000)])) != baseline
    reordered_lines = make_profile()
    reordered_lines = reordered_lines.model_copy(
        update={"budget_lines": list(reversed(reordered_lines.budget_lines))}
    )
    assert hash_profile(reordered_lines) != baseline
    unapproved_fact = make_profile()
    facts = [
        fact.model_copy(update={"approved": False}) if fact.id == "ORG_ENTITY" else fact
        for fact in unapproved_fact.facts
    ]
    assert hash_profile(unapproved_fact.model_copy(update={"facts": facts})) != baseline


# --- hash_reviews ---------------------------------------------------------------------


def test_hash_reviews_is_stable_across_item_order():
    first = make_review_set(requirement_ids=("R001", "R002"))
    second = make_review_set(requirement_ids=("R002", "R001"))
    assert hash_reviews(first) == hash_reviews(second)


@pytest.mark.parametrize(
    "override",
    [
        {"source_complete": False},
        {"coverage_reviewed": False},
        {"deadline_reviewed": False},
        {"profile_reviewed": False},
        {"application_instructions_reviewed": False},
        {"mission_fit": "low"},
        {"fit_reviewed": False},
    ],
)
def test_hash_reviews_changes_with_every_flag_and_fit_decision(override):
    assert hash_reviews(make_review_set(**override)) != hash_reviews(make_review_set())


def test_hash_reviews_changes_with_item_status_and_reason():
    baseline = hash_reviews(make_review_set())
    changed_status = make_review_set()
    changed_status.items[0] = changed_status.items[0].model_copy(
        update={"status": ReviewStatus.fails}
    )
    assert hash_reviews(changed_status) != baseline
    changed_reason = make_review_set()
    changed_reason.items[0] = changed_reason.items[0].model_copy(
        update={"reason": "A different reviewed reason."}
    )
    assert hash_reviews(changed_reason) != baseline


# --- hash_extraction --------------------------------------------------------------------


def test_hash_extraction_is_deterministic():
    assert hash_extraction(make_extraction()) == hash_extraction(make_extraction())


def test_hash_extraction_preserves_requirement_and_section_order():
    first_requirement = make_extracted_requirement(description="First.")
    second_requirement = make_extracted_requirement(
        dimension="geography", description="Second.", suggested_fact_ids=["ORG_GEOGRAPHY"]
    )
    ordered = make_extraction(requirements=[first_requirement, second_requirement])
    reversed_result = make_extraction(requirements=[second_requirement, first_requirement])
    assert hash_extraction(ordered) != hash_extraction(reversed_result)

    first_section = make_section(title="A")
    second_section = make_section(title="B")
    ordered_sections = make_extraction(application_sections=[first_section, second_section])
    reversed_sections = make_extraction(application_sections=[second_section, first_section])
    assert hash_extraction(ordered_sections) != hash_extraction(reversed_sections)


def test_hash_extraction_changes_with_content():
    assert hash_extraction(make_extraction(mission_fit="low")) != hash_extraction(
        make_extraction()
    )


# --- grant_id -------------------------------------------------------------------------------


def test_grant_id_is_a_deterministic_uuid5():
    source = make_source()
    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, "grant-preflight:fixture:eligible"))
    assert grant_id(source) == expected
    assert grant_id(make_source()) == expected
    assert uuid.UUID(grant_id(source)).version == 5


def test_grant_id_uses_the_fixture_key_for_synthetic_sources():
    ids = {
        grant_id(make_source(fixture_id=fixture_id))
        for fixture_id in ("eligible", "excluded", "unclear", "expired", "wrong_region")
    }
    assert len(ids) == 5


def test_grant_id_uses_the_canonical_url_for_fetched_sources():
    url = "https://avustukset.hel.fi/en/grants?lang=en"
    fetched = make_source(
        kind="fetched",
        fixture_id=None,
        source_url=url,
        fetched_at=TEST_NOW,
        content_type="text/html",
        is_synthetic=False,
    )
    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, "grant-preflight:" + url))
    assert grant_id(fetched) == expected
    with_fragment = fetched.model_copy(update={"source_url": url + "#section-2"})
    assert grant_id(with_fragment) == expected
    different_query = fetched.model_copy(update={"source_url": url + "&page=2"})
    assert grant_id(different_query) != expected


def test_grant_id_falls_back_to_the_source_hash_without_a_url():
    pasted = make_source(
        kind="pasted", fixture_id=None, source_url=None, is_synthetic=False
    )
    expected = str(
        uuid.uuid5(uuid.NAMESPACE_URL, "grant-preflight:text:" + pasted.source_hash)
    )
    assert grant_id(pasted) == expected
    other_text = pasted.model_copy(
        update={"text": SOURCE_TEXT + " Extra.", "source_hash": hash_source(SOURCE_TEXT + " Extra.")}
    )
    assert grant_id(other_text) != expected


def test_grant_id_reads_identity_from_the_source_model_not_the_text_alone():
    synthetic = make_source()
    pasted_same_text = make_source(
        kind="pasted", fixture_id=None, is_synthetic=False
    )
    assert grant_id(synthetic) != grant_id(pasted_same_text)


# --- draft_fingerprint ------------------------------------------------------------------------


def build_fingerprint_inputs(**overrides):
    source = overrides.get("source", make_source())
    extraction = overrides.get("extraction", make_extraction())
    profile = overrides.get("profile", make_profile())
    meta = overrides.get("meta", make_meta())
    grant = validate_extraction(source, extraction, profile, meta, TEST_NOW)
    reviews = overrides.get("reviews", make_review_set(requirement_ids=("R001",)))
    kind = overrides.get("kind", "proposal")
    return grant, profile, reviews, kind


def test_draft_fingerprint_is_deterministic():
    first = build_fingerprint_inputs()
    second = build_fingerprint_inputs()
    assert draft_fingerprint(*first) == draft_fingerprint(*second)
    assert len(draft_fingerprint(*first)) == 64


@pytest.mark.parametrize("kind", ["proposal", "clarification"])
def test_draft_fingerprint_accepts_both_draft_kinds(kind):
    grant, profile, reviews, _ = build_fingerprint_inputs()
    assert len(draft_fingerprint(grant, profile, reviews, kind)) == 64


def test_draft_fingerprint_rejects_unknown_kind():
    grant, profile, reviews, _ = build_fingerprint_inputs()
    with pytest.raises(ValueError):
        draft_fingerprint(grant, profile, reviews, "invoice")


def test_draft_fingerprint_changes_with_each_included_component():
    baseline = draft_fingerprint(*build_fingerprint_inputs())

    other_source = build_fingerprint_inputs(
        source=make_source(fixture_id="excluded")
    )
    assert draft_fingerprint(*other_source) != baseline

    other_extraction = build_fingerprint_inputs(
        extraction=make_extraction(mission_fit="low")
    )
    assert draft_fingerprint(*other_extraction) != baseline

    other_profile = build_fingerprint_inputs(profile=make_profile(region="Uusimaa"))
    assert draft_fingerprint(*other_profile) != baseline

    other_reviews = build_fingerprint_inputs(reviews=make_review_set(fit_reviewed=False))
    assert draft_fingerprint(*other_reviews) != baseline

    other_kind = build_fingerprint_inputs(kind="clarification")
    assert draft_fingerprint(*other_kind) != baseline

    other_model = build_fingerprint_inputs(
        meta=make_meta(model_id="gemini-3.5-flash", response_id="resp-2")
    )
    assert draft_fingerprint(*other_model) == baseline  # response_id is excluded
    authored = build_fingerprint_inputs(
        meta=make_meta(origin="authored", model_id=None, response_id=None)
    )
    assert draft_fingerprint(*authored) != baseline  # model_id is included


def test_draft_fingerprint_excludes_timestamps_and_origin_labels():
    live = make_meta(origin="live", generated_at=TEST_NOW, response_id="resp-1")
    recorded = make_meta(
        origin="recorded",
        generated_at=datetime(2026, 9, 6, 8, 30, tzinfo=timezone.utc),
        response_id="resp-999",
    )
    first = build_fingerprint_inputs(meta=live)
    second = build_fingerprint_inputs(meta=recorded)
    assert draft_fingerprint(*first) == draft_fingerprint(*second)


def test_draft_fingerprint_changes_with_a_different_extraction_of_the_same_source():
    first = build_fingerprint_inputs()
    second = build_fingerprint_inputs(
        extraction=make_extraction(
            requirements=[make_extracted_requirement(description="A later, different extraction.")]
        )
    )
    assert draft_fingerprint(*first) != draft_fingerprint(*second)


# --- validate_extraction -------------------------------------------------------------------------


def test_validate_extraction_assigns_sequential_requirement_ids():
    extraction = make_extraction(
        requirements=[
            make_extracted_requirement(description="First."),
            make_extracted_requirement(dimension="geography", description="Second."),
            make_extracted_requirement(dimension="funding", description="Third."),
        ]
    )
    grant = validate_extraction(make_source(), extraction, make_profile(), make_meta(), TEST_NOW)
    assert [requirement.id for requirement in grant.requirements] == ["R001", "R002", "R003"]


def test_validate_extraction_replaces_model_supplied_section_ids():
    extraction = make_extraction(
        application_sections=[
            make_section(id="model-abc", title="A"),
            make_section(id="model-xyz", title="B"),
        ]
    )
    grant = validate_extraction(make_source(), extraction, make_profile(), make_meta(), TEST_NOW)
    assert [section.id for section in grant.extraction.application_sections] == [
        "S001",
        "S002",
    ]
    assert set(grant.metadata_evidence_valid) == {
        "foundation",
        "title",
        "amount",
        "deadline",
        "section:S001",
        "section:S002",
    }


def test_validate_extraction_is_idempotent_for_normalized_ids():
    extraction = make_extraction(
        application_sections=[make_section(id="S001"), make_section(id="S002", title="B")]
    )
    source, profile, meta = make_source(), make_profile(), make_meta()
    first = validate_extraction(source, extraction, profile, meta, TEST_NOW)
    second = validate_extraction(source, first.extraction, profile, meta, TEST_NOW)
    assert first.extraction == second.extraction
    assert hash_extraction(first.extraction) == hash_extraction(second.extraction)
    assert [requirement.id for requirement in second.requirements] == ["R001"]


def test_validate_extraction_stores_the_normalized_extraction_and_hash_inputs():
    source, extraction, profile, meta = make_source(), make_extraction(), make_profile(), make_meta()
    grant = validate_extraction(source, extraction, profile, meta, TEST_NOW)
    assert grant.id == grant_id(source)
    assert grant.source == source
    assert grant.extraction_profile_hash == hash_profile(profile)
    assert grant.extraction_meta == meta
    assert grant.created_at == TEST_NOW
    assert grant.updated_at == TEST_NOW
    assert grant.schema_version == 1


def test_evidence_flags_are_true_only_for_nonempty_matching_quotes():
    extraction = make_extraction(
        foundation=QuotedValue(value="X", quote="Registered associations operating in Pirkanmaa"),
        title=QuotedValue(value=None, quote=""),
        amount=QuotedValue(value=None, quote="must not exceed EUR 10,000"),
        deadline=Deadline(
            kind="datetime",
            raw_text=None,
            quote="Applications close on 15 October 2026 at 13:00 Europe/Helsinki.",
            at=datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc),
            on=None,
            timezone=None,
        ),
        application_sections=[
            make_section(quote="   "),
            make_section(title="B", quote=None),
            make_section(
                title="C",
                quote="Requests must be in EUR and must not exceed EUR 5,000.",
            ),
        ],
    )
    grant = validate_extraction(make_source(), extraction, make_profile(), make_meta(), TEST_NOW)
    evidence = grant.metadata_evidence_valid
    assert evidence["foundation"] is True
    assert evidence["title"] is False  # empty quote never matches
    assert evidence["amount"] is False  # quote absent from source
    assert evidence["deadline"] is True
    assert evidence["section:S001"] is False  # whitespace-only quote
    assert evidence["section:S002"] is False  # no quote
    assert evidence["section:S003"] is True


def test_quote_matching_normalizes_whitespace_but_preserves_case():
    extraction = make_extraction(
        foundation=QuotedValue(
            value=None,
            quote="Registered associations\n  operating in Pirkanmaa, Finland   may apply.",
        )
    )
    grant = validate_extraction(make_source(), extraction, make_profile(), make_meta(), TEST_NOW)
    assert grant.metadata_evidence_valid["foundation"] is True

    wrong_case = make_extraction(
        foundation=QuotedValue(value=None, quote="registered associations operating in pirkanmaa")
    )
    grant = validate_extraction(make_source(), wrong_case, make_profile(), make_meta(), TEST_NOW)
    assert grant.metadata_evidence_valid["foundation"] is False


def test_requirement_evidence_valid_follows_quote_matching():
    extraction = make_extraction(
        requirements=[
            make_extracted_requirement(
                description="Matches.",
                quote="The grant supports community cardiovascular-health workshops.",
            ),
            make_extracted_requirement(
                dimension="other", description="No quote.", quote=None
            ),
            make_extracted_requirement(
                dimension="funding", description="Wrong quote.", quote="must not exceed EUR 9,999."
            ),
        ]
    )
    grant = validate_extraction(make_source(), extraction, make_profile(), make_meta(), TEST_NOW)
    assert [requirement.evidence_valid for requirement in grant.requirements] == [
        True,
        False,
        False,
    ]
    assert len(grant.requirements) == 3  # invalid requirements are never erased


def test_unknown_fact_references_become_unknown_suggestions():
    extraction = make_extraction(
        requirements=[
            make_extracted_requirement(
                description="Partially unknown.",
                suggested_fact_ids=["ORG_ENTITY", "HALLUCINATED_FACT"],
            ),
            make_extracted_requirement(
                dimension="geography",
                description="Fully unknown.",
                suggested_fact_ids=["NOPE"],
            ),
            make_extracted_requirement(
                dimension="activity",
                description="Known.",
                suggested_fact_ids=["ORG_ENTITY"],
            ),
            make_extracted_requirement(
                dimension="other",
                description="No references.",
                suggested_status="unknown",
                suggested_fact_ids=[],
            ),
        ]
    )
    grant = validate_extraction(make_source(), extraction, make_profile(), make_meta(), TEST_NOW)
    first, second, third, fourth = grant.requirements
    assert first.suggested_status == "unknown"
    assert first.suggested_fact_ids == ["ORG_ENTITY"]
    assert second.suggested_status == "unknown"
    assert second.suggested_fact_ids == []
    assert third.suggested_status == "meets"
    assert third.suggested_fact_ids == ["ORG_ENTITY"]
    assert fourth.suggested_status == "unknown"
    assert fourth.suggested_fact_ids == []


def test_validate_extraction_rejects_a_naive_clock():
    with pytest.raises(ValidationError):
        validate_extraction(
            make_source(),
            make_extraction(),
            make_profile(),
            make_meta(),
            datetime(2026, 9, 5, 12, 0),
        )


def test_validate_extraction_normalizes_an_aware_clock_to_utc():
    plus_three = timezone(timedelta(hours=3))
    now_local = datetime(2026, 9, 5, 15, 0, tzinfo=plus_three)
    grant = validate_extraction(
        make_source(), make_extraction(), make_profile(), make_meta(), now_local
    )
    assert grant.created_at == TEST_NOW
    assert grant.created_at.tzinfo == timezone.utc


def test_assembled_grant_round_trips_through_json():
    grant = validate_extraction(
        make_source(), make_extraction(), make_profile(), make_meta(), TEST_NOW
    )
    restored = Grant.model_validate_json(grant.model_dump_json())
    assert restored == grant
