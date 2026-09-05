"""Shared Pydantic record models and enums (P2.1-P2.2).

Serialization rules (P2.1):

* Pydantic v2 ``BaseModel`` with ``ConfigDict(extra="forbid")`` on every
  record; JSON field names are snake_case.
* Application-owned list/dict defaults use ``Field(default_factory=...)``.
  Provider-output schemas (:class:`ExtractionResult` and its nested types,
  :class:`DraftResult`, :class:`DraftSectionResult`) keep every field
  required, using explicit empty lists/nulls when no value is known.
* All integer and boolean fields use :data:`pydantic.StrictInt` and
  :data:`pydantic.StrictBool` with nonnegative/positive bounds: ``true`` is
  not money, ``400000.0`` is not an integer amount, and ``"false"`` is not a
  boolean. Global strict mode is deliberately not enabled so ISO
  dates/timestamps from JSON still parse.
* Schema-version fields accept only an actual integer ``1`` via a
  before-validator plus ``Literal[1]``; boolean ``true`` is not a schema
  version.
* All timestamps are timezone-aware and normalized to UTC; naive timestamps
  are rejected. Dates are ISO ``YYYY-MM-DD``.
* Currency is an uppercase three-letter code or ``None``. Money is a
  nonnegative integer number of minor units; floats and automatic currency
  conversion are never used.

Record constraints (P2.2) enforced here: unique fact/requirement/review/
section IDs; persisted assessment review IDs exactly match the snapshot's
requirement IDs; source text bounded by ``MAX_SOURCE_CHARS``; profile text
bounded to 10,000 characters in aggregate, 50 facts, and 20 budget lines
(rejected with ``INPUT_INVALID``, never silently cropped); positive word
limits; ``amount_min_minor <= amount_max_minor`` when both exist;
``fetched_at`` only for ``kind="fetched"``; synthetic sources require one of
the five known fixture IDs and carry no source URL; fetched/pasted sources
have ``fixture_id=None``; ``at`` only for datetime deadlines and ``on`` only
for date deadlines; authored generation output claims no model/response ID.

Requirement/application-section count limits (40/12) are deliberately NOT
model constraints: they are enforced in application code after parsing so an
oversized provider response raises ``AI_LIMIT`` instead of a generic
list-length validation failure (P3B.2).
"""

from datetime import date, datetime, timezone
from enum import StrEnum, unique
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from errors import AppError
from settings import MAX_SOURCE_CHARS, SCHEMA_VERSION

MAX_PROFILE_TEXT_CHARS = 10000
MAX_PROFILE_FACTS = 50
MAX_PROFILE_BUDGET_LINES = 20

DEMO_FIXTURE_IDS = frozenset({
    "eligible",
    "excluded",
    "unclear",
    "expired",
    "wrong_region",
})


# --- P2.1 string-literal enums ---------------------------------------------


@unique
class SourceKind(StrEnum):
    synthetic = "synthetic"
    pasted = "pasted"
    fetched = "fetched"


@unique
class ReviewStatus(StrEnum):
    meets = "meets"
    fails = "fails"
    unknown = "unknown"


@unique
class Decision(StrEnum):
    pursue = "pursue"
    clarify = "clarify"
    skip = "skip"


@unique
class MissionFit(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    unknown = "unknown"


@unique
class Dimension(StrEnum):
    applicant_type = "applicant_type"
    geography = "geography"
    activity = "activity"
    funding = "funding"
    deadline = "deadline"
    other = "other"


@unique
class DeadlineKind(StrEnum):
    datetime = "datetime"
    date = "date"
    rolling = "rolling"
    unknown = "unknown"


@unique
class DraftKind(StrEnum):
    proposal = "proposal"
    clarification = "clarification"


@unique
class OutputOrigin(StrEnum):
    live = "live"
    recorded = "recorded"
    authored = "authored"


# --- P2.1 shared annotated field types --------------------------------------


def _require_actual_integer_one(value: object) -> object:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            "schema_version must be the actual integer 1; booleans, strings, "
            "and floats are not schema versions"
        )
    return value


SchemaVersion = Annotated[
    Literal[SCHEMA_VERSION], BeforeValidator(_require_actual_integer_one)
]


def _require_aware_normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            "timestamps must be timezone-aware; naive timestamps are rejected"
        )
    return value.astimezone(timezone.utc)


UtcDatetime = Annotated[datetime, AfterValidator(_require_aware_normalize_utc)]

CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]

Money = Annotated[StrictInt, Field(ge=0)]

TokenCount = Annotated[StrictInt, Field(ge=0)]

WordLimit = Annotated[StrictInt, Field(gt=0)]


class StrictRecord(BaseModel):
    """Base record: unknown fields are rejected everywhere."""

    model_config = ConfigDict(extra="forbid")


# --- P2.2 organization profile records --------------------------------------


class Fact(StrictRecord):
    id: str
    text: str
    approved: StrictBool
    provenance: str
    is_synthetic: StrictBool


class BudgetLine(StrictRecord):
    label: str
    amount_minor: Money


_PROFILE_TEXT_FIELDS = (
    "name",
    "entity_type",
    "country",
    "region",
    "mission",
    "project_title",
    "project_activity",
)


class OrganizationProfile(StrictRecord):
    schema_version: SchemaVersion = SCHEMA_VERSION
    is_synthetic: StrictBool
    name: str
    entity_type: str
    country: str
    region: str
    mission: str
    project_title: str
    project_activity: str
    requested_amount_minor: Money
    currency: CurrencyCode
    budget_lines: list[BudgetLine] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    profile_reviewed: StrictBool

    @model_validator(mode="after")
    def _check_bounds(self) -> "OrganizationProfile":
        fact_ids = [fact.id for fact in self.facts]
        if len(set(fact_ids)) != len(fact_ids):
            raise AppError("INPUT_INVALID", "profile fact IDs must be unique")
        if len(self.facts) > MAX_PROFILE_FACTS:
            raise AppError(
                "INPUT_INVALID",
                f"profiles are bounded to {MAX_PROFILE_FACTS} facts; "
                "approved facts are never silently omitted",
            )
        if len(self.budget_lines) > MAX_PROFILE_BUDGET_LINES:
            raise AppError(
                "INPUT_INVALID",
                f"profiles are bounded to {MAX_PROFILE_BUDGET_LINES} budget lines",
            )
        total_text = sum(len(getattr(self, name)) for name in _PROFILE_TEXT_FIELDS)
        total_text += sum(len(fact.text) + len(fact.provenance) for fact in self.facts)
        total_text += sum(len(line.label) for line in self.budget_lines)
        if total_text > MAX_PROFILE_TEXT_CHARS:
            raise AppError(
                "INPUT_INVALID",
                f"profile text is bounded to {MAX_PROFILE_TEXT_CHARS} characters "
                "in aggregate",
            )
        return self


# --- P2.2 source records -----------------------------------------------------


class SourceSnapshot(StrictRecord):
    schema_version: SchemaVersion = SCHEMA_VERSION
    kind: SourceKind
    fixture_id: str | None
    source_url: str | None
    text: str = Field(max_length=MAX_SOURCE_CHARS)
    source_hash: str
    supplied_at: UtcDatetime
    fetched_at: UtcDatetime | None
    content_type: str | None
    is_synthetic: StrictBool

    @model_validator(mode="after")
    def _check_provenance(self) -> "SourceSnapshot":
        if self.fetched_at is not None and self.kind != SourceKind.fetched:
            raise ValueError("fetched_at requires kind='fetched'")
        if self.kind == SourceKind.synthetic:
            if self.fixture_id not in DEMO_FIXTURE_IDS:
                raise ValueError(
                    "synthetic sources require one of the known fixture IDs: "
                    + ", ".join(sorted(DEMO_FIXTURE_IDS))
                )
            if self.source_url is not None:
                raise ValueError("synthetic sources carry no source URL")
            if not self.is_synthetic:
                raise ValueError(
                    "sources with kind='synthetic' must carry is_synthetic=true"
                )
        elif self.fixture_id is not None:
            raise ValueError("fetched and pasted sources have fixture_id=None")
        return self


# --- P2.2 extraction records (provider-output schemas) -----------------------


class QuotedValue(StrictRecord):
    value: str | None
    quote: str | None


class Deadline(StrictRecord):
    kind: DeadlineKind
    raw_text: str | None
    quote: str | None
    at: UtcDatetime | None
    on: date | None
    timezone: str | None

    @model_validator(mode="after")
    def _check_kind_fields(self) -> "Deadline":
        if self.at is not None and self.kind != DeadlineKind.datetime:
            raise ValueError("'at' is only valid with kind='datetime'")
        if self.on is not None and self.kind != DeadlineKind.date:
            raise ValueError("'on' is only valid with kind='date'")
        return self


class ExtractedRequirement(StrictRecord):
    dimension: Dimension
    description: str
    quote: str | None
    suggested_status: ReviewStatus
    suggested_fact_ids: list[str]
    reason: str


class ApplicationSection(StrictRecord):
    id: str
    title: str
    instructions: str
    word_limit: WordLimit | None
    quote: str | None


class ExtractionResult(StrictRecord):
    foundation: QuotedValue
    title: QuotedValue
    amount: QuotedValue
    amount_min_minor: Money | None
    amount_max_minor: Money | None
    currency: CurrencyCode | None
    focus_areas: list[str]
    deadline: Deadline
    requirements: list[ExtractedRequirement]
    application_sections: list[ApplicationSection]
    mission_fit: MissionFit
    fit_reasons: list[str]
    missing_information: list[str]
    coverage_incomplete: StrictBool

    @model_validator(mode="after")
    def _check_amount_range(self) -> "ExtractionResult":
        if (
            self.amount_min_minor is not None
            and self.amount_max_minor is not None
            and self.amount_min_minor > self.amount_max_minor
        ):
            raise ValueError("amount_min_minor must not exceed amount_max_minor")
        return self


class Requirement(ExtractedRequirement):
    """An extracted requirement plus application-assigned identity.

    ``id`` and ``evidence_valid`` are assigned by application code during
    assembly (P2.3); the provider never supplies them.
    """

    id: str
    evidence_valid: StrictBool


class GenerationMeta(StrictRecord):
    origin: OutputOrigin
    model_id: str | None
    prompt_version: str
    generated_at: UtcDatetime
    response_id: str | None
    input_tokens: TokenCount | None
    output_tokens: TokenCount | None

    @model_validator(mode="after")
    def _check_authored_claims(self) -> "GenerationMeta":
        if self.origin == OutputOrigin.authored and (
            self.model_id is not None or self.response_id is not None
        ):
            raise ValueError(
                "authored output must not claim a model ID or response ID"
            )
        return self


class Grant(StrictRecord):
    schema_version: SchemaVersion = SCHEMA_VERSION
    id: str
    source: SourceSnapshot
    extraction: ExtractionResult
    requirements: list[Requirement] = Field(default_factory=list)
    metadata_evidence_valid: dict[str, StrictBool] = Field(default_factory=dict)
    extraction_profile_hash: str
    extraction_meta: GenerationMeta
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "Grant":
        requirement_ids = [requirement.id for requirement in self.requirements]
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError("requirement IDs must be unique")
        return self


# --- P2.2 review and assessment records --------------------------------------


class RequirementReview(StrictRecord):
    requirement_id: str
    status: ReviewStatus
    reviewed: StrictBool
    fact_ids: list[str] = Field(default_factory=list)
    reason: str


class ReviewSet(StrictRecord):
    items: list[RequirementReview] = Field(default_factory=list)
    source_complete: StrictBool
    coverage_reviewed: StrictBool
    deadline_reviewed: StrictBool
    profile_reviewed: StrictBool
    application_instructions_reviewed: StrictBool
    mission_fit: MissionFit
    fit_reviewed: StrictBool

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "ReviewSet":
        review_ids = [item.requirement_id for item in self.items]
        if len(set(review_ids)) != len(review_ids):
            raise ValueError("review requirement IDs must be unique")
        return self


class Assessment(StrictRecord):
    schema_version: SchemaVersion = SCHEMA_VERSION
    id: str
    grant_id: str
    grant_snapshot: Grant
    profile_snapshot: OrganizationProfile
    profile_hash: str
    review_hash: str
    reviews: ReviewSet
    decision: Decision
    blockers: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    evaluated_at: UtcDatetime

    @model_validator(mode="after")
    def _check_review_coverage(self) -> "Assessment":
        requirement_ids = [
            requirement.id for requirement in self.grant_snapshot.requirements
        ]
        review_ids = [item.requirement_id for item in self.reviews.items]
        if sorted(review_ids) != sorted(requirement_ids):
            raise ValueError(
                "persisted assessment review IDs must exactly match the "
                "snapshot's requirement IDs"
            )
        return self


# --- P2.2 draft records -------------------------------------------------------


class DraftSection(StrictRecord):
    id: str
    title: str
    generated_text: str
    edited_text: str | None = None
    fact_ids: list[str] = Field(default_factory=list)
    placeholders: list[str] = Field(default_factory=list)
    word_limit: WordLimit | None = None


class Draft(StrictRecord):
    schema_version: SchemaVersion = SCHEMA_VERSION
    id: str
    assessment_id: str
    kind: DraftKind
    sections: list[DraftSection] = Field(default_factory=list)
    meta: GenerationMeta
    input_fingerprint: str
    is_synthetic: StrictBool

    @model_validator(mode="after")
    def _check_unique_ids(self) -> "Draft":
        section_ids = [section.id for section in self.sections]
        if len(set(section_ids)) != len(section_ids):
            raise ValueError("draft section IDs must be unique")
        return self


class DraftSectionResult(StrictRecord):
    """Provider drafting output for one section.

    Contains only provider-supplied fields; application code supplies draft
    IDs, edited fields, timestamps, word limits, and provenance.
    """

    id: str
    title: str
    text: str
    fact_ids: list[str]
    placeholders: list[str]


class DraftResult(StrictRecord):
    """Provider drafting output schema sent to Gemini (P2.2)."""

    sections: list[DraftSectionResult]


class AssessmentRecord(StrictRecord):
    """Repository readback wrapper supporting concurrent-edit checks."""

    assessment: Assessment
    draft: Draft | None = None
    draft_revision: Annotated[StrictInt, Field(ge=0)] = 0
