"""Tests for the P2.1 serialization rules and P2.2 record models (models.py).

These tests are pure: they construct records in memory and round-trip them
through JSON. The conftest outbound-call guard is active, so any accidental
network, DNS, Gemini, or Snowflake call during import or validation would
raise OutboundCallBlocked.
"""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from errors import AppError
from models import (
    DEMO_FIXTURE_IDS,
    MAX_PROFILE_BUDGET_LINES,
    MAX_PROFILE_FACTS,
    MAX_PROFILE_TEXT_CHARS,
    ApplicationSection,
    Assessment,
    AssessmentRecord,
    BudgetLine,
    Deadline,
    DeadlineKind,
    Decision,
    Dimension,
    Draft,
    DraftKind,
    DraftSection,
    DraftSectionResult,
    DraftResult,
    ExtractedRequirement,
    ExtractionResult,
    Fact,
    GenerationMeta,
    Grant,
    MissionFit,
    OrganizationProfile,
    OutputOrigin,
    QuotedValue,
    Requirement,
    RequirementReview,
    ReviewSet,
    ReviewStatus,
    SourceKind,
    SourceSnapshot,
)
from settings import MAX_SOURCE_CHARS

TEST_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


# --- factories ---------------------------------------------------------------


def make_fact(**overrides) -> Fact:
    data = dict(
        id="ORG_ENTITY",
        text="A registered association in Pirkanmaa.",
        approved=True,
        provenance="fixture",
        is_synthetic=True,
    )
    data.update(overrides)
    return Fact(**data)


def make_profile(**overrides) -> OrganizationProfile:
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
        budget_lines=[BudgetLine(label="venue", amount_minor=120000)],
        facts=[make_fact()],
        profile_reviewed=True,
    )
    data.update(overrides)
    return OrganizationProfile(**data)


def make_source(**overrides) -> SourceSnapshot:
    data = dict(
        kind="synthetic",
        fixture_id="eligible",
        source_url=None,
        text="Registered associations operating in Pirkanmaa, Finland may apply. "
        "The grant supports community cardiovascular-health workshops.",
        source_hash="ab" * 32,
        supplied_at=TEST_NOW,
        fetched_at=None,
        content_type=None,
        is_synthetic=True,
    )
    data.update(overrides)
    return SourceSnapshot(**data)


def make_deadline(**overrides) -> Deadline:
    data = dict(
        kind="datetime",
        raw_text="15 October 2026 at 13:00 Europe/Helsinki",
        quote="Applications close on 15 October 2026 at 13:00 Europe/Helsinki.",
        at=datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc),
        on=None,
        timezone="Europe/Helsinki",
    )
    data.update(overrides)
    return Deadline(**data)


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


def make_requirement(**overrides) -> Requirement:
    data = dict(id="R001", evidence_valid=True)
    data.update(overrides)
    return Requirement(**make_extracted_requirement().model_dump(), **data)


def make_extraction(**overrides) -> ExtractionResult:
    data = dict(
        foundation=QuotedValue(value="Community Health Foundation", quote="..."),
        title=QuotedValue(value="Heart Health Saturdays", quote="..."),
        amount=QuotedValue(value="EUR 5,000", quote="must not exceed EUR 5,000"),
        amount_min_minor=None,
        amount_max_minor=500000,
        currency="EUR",
        focus_areas=["cardiovascular health"],
        deadline=make_deadline(),
        requirements=[make_extracted_requirement()],
        application_sections=[
            ApplicationSection(
                id="S001",
                title="Project description",
                instructions="Describe the project.",
                word_limit=300,
                quote="Describe the project.",
            )
        ],
        mission_fit="high",
        fit_reasons=["Community cardiovascular-health workshops are the core activity."],
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


def make_grant(**overrides) -> Grant:
    data = dict(
        id="grant-id",
        source=make_source(),
        extraction=make_extraction(),
        requirements=[make_requirement()],
        metadata_evidence_valid={
            "foundation": True,
            "title": True,
            "amount": True,
            "deadline": True,
            "section:S001": True,
        },
        extraction_profile_hash="cd" * 32,
        extraction_meta=make_meta(),
        created_at=TEST_NOW,
        updated_at=TEST_NOW,
    )
    data.update(overrides)
    return Grant(**data)


def make_review(**overrides) -> RequirementReview:
    data = dict(
        requirement_id="R001",
        status="meets",
        reviewed=True,
        fact_ids=["ORG_ENTITY"],
        reason="Reviewed against the quoted clause.",
    )
    data.update(overrides)
    return RequirementReview(**data)


def make_review_set(**overrides) -> ReviewSet:
    data = dict(
        items=[make_review()],
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


def make_assessment(**overrides) -> Assessment:
    data = dict(
        id="assessment-id",
        grant_id="grant-id",
        grant_snapshot=make_grant(),
        profile_snapshot=make_profile(),
        profile_hash="ef" * 32,
        review_hash="01" * 32,
        reviews=make_review_set(),
        decision="pursue",
        blockers=[],
        unknowns=[],
        evaluated_at=TEST_NOW,
    )
    data.update(overrides)
    return Assessment(**data)


def make_draft(**overrides) -> Draft:
    data = dict(
        id="draft-id",
        assessment_id="assessment-id",
        kind="proposal",
        sections=[
            DraftSection(
                id="D001",
                title="Summary",
                generated_text="A community workshop project.",
            )
        ],
        meta=make_meta(),
        input_fingerprint="23" * 32,
        is_synthetic=True,
    )
    data.update(overrides)
    return Draft(**data)


# --- P2.1 enums ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("enum_cls", "expected"),
    [
        (SourceKind, {"synthetic", "pasted", "fetched"}),
        (ReviewStatus, {"meets", "fails", "unknown"}),
        (Decision, {"pursue", "clarify", "skip"}),
        (MissionFit, {"high", "medium", "low", "unknown"}),
        (
            Dimension,
            {"applicant_type", "geography", "activity", "funding", "deadline", "other"},
        ),
        (DeadlineKind, {"datetime", "date", "rolling", "unknown"}),
        (DraftKind, {"proposal", "clarification"}),
        (OutputOrigin, {"live", "recorded", "authored"}),
    ],
)
def test_enum_values_are_exact_string_literals(enum_cls, expected):
    assert {member.value for member in enum_cls} == expected
    assert all(isinstance(member.value, str) for member in enum_cls)


def test_enums_validate_from_plain_strings():
    source = make_source(kind="pasted", fixture_id=None)
    assert source.kind is SourceKind.pasted


# --- P2.1 schema version ------------------------------------------------------


def test_schema_version_defaults_to_one():
    assert make_profile().schema_version == 1
    assert make_source().schema_version == 1
    assert make_grant().schema_version == 1
    assert make_assessment().schema_version == 1
    assert make_draft().schema_version == 1


@pytest.mark.parametrize("invalid", [True, False, "1", 1.0, 2, None])
def test_schema_version_accepts_only_actual_integer_one(invalid):
    with pytest.raises(ValidationError):
        make_source(schema_version=invalid)


def test_schema_version_accepts_integer_one_explicitly():
    assert make_source(schema_version=1).schema_version == 1


# --- P2.1 strict integers and booleans -----------------------------------------


@pytest.mark.parametrize("invalid", [400000.0, True, "400000"])
def test_money_rejects_floats_booleans_and_strings(invalid):
    with pytest.raises(ValidationError):
        make_profile(requested_amount_minor=invalid)


def test_money_rejects_negative_amounts():
    with pytest.raises(ValidationError):
        BudgetLine(label="venue", amount_minor=-1)
    with pytest.raises(ValidationError):
        make_extraction(amount_max_minor=-500000)


@pytest.mark.parametrize("invalid", ["false", "true", 1, 0, None])
def test_booleans_reject_strings_ints_and_none(invalid):
    with pytest.raises(ValidationError):
        make_profile(profile_reviewed=invalid)


def test_token_counts_reject_negative_and_float_values():
    with pytest.raises(ValidationError):
        make_meta(input_tokens=-1)
    with pytest.raises(ValidationError):
        make_meta(output_tokens=1.5)


def test_word_limit_must_be_positive():
    with pytest.raises(ValidationError):
        ApplicationSection(
            id="S001", title="t", instructions="i", word_limit=0, quote=None
        )
    with pytest.raises(ValidationError):
        ApplicationSection(
            id="S001", title="t", instructions="i", word_limit=-3, quote=None
        )
    section = ApplicationSection(
        id="S001", title="t", instructions="i", word_limit=None, quote=None
    )
    assert section.word_limit is None


# --- P2.1 timestamps ------------------------------------------------------------


def test_naive_timestamps_are_rejected():
    with pytest.raises(ValidationError):
        make_source(supplied_at=datetime(2026, 9, 5, 12, 0))
    with pytest.raises(ValidationError):
        make_meta(generated_at=datetime(2026, 9, 5, 12, 0))


def test_aware_timestamps_are_normalized_to_utc():
    helsinki = datetime(2026, 9, 5, 15, 0, tzinfo=timezone.utc).astimezone()
    source = make_source(supplied_at=helsinki)
    assert source.supplied_at.tzinfo == timezone.utc
    assert source.supplied_at == helsinki


def test_json_timestamps_parse_and_round_trip():
    source = make_source()
    restored = SourceSnapshot.model_validate_json(source.model_dump_json())
    assert restored.supplied_at == TEST_NOW
    assert restored.supplied_at.tzinfo == timezone.utc


def test_deadline_date_field_accepts_iso_date():
    deadline = make_deadline(
        kind="date",
        at=None,
        on=date(2026, 10, 15),
    )
    assert deadline.on == date(2026, 10, 15)
    restored = Deadline.model_validate_json(deadline.model_dump_json())
    assert restored.on == date(2026, 10, 15)


# --- P2.1 currency ----------------------------------------------------------------


@pytest.mark.parametrize("valid", ["EUR", "USD", "GBP"])
def test_valid_currency_codes_are_accepted(valid):
    assert make_profile(currency=valid).currency == valid
    assert make_extraction(currency=valid).currency == valid


@pytest.mark.parametrize("invalid", ["eur", "EURO", "EU", "E1R", ""])
def test_invalid_currency_codes_are_rejected(invalid):
    with pytest.raises(ValidationError):
        make_profile(currency=invalid)


def test_extraction_currency_may_be_none():
    assert make_extraction(currency=None).currency is None


# --- P2.1 extra="forbid" ------------------------------------------------------------


def test_unknown_fields_are_rejected_everywhere():
    with pytest.raises(ValidationError):
        Fact(id="X", text="t", approved=True, provenance="p", is_synthetic=True, extra_field=1)
    with pytest.raises(ValidationError):
        make_profile(unexpected="x")
    with pytest.raises(ValidationError):
        make_source(unexpected="x")
    with pytest.raises(ValidationError):
        make_extraction(unexpected="x")
    with pytest.raises(ValidationError):
        DraftSectionResult(
            id="D001", title="t", text="x", fact_ids=[], placeholders=[], word_limit=100
        )


# --- P2.2 OrganizationProfile bounds --------------------------------------------------


def test_valid_profile_is_accepted():
    profile = make_profile()
    assert profile.is_synthetic is True
    assert profile.requested_amount_minor == 400000
    assert profile.currency == "EUR"


def test_duplicate_fact_ids_are_input_invalid():
    with pytest.raises(AppError) as excinfo:
        make_profile(facts=[make_fact(), make_fact()])
    assert excinfo.value.code == "INPUT_INVALID"


def test_distinct_fact_ids_are_accepted():
    profile = make_profile(
        facts=[make_fact(id="ORG_ENTITY"), make_fact(id="ORG_GEOGRAPHY")]
    )
    assert len(profile.facts) == 2


def test_fact_count_bound_is_input_invalid():
    facts = [make_fact(id=f"F{i:03d}") for i in range(MAX_PROFILE_FACTS + 1)]
    with pytest.raises(AppError) as excinfo:
        make_profile(facts=facts)
    assert excinfo.value.code == "INPUT_INVALID"
    assert len(make_profile(facts=facts[:MAX_PROFILE_FACTS]).facts) == MAX_PROFILE_FACTS


def test_budget_line_count_bound_is_input_invalid():
    lines = [
        BudgetLine(label=f"line {i}", amount_minor=100)
        for i in range(MAX_PROFILE_BUDGET_LINES + 1)
    ]
    with pytest.raises(AppError) as excinfo:
        make_profile(budget_lines=lines)
    assert excinfo.value.code == "INPUT_INVALID"
    assert (
        len(make_profile(budget_lines=lines[:MAX_PROFILE_BUDGET_LINES]).budget_lines)
        == MAX_PROFILE_BUDGET_LINES
    )


def _profile_text_total(profile: OrganizationProfile) -> int:
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
    total += sum(len(f.text) + len(f.provenance) for f in profile.facts)
    total += sum(len(line.label) for line in profile.budget_lines)
    return total


def test_aggregate_text_bound_is_input_invalid():
    base = make_profile(facts=[], budget_lines=[], mission="")
    rest = _profile_text_total(base)
    exact = make_profile(
        facts=[], budget_lines=[], mission="m" * (MAX_PROFILE_TEXT_CHARS - rest)
    )
    assert _profile_text_total(exact) == MAX_PROFILE_TEXT_CHARS
    with pytest.raises(AppError) as excinfo:
        make_profile(
            facts=[],
            budget_lines=[],
            mission="m" * (MAX_PROFILE_TEXT_CHARS - rest + 1),
        )
    assert excinfo.value.code == "INPUT_INVALID"


def test_fact_text_counts_toward_the_aggregate_bound():
    base = make_profile(mission="")
    rest = _profile_text_total(make_profile(facts=[], budget_lines=[], mission=""))
    budget = MAX_PROFILE_TEXT_CHARS - rest
    provenance_len = len("fixture")
    with pytest.raises(AppError) as excinfo:
        make_profile(
            mission="",
            facts=[
                make_fact(text="t" * (budget - provenance_len + 1)),
            ],
        )
    assert excinfo.value.code == "INPUT_INVALID"


# --- P2.2 SourceSnapshot provenance rules ----------------------------------------------


def test_synthetic_source_requires_known_fixture_id():
    assert DEMO_FIXTURE_IDS == {
        "eligible",
        "excluded",
        "unclear",
        "expired",
        "wrong_region",
    }
    for fixture_id in sorted(DEMO_FIXTURE_IDS):
        assert make_source(fixture_id=fixture_id).fixture_id == fixture_id
    with pytest.raises(ValidationError):
        make_source(fixture_id="invented_case")
    with pytest.raises(ValidationError):
        make_source(fixture_id=None)


def test_synthetic_source_carries_no_source_url():
    with pytest.raises(ValidationError):
        make_source(source_url="https://example.test/fake")


def test_synthetic_source_must_be_flagged_synthetic():
    with pytest.raises(ValidationError):
        make_source(is_synthetic=False)


@pytest.mark.parametrize("kind", ["fetched", "pasted"])
def test_fetched_and_pasted_sources_have_no_fixture_id(kind):
    source = make_source(
        kind=kind,
        fixture_id=None,
        source_url="https://avustukset.hel.fi/page" if kind == "fetched" else None,
        fetched_at=TEST_NOW if kind == "fetched" else None,
        content_type="text/html" if kind == "fetched" else None,
        is_synthetic=False,
    )
    assert source.fixture_id is None
    with pytest.raises(ValidationError):
        make_source(kind=kind, fixture_id="eligible")


@pytest.mark.parametrize("kind", ["synthetic", "pasted"])
def test_fetched_at_requires_fetched_kind(kind):
    with pytest.raises(ValidationError):
        make_source(kind=kind, fixture_id="eligible" if kind == "synthetic" else None, fetched_at=TEST_NOW)


def test_source_text_is_bounded_by_max_source_chars():
    with pytest.raises(ValidationError):
        make_source(text="a" * (MAX_SOURCE_CHARS + 1))
    assert len(make_source(text="a" * MAX_SOURCE_CHARS).text) == MAX_SOURCE_CHARS


# --- P2.2 Deadline rules ------------------------------------------------------------------


def test_at_is_only_valid_with_datetime_kind():
    for kind in ("date", "rolling", "unknown"):
        with pytest.raises(ValidationError):
            make_deadline(kind=kind, on=None)


def test_on_is_only_valid_with_date_kind():
    for kind in ("datetime", "rolling", "unknown"):
        with pytest.raises(ValidationError):
            make_deadline(kind=kind, at=None, on=date(2026, 10, 15))


@pytest.mark.parametrize("kind", ["rolling", "unknown"])
def test_rolling_and_unknown_deadlines_carry_neither_at_nor_on(kind):
    deadline = make_deadline(kind=kind, at=None, on=None)
    assert deadline.at is None
    assert deadline.on is None


# --- P2.2 ExtractionResult -------------------------------------------------------------------


def test_amount_range_must_be_ordered():
    with pytest.raises(ValidationError):
        make_extraction(amount_min_minor=600000, amount_max_minor=500000)
    result = make_extraction(amount_min_minor=100000, amount_max_minor=500000)
    assert result.amount_min_minor <= result.amount_max_minor


@pytest.mark.parametrize(
    ("minimum", "maximum"), [(None, 500000), (100000, None), (None, None)]
)
def test_amount_bounds_may_be_independently_absent(minimum, maximum):
    result = make_extraction(amount_min_minor=minimum, amount_max_minor=maximum)
    assert result.amount_min_minor == minimum
    assert result.amount_max_minor == maximum


def test_provider_output_lists_are_required_not_defaulted():
    payload = make_extraction().model_dump()
    del payload["focus_areas"]
    with pytest.raises(ValidationError):
        ExtractionResult(**payload)
    result = make_extraction(
        focus_areas=[], fit_reasons=[], missing_information=[], requirements=[],
        application_sections=[],
    )
    assert result.focus_areas == []
    assert result.requirements == []


def test_extracted_requirement_lists_are_required():
    with pytest.raises(ValidationError):
        ExtractedRequirement(
            dimension="other",
            description="d",
            quote=None,
            suggested_status="unknown",
            reason="r",
        )


# --- P2.2 Requirement ----------------------------------------------------------------------------


def test_requirement_extends_extracted_requirement_with_app_fields():
    requirement = make_requirement()
    assert isinstance(requirement, ExtractedRequirement)
    assert requirement.id == "R001"
    assert requirement.evidence_valid is True
    assert requirement.dimension is Dimension.applicant_type
    assert requirement.suggested_fact_ids == ["ORG_ENTITY", "ORG_GEOGRAPHY"]


def test_requirement_rejects_invalid_evidence_flag():
    with pytest.raises(ValidationError):
        make_requirement(evidence_valid="true")


# --- P2.2 GenerationMeta ----------------------------------------------------------------------------


def test_authored_meta_claims_no_model_or_response_id():
    meta = make_meta(origin="authored", model_id=None, response_id=None)
    assert meta.origin is OutputOrigin.authored
    with pytest.raises(ValidationError):
        make_meta(origin="authored", response_id=None, model_id="gemini-3.5-flash")
    with pytest.raises(ValidationError):
        make_meta(origin="authored", model_id=None, response_id="resp-1")


@pytest.mark.parametrize("origin", ["live", "recorded"])
def test_live_and_recorded_meta_may_carry_identifiers(origin):
    meta = make_meta(origin=origin)
    assert meta.model_id == "gemini-3.5-flash"
    assert meta.response_id == "resp-1"


def test_meta_token_counts_may_be_absent():
    meta = make_meta(input_tokens=None, output_tokens=None)
    assert meta.input_tokens is None


# --- P2.2 Grant -------------------------------------------------------------------------------------


def test_grant_rejects_duplicate_requirement_ids():
    with pytest.raises(ValidationError):
        make_grant(requirements=[make_requirement(), make_requirement()])


def test_grant_accepts_distinct_requirement_ids():
    grant = make_grant(
        requirements=[make_requirement(id="R001"), make_requirement(id="R002")]
    )
    assert [requirement.id for requirement in grant.requirements] == ["R001", "R002"]


def test_grant_metadata_evidence_values_must_be_strict_booleans():
    with pytest.raises(ValidationError):
        make_grant(metadata_evidence_valid={"foundation": "yes"})


# --- P2.2 ReviewSet and Assessment -----------------------------------------------------------------------


def test_review_set_rejects_duplicate_requirement_ids():
    with pytest.raises(ValidationError):
        make_review_set(items=[make_review(), make_review()])


def test_assessment_review_ids_must_exactly_match_requirement_ids():
    grant = make_grant(
        requirements=[make_requirement(id="R001"), make_requirement(id="R002")]
    )
    with pytest.raises(ValidationError):
        make_assessment(
            grant_snapshot=grant,
            reviews=make_review_set(items=[make_review(requirement_id="R001")]),
        )
    with pytest.raises(ValidationError):
        make_assessment(
            grant_snapshot=grant,
            reviews=make_review_set(
                items=[
                    make_review(requirement_id="R001"),
                    make_review(requirement_id="R002"),
                    make_review(requirement_id="R003"),
                ]
            ),
        )


def test_assessment_accepts_exact_review_match_in_any_order():
    grant = make_grant(
        requirements=[make_requirement(id="R001"), make_requirement(id="R002")]
    )
    assessment = make_assessment(
        grant_snapshot=grant,
        reviews=make_review_set(
            items=[
                make_review(requirement_id="R002"),
                make_review(requirement_id="R001"),
            ]
        ),
    )
    assert {item.requirement_id for item in assessment.reviews.items} == {
        "R001",
        "R002",
    }


# --- P2.2 Draft records ------------------------------------------------------------------------------------


def test_draft_rejects_duplicate_section_ids():
    with pytest.raises(ValidationError):
        make_draft(
            sections=[
                DraftSection(id="D001", title="a", generated_text="x"),
                DraftSection(id="D001", title="b", generated_text="y"),
            ]
        )


def test_draft_section_application_defaults():
    section = DraftSection(id="D001", title="Summary", generated_text="text")
    assert section.edited_text is None
    assert section.fact_ids == []
    assert section.placeholders == []
    assert section.word_limit is None


def test_draft_section_result_is_provider_only():
    result = DraftSectionResult(
        id="D001", title="Summary", text="t", fact_ids=["ORG_ENTITY"], placeholders=[]
    )
    assert result.fact_ids == ["ORG_ENTITY"]
    with pytest.raises(ValidationError):
        DraftSectionResult(id="D001", title="t", text="x", placeholders=[])
    with pytest.raises(ValidationError):
        DraftResult(sections=[result], unexpected=True)


# --- P2.2 AssessmentRecord --------------------------------------------------------------------------------------


def test_assessment_record_defaults():
    record = AssessmentRecord(assessment=make_assessment())
    assert record.draft is None
    assert record.draft_revision == 0


def test_assessment_record_revision_must_be_nonnegative_strict_int():
    with pytest.raises(ValidationError):
        AssessmentRecord(assessment=make_assessment(), draft_revision=-1)
    with pytest.raises(ValidationError):
        AssessmentRecord(assessment=make_assessment(), draft_revision=1.0)
    with pytest.raises(ValidationError):
        AssessmentRecord(assessment=make_assessment(), draft_revision=True)


def test_assessment_record_accepts_draft():
    record = AssessmentRecord(
        assessment=make_assessment(), draft=make_draft(), draft_revision=3
    )
    assert record.draft is not None
    assert record.draft_revision == 3


# --- JSON round-trip and serialization -------------------------------------------------------------------------------


def test_full_record_graph_round_trips_through_json():
    record = AssessmentRecord(
        assessment=make_assessment(), draft=make_draft(), draft_revision=2
    )
    restored = AssessmentRecord.model_validate_json(record.model_dump_json())
    assert restored == record


def test_json_dump_uses_snake_case_and_plain_enum_strings():
    payload = make_assessment().model_dump(mode="json")
    assert payload["grant_snapshot"]["extraction"]["mission_fit"] == "high"
    assert payload["grant_snapshot"]["source"]["kind"] == "synthetic"
    assert payload["decision"] == "pursue"
    assert payload["reviews"]["items"][0]["requirement_id"] == "R001"
    assert payload["grant_snapshot"]["source"]["supplied_at"] == "2026-09-05T12:00:00Z"


def test_hash_stability_input_dictionary_order_does_not_matter():
    first = make_assessment().model_dump(mode="json")
    second = make_assessment().model_dump(mode="json")
    assert first == second
