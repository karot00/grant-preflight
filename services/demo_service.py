"""Recorded/authored demo provider and canonical fixture-profile builder.

P2.4 implements :func:`build_demo_profile`, the single canonical
fixture-profile builder for tests, public loading, smoke scripts, and capture
validation. It loads the fixed fictional profile from ``data/demo_profile.json``,
performs the deterministic history mapping from
:mod:`services.salesforce_service`, and returns detached data with all
review/fact approvals set to the requested value. Callers must not
independently reconstruct the profile.

P2.5 implements the five deterministic funding cases: :func:`load_demo_cases`
validates ``data/demo_cases.json``, resolves each ``source_file`` only under
``data/source_texts``, builds the synthetic :class:`SourceSnapshot` and the
assembled :class:`Grant` through :func:`services.evidence.validate_extraction`
with clearly labeled authored metadata at :data:`FIXTURE_CLOCK`, validates the
authored reviewed :class:`ReviewSet` against the normalized requirement IDs,
derives the unreviewed variant, and builds the authored :class:`Draft` with
deterministic fixture-authorship IDs and an exact fingerprint.
:func:`load_demo_recordings` validates ``data/demo_recordings.json`` (exactly
one bundle per case; duplicate case IDs, extraction lookup keys, or draft
fingerprints are rejected) and :func:`validate_recording_bundle` applies every
P2.5 exact-baseline check, rejecting mismatches with ``FIXTURE_MISMATCH``.
This deliberately excludes edited/private operator profiles even if inherited
synthetic flags remain true.

The fictional profile is always synthetic: ``is_synthetic`` is not an editable
checkbox, and fact approval never removes ``is_synthetic`` or ``provenance``.
The shipped public fixture is pre-reviewed (``approved=True``); operator mode
initializes approvals false (``approved=False``) and requires explicit user
confirmation before live generation. Authored fixtures are never labeled as
Gemini results.

The P3D.1-P3D.2 ``DemoService`` recorded provider (extraction/draft lookup
and replay rebinding) is implemented in Phase 3, Lane D and raises
``NotImplementedError`` until then.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from errors import AppError
from models import (
    DEMO_FIXTURE_IDS,
    Decision,
    Draft,
    DraftKind,
    DraftResult,
    DraftSection,
    ExtractionResult,
    GenerationMeta,
    Grant,
    MissionFit,
    OrganizationProfile,
    RequirementReview,
    ReviewSet,
    ReviewStatus,
    SchemaVersion,
    SourceSnapshot,
    StrictRecord,
)
from services.evidence import (
    draft_fingerprint,
    hash_profile,
    hash_source,
    validate_extraction,
)
from services.salesforce_service import load_npsp_data, map_history_facts
from settings import DRAFT_PROMPT_VERSION, EXTRACTION_PROMPT_VERSION, PROJECT_ROOT

DEMO_PROFILE_PATH = PROJECT_ROOT / "data" / "demo_profile.json"
DEMO_CASES_PATH = PROJECT_ROOT / "data" / "demo_cases.json"
DEMO_RECORDINGS_PATH = PROJECT_ROOT / "data" / "demo_recordings.json"
SOURCE_TEXTS_DIR = PROJECT_ROOT / "data" / "source_texts"

#: Fixed automated-test clock and clearly labeled fixture-authorship
#: timestamp (P2.5). The running app uses actual current time; this is never
#: a claimed API request time.
FIXTURE_CLOCK = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

ALLOWED_SOURCE_FILES = frozenset(
    f"{fixture_id}.txt" for fixture_id in sorted(DEMO_FIXTURE_IDS)
)

#: The six default proposal section IDs/titles (P3B.6), used when the source
#: supplies no funder-specific application sections.
GENERIC_PROPOSAL_SECTIONS: tuple[tuple[str, str], ...] = (
    ("executive_summary", "Executive Summary"),
    ("project_goals", "Project Goals"),
    ("target_group", "Target Group"),
    ("activities_timeline", "Activities and Timeline"),
    ("expected_impact", "Expected Impact"),
    ("budget_justification", "Budget Justification"),
)

CLARIFICATION_SECTION_ID = "clarification"
CLARIFICATION_MAX_WORDS = 150
GENERIC_PROPOSAL_MAX_TOTAL_WORDS = 1400
FUNDER_SPECIFIC_MAX_TOTAL_WORDS = 6000


# --- P2.4 canonical fixture-profile builder -----------------------------------


def build_demo_profile(*, approved: bool) -> OrganizationProfile:
    """Build the canonical fictional demo profile with the requested approvals.

    Loads ``data/demo_profile.json``, appends the deterministic synthetic
    history facts (``HIST_WORKSHOPS``, ``HIST_ATTENDANCE``) mapped from
    ``salesforce_npsp_data.json``, and sets every fact approval and
    ``profile_reviewed`` to ``approved``. Returns freshly parsed, detached
    data on every call; approval never clears ``is_synthetic`` or
    ``provenance``.
    """
    base = _load_base_profile()
    history_facts = map_history_facts(load_npsp_data())

    combined_ids = [fact.id for fact in (*base.facts, *history_facts)]
    duplicates = sorted({i for i in combined_ids if combined_ids.count(i) > 1})
    if duplicates:
        raise AppError(
            "FIXTURE_MISMATCH",
            "demo profile and history facts must use disjoint stable IDs; "
            f"duplicates: {', '.join(duplicates)}",
        )

    payload: dict[str, Any] = base.model_dump(mode="json")
    payload["facts"] = [
        {**fact.model_dump(mode="json"), "approved": approved}
        for fact in (*base.facts, *history_facts)
    ]
    payload["profile_reviewed"] = approved
    try:
        return OrganizationProfile.model_validate(payload)
    except ValidationError as error:
        raise AppError(
            "FIXTURE_MISMATCH",
            "the combined demo profile does not satisfy the organization "
            "profile contract",
        ) from error


def _load_base_profile() -> OrganizationProfile:
    payload = _read_json(DEMO_PROFILE_PATH)
    try:
        profile = OrganizationProfile.model_validate(payload)
    except ValidationError as error:
        raise AppError(
            "FIXTURE_MISMATCH",
            "data/demo_profile.json does not satisfy the organization profile "
            "contract",
        ) from error
    if not profile.is_synthetic:
        raise AppError(
            "FIXTURE_MISMATCH",
            "the shipped demo profile must be synthetic; a real organization "
            "identity is never claimed",
        )
    return profile


# --- P2.5 demo cases -------------------------------------------------------------


class DemoCase(StrictRecord):
    """One entry of ``data/demo_cases.json`` (fixed P2.5 file shape)."""

    case_id: str
    source_file: str
    expected_decision: Decision
    authored_extraction: ExtractionResult
    authored_reviews: ReviewSet
    authored_draft_result: DraftResult | None


class DemoCasesFile(StrictRecord):
    schema_version: SchemaVersion
    cases: list[DemoCase]


@dataclass(frozen=True)
class LoadedDemoCase:
    """A demo case assembled into coherent application records.

    ``reviewed_reviews`` is the authored reviewed baseline;
    ``unreviewed_reviews`` is the derived variant whose review flags are all
    false. ``draft`` is the authored example draft, or ``None`` when the case
    has no ``authored_draft_result``.
    """

    case_id: str
    expected_decision: Decision
    source: SourceSnapshot
    grant: Grant
    reviewed_reviews: ReviewSet
    unreviewed_reviews: ReviewSet
    draft: Draft | None


def load_demo_cases() -> list[LoadedDemoCase]:
    """Load, validate, and assemble the five deterministic funding cases."""
    cases_file = _parse_fixture(
        _read_json(DEMO_CASES_PATH),
        DemoCasesFile,
        "data/demo_cases.json does not match the demo-case fixture shape",
    )
    case_ids = [case.case_id for case in cases_file.cases]
    if len(set(case_ids)) != len(case_ids):
        raise AppError("FIXTURE_MISMATCH", "demo cases must have unique case IDs")
    if set(case_ids) != set(DEMO_FIXTURE_IDS):
        raise AppError(
            "FIXTURE_MISMATCH",
            "demo_cases.json must contain exactly the five known cases: "
            + ", ".join(sorted(DEMO_FIXTURE_IDS)),
        )
    profile = build_demo_profile(approved=True)
    return [build_loaded_case(case, profile) for case in cases_file.cases]


def build_loaded_case(
    case: DemoCase, profile: OrganizationProfile
) -> LoadedDemoCase:
    """Assemble one validated demo case into coherent application records.

    Builds the synthetic source snapshot, the grant through
    ``validate_extraction`` with authored metadata at ``FIXTURE_CLOCK``, the
    reviewed/unreviewed review sets, and the authored draft (if any) with
    deterministic fixture-authorship IDs. Never claims an API request time.
    """
    if case.source_file not in ALLOWED_SOURCE_FILES:
        raise AppError(
            "FIXTURE_MISMATCH",
            "source_file must be one of "
            f"{', '.join(sorted(ALLOWED_SOURCE_FILES))}; got {case.source_file!r}",
        )
    if (
        case.case_id != Path(case.source_file).stem
        or case.case_id not in DEMO_FIXTURE_IDS
    ):
        raise AppError(
            "FIXTURE_MISMATCH",
            "case_id must equal the source-file basename and be one of the "
            "five known fixture IDs",
        )

    text = _read_text(SOURCE_TEXTS_DIR / case.source_file)
    source = SourceSnapshot(
        kind="synthetic",
        fixture_id=case.case_id,
        source_url=None,
        text=text,
        source_hash=hash_source(text),
        supplied_at=FIXTURE_CLOCK,
        fetched_at=None,
        content_type=None,
        is_synthetic=True,
    )
    authored_meta = GenerationMeta(
        origin="authored",
        model_id=None,
        prompt_version=EXTRACTION_PROMPT_VERSION,
        generated_at=FIXTURE_CLOCK,
        response_id=None,
        input_tokens=None,
        output_tokens=None,
    )
    grant = validate_extraction(
        source, case.authored_extraction, profile, authored_meta, FIXTURE_CLOCK
    )
    _require_review_ids_match(grant, case.authored_reviews, case.case_id)
    unreviewed = build_unreviewed_reviews(grant)
    draft = (
        _build_authored_draft(case, grant, profile)
        if case.authored_draft_result is not None
        else None
    )
    return LoadedDemoCase(
        case_id=case.case_id,
        expected_decision=case.expected_decision,
        source=source,
        grant=grant,
        reviewed_reviews=case.authored_reviews,
        unreviewed_reviews=unreviewed,
        draft=draft,
    )


def build_unreviewed_reviews(grant: Grant) -> ReviewSet:
    """Derive the unreviewed variant: every review flag false.

    Each requirement row becomes ``unknown``/``reviewed=false`` with empty
    fact IDs and the reason ``Not reviewed``, matching the P3B.4 fill
    convention; mission fit becomes ``unknown`` and fit_reviewed false.
    """
    return ReviewSet(
        items=[
            RequirementReview(
                requirement_id=requirement.id,
                status=ReviewStatus.unknown,
                reviewed=False,
                fact_ids=[],
                reason="Not reviewed",
            )
            for requirement in grant.requirements
        ],
        source_complete=False,
        coverage_reviewed=False,
        deadline_reviewed=False,
        profile_reviewed=False,
        application_instructions_reviewed=False,
        mission_fit=MissionFit.unknown,
        fit_reviewed=False,
    )


def _build_authored_draft(
    case: DemoCase, grant: Grant, profile: OrganizationProfile
) -> Draft:
    result = case.authored_draft_result
    assert result is not None  # guaranteed by the caller
    kind = _draft_kind_for_decision(case.expected_decision, case.case_id)
    expected = _expected_sections(grant, kind)
    if [section.id for section in result.sections] != [
        section_id for section_id, _, _ in expected
    ]:
        raise AppError(
            "FIXTURE_MISMATCH",
            f"case {case.case_id!r}: authored {kind.value} draft must supply the "
            "prescribed section IDs exactly once each, in order: "
            + ", ".join(section_id for section_id, _, _ in expected),
        )

    known_fact_ids = {fact.id for fact in profile.facts}
    sections: list[DraftSection] = []
    total_words = 0
    for (section_id, expected_title, word_limit), section_result in zip(
        expected, result.sections, strict=True
    ):
        unknown = sorted(
            fact_id
            for fact_id in section_result.fact_ids
            if fact_id not in known_fact_ids
        )
        if unknown:
            raise AppError(
                "FIXTURE_MISMATCH",
                f"case {case.case_id!r}: authored draft section {section_id!r} "
                f"references unknown fact IDs: {', '.join(unknown)}",
            )
        if expected_title is not None and section_result.title != expected_title:
            raise AppError(
                "FIXTURE_MISMATCH",
                f"case {case.case_id!r}: section {section_id!r} must use the "
                f"prescribed title {expected_title!r}",
            )
        words = _word_count(section_result.text)
        total_words += words
        if word_limit is not None and words > word_limit:
            raise AppError(
                "FIXTURE_MISMATCH",
                f"case {case.case_id!r}: section {section_id!r} exceeds its "
                f"word limit of {word_limit}",
            )
        sections.append(
            DraftSection(
                id=section_result.id,
                title=section_result.title,
                generated_text=section_result.text,
                edited_text=None,
                fact_ids=list(section_result.fact_ids),
                placeholders=list(section_result.placeholders),
                word_limit=word_limit,
            )
        )

    if kind == DraftKind.clarification:
        if total_words > CLARIFICATION_MAX_WORDS:
            raise AppError(
                "FIXTURE_MISMATCH",
                f"case {case.case_id!r}: clarification email exceeds the "
                f"{CLARIFICATION_MAX_WORDS}-word hard maximum",
            )
    elif grant.extraction.application_sections:
        if total_words > FUNDER_SPECIFIC_MAX_TOTAL_WORDS:
            raise AppError(
                "FIXTURE_MISMATCH",
                f"case {case.case_id!r}: funder-specific proposal exceeds the "
                f"{FUNDER_SPECIFIC_MAX_TOTAL_WORDS}-word application safety maximum",
            )
    elif total_words > GENERIC_PROPOSAL_MAX_TOTAL_WORDS:
        raise AppError(
            "FIXTURE_MISMATCH",
            f"case {case.case_id!r}: generic proposal exceeds the "
            f"{GENERIC_PROPOSAL_MAX_TOTAL_WORDS}-word hard maximum",
        )

    draft_meta = GenerationMeta(
        origin="authored",
        model_id=None,
        prompt_version=DRAFT_PROMPT_VERSION,
        generated_at=FIXTURE_CLOCK,
        response_id=None,
        input_tokens=None,
        output_tokens=None,
    )
    return Draft(
        id=_fixture_uuid("authored-draft", case.case_id),
        assessment_id=_fixture_uuid("authored-assessment", case.case_id),
        kind=kind,
        sections=sections,
        meta=draft_meta,
        input_fingerprint=draft_fingerprint(
            grant, profile, case.authored_reviews, kind
        ),
        is_synthetic=True,
    )


def _draft_kind_for_decision(decision: Decision, case_id: str) -> DraftKind:
    if decision == Decision.pursue:
        return DraftKind.proposal
    if decision == Decision.clarify:
        return DraftKind.clarification
    raise AppError(
        "FIXTURE_MISMATCH",
        f"case {case_id!r} expects skip; drafts are blocked for skip decisions, "
        "so it must not carry an authored_draft_result",
    )


def _expected_sections(
    grant: Grant, kind: DraftKind
) -> list[tuple[str, str | None, int | None]]:
    """(section ID, prescribed title or None, word limit or None) in order."""
    if kind == DraftKind.clarification:
        return [(CLARIFICATION_SECTION_ID, None, None)]
    funder_sections = grant.extraction.application_sections
    if funder_sections:
        return [
            (section.id, section.title, section.word_limit)
            for section in funder_sections
        ]
    return [(section_id, title, None) for section_id, title in GENERIC_PROPOSAL_SECTIONS]


def _fixture_uuid(label: str, case_id: str) -> str:
    """Deterministic fixture-authorship ID.

    Runtime user actions create UUID4 event IDs (P2.3); fixture assembly must
    be deterministic, so authored drafts and their fixture assessments use
    UUID5 identities clearly derived from the case ID.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"grant-preflight:{label}:{case_id}"))


def _require_review_ids_match(
    grant: Grant, reviews: ReviewSet, case_id: str
) -> None:
    requirement_ids = sorted(requirement.id for requirement in grant.requirements)
    review_ids = sorted(item.requirement_id for item in reviews.items)
    if requirement_ids != review_ids:
        raise AppError(
            "FIXTURE_MISMATCH",
            f"case {case_id!r}: authored review IDs must exactly match the "
            "normalized requirement IDs "
            f"({', '.join(requirement_ids) or 'none'})",
        )


# --- P2.5 demo recordings ----------------------------------------------------------


class DemoRecording(StrictRecord):
    """One recorded bundle of ``data/demo_recordings.json`` (fixed shape)."""

    case_id: str
    source_assessment_id: str
    grant_snapshot: Grant
    profile_snapshot: OrganizationProfile
    reviews: ReviewSet
    draft: Draft


class DemoRecordingsFile(StrictRecord):
    schema_version: SchemaVersion
    recordings: list[DemoRecording]


def load_demo_recordings() -> list[DemoRecording]:
    """Load and fully validate the recorded demo bundles.

    Exactly one bundle per case is allowed in this release; duplicate case
    IDs, extraction lookup keys, or draft fingerprints are rejected rather
    than resolved by selecting an arbitrary record. Every bundle passes
    :func:`validate_recording_bundle` before it is returned.
    """
    recordings_file = _parse_fixture(
        _read_json(DEMO_RECORDINGS_PATH),
        DemoRecordingsFile,
        "data/demo_recordings.json does not match the recording fixture shape",
    )
    cases = load_demo_cases()
    validate_recording_collection(recordings_file.recordings, cases)
    return list(recordings_file.recordings)


def validate_recording_collection(
    recordings: list[DemoRecording], cases: list[LoadedDemoCase]
) -> None:
    """Reject duplicate case IDs, extraction lookup keys, or fingerprints."""
    cases_by_id = {case.case_id: case for case in cases}
    seen_case_ids: set[str] = set()
    seen_extraction_keys: set[tuple[str, str, str]] = set()
    seen_fingerprints: set[str] = set()
    for recording in recordings:
        if recording.case_id in seen_case_ids:
            raise AppError(
                "FIXTURE_MISMATCH",
                "exactly one recording bundle per case is allowed; duplicate "
                f"case ID {recording.case_id!r}",
            )
        seen_case_ids.add(recording.case_id)
        extraction_key = (
            recording.grant_snapshot.source.source_hash,
            recording.grant_snapshot.extraction_profile_hash,
            recording.grant_snapshot.extraction_meta.prompt_version,
        )
        if extraction_key in seen_extraction_keys:
            raise AppError(
                "FIXTURE_MISMATCH",
                "recordings must have distinct extraction lookup keys "
                "(source hash, profile hash, extraction prompt version)",
            )
        seen_extraction_keys.add(extraction_key)
        if recording.draft.input_fingerprint in seen_fingerprints:
            raise AppError(
                "FIXTURE_MISMATCH",
                "recordings must have distinct draft fingerprints",
            )
        seen_fingerprints.add(recording.draft.input_fingerprint)
        case = cases_by_id.get(recording.case_id)
        if case is None:
            raise AppError(
                "FIXTURE_MISMATCH",
                f"recording references unknown case {recording.case_id!r}",
            )
        validate_recording_bundle(recording, case)


def validate_recording_bundle(
    recording: DemoRecording, case: LoadedDemoCase
) -> None:
    """Apply every P2.5 exact-baseline check to one recording bundle.

    Rejects with ``FIXTURE_MISMATCH`` unless: the case ID equals the grant
    snapshot's fixture ID; the source text/hash exactly matches the authored
    fixture source; the profile hash equals the canonical approved demo
    profile hash; the extraction profile hash equals that hash; review IDs
    match the snapshot's normalized requirement IDs; the draft's assessment
    ID equals ``source_assessment_id``; and the draft fingerprint recomputes
    exactly from the captured snapshots and reviews. Edited/private operator
    profiles are excluded even if inherited synthetic flags remain true.
    """
    grant = recording.grant_snapshot

    def mismatch(reason: str) -> None:
        raise AppError(
            "FIXTURE_MISMATCH",
            f"recording for case {recording.case_id!r} failed bundle "
            f"validation: {reason}",
        )

    if recording.case_id != case.case_id:
        mismatch("the bundle does not belong to the compared case")
    if grant.source.fixture_id != recording.case_id:
        mismatch("grant snapshot fixture ID does not equal the case ID")
    if (
        grant.source.text != case.source.text
        or grant.source.source_hash != case.source.source_hash
    ):
        mismatch(
            "source text/hash does not exactly match the authored fixture source"
        )
    if grant.source.source_hash != hash_source(grant.source.text):
        mismatch("source hash does not match its own text")
    canonical_profile_hash = hash_profile(build_demo_profile(approved=True))
    if hash_profile(recording.profile_snapshot) != canonical_profile_hash:
        mismatch(
            "profile snapshot does not equal the canonical approved demo profile"
        )
    if grant.extraction_profile_hash != canonical_profile_hash:
        mismatch("extraction profile hash does not equal the canonical profile hash")
    requirement_ids = sorted(requirement.id for requirement in grant.requirements)
    review_ids = sorted(item.requirement_id for item in recording.reviews.items)
    if requirement_ids != review_ids:
        mismatch("review IDs do not match the snapshot's normalized requirement IDs")
    if recording.draft.assessment_id != recording.source_assessment_id:
        mismatch("draft assessment ID does not equal the source assessment ID")
    expected_fingerprint = draft_fingerprint(
        grant,
        recording.profile_snapshot,
        recording.reviews,
        recording.draft.kind,
    )
    if recording.draft.input_fingerprint != expected_fingerprint:
        mismatch(
            "draft fingerprint does not recompute from the captured snapshots "
            "and reviews"
        )


# --- P3D.1-P3D.2 recorded provider (not implemented before Phase 3, Lane D) -----


class DemoService:
    """Recorded/authored demo provider (P3D.1-P3D.2).

    Implements the same extraction/drafting method signatures as
    ``GeminiService`` with exact source-hash/profile-hash/prompt-version and
    fingerprint lookup, raising ``FIXTURE_MISMATCH`` on any mismatch. Not
    implemented before Phase 3, Lane D.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "DemoService is implemented in Phase 3, Lane D (P3D.1-P3D.2)"
        )


# --- shared fixture I/O helpers ----------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AppError(
            "FIXTURE_MISMATCH",
            f"fixture file {path.name} is missing or not valid UTF-8 JSON",
        ) from error


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise AppError(
            "FIXTURE_MISMATCH",
            f"fixture file {path.name} is missing or unreadable",
        ) from error


def _parse_fixture(payload: Any, model: type, message: str):
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        raise AppError("FIXTURE_MISMATCH", message) from error


def _word_count(text: str) -> int:
    return len(text.split())
