"""Canonical hashing, IDs, quote normalization, and extraction validation (P2.3).

Pure helpers used by every lane:

* :func:`normalize_for_quote` is exactly ``" ".join(text.split())``; case and
  punctuation are preserved. Empty quotes never match.
* :func:`hash_source` is SHA-256 of the normalized source UTF-8 bytes. The
  paragraph-preserving source text is kept separately for display.
* Canonical JSON hashing uses ``model_dump(mode="json")``,
  ``json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)``,
  then SHA-256. Facts are sorted by ID and review items by requirement ID
  before hashing; other lists preserve meaningful order. Profile and review
  hashes include every field/flag and no timestamps.
* :func:`grant_id` uses ``uuid.uuid5(uuid.NAMESPACE_URL, "grant-preflight:" + key)``
  with the key read from the shared source model: the canonical URL
  (fragment stripped) for fetched/pasted URL sources, ``"text:" + source_hash``
  without a URL, and ``"fixture:" + fixture_id`` for synthetic sources.
* Requirement IDs ``R001``... are assigned in extraction order and
  application-section IDs ``S001``... in supplied order, replacing
  model-supplied IDs during assembly before the extraction hash is computed or
  the normalized result is stored in ``Grant.extraction``. Re-normalizing
  already normalized IDs is idempotent.
* :func:`draft_fingerprint` includes the grant ID, source hash, extraction
  hash, profile hash, review hash, draft kind, selected model ID, extraction
  prompt version, and draft prompt version. It excludes event IDs,
  output-origin labels, and timestamps so a replay can match equivalent
  reviewed inputs, but a different extraction of the same source cannot reuse
  an old draft.
* :func:`validate_extraction` is invoked exactly once per provider result to
  normalize IDs, check quotes, and assemble the :class:`Grant`. Quote
  validation sets evidence flags; it never silently erases invalid
  requirements. Unknown fact references become unknown suggestions.

``Grant.metadata_evidence_valid`` uses the fixed keys ``foundation``,
``title``, ``amount``, and ``deadline``, plus ``section:S001`` etc. for
application instructions. A value is true only when its nonempty quote
matches the source; metadata without evidence is displayed as unverified.
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from models import (
    DraftKind,
    ExtractionResult,
    GenerationMeta,
    Grant,
    OrganizationProfile,
    Requirement,
    ReviewSet,
    ReviewStatus,
    SourceKind,
    SourceSnapshot,
)
from settings import DRAFT_PROMPT_VERSION

GRANT_ID_PREFIX = "grant-preflight:"


def normalize_for_quote(text: str) -> str:
    """Collapse all whitespace runs to single spaces and strip the ends.

    Exactly ``" ".join(text.split())``; case and punctuation are preserved.
    """
    return " ".join(text.split())


def hash_source(text: str) -> str:
    """SHA-256 hex digest of the normalized source text UTF-8 bytes."""
    return hashlib.sha256(normalize_for_quote(text).encode("utf-8")).hexdigest()


def hash_profile(profile: OrganizationProfile) -> str:
    """Canonical JSON SHA-256 of every profile field, facts sorted by ID."""
    payload = profile.model_dump(mode="json")
    payload["facts"] = sorted(payload["facts"], key=lambda fact: fact["id"])
    return _canonical_json_hash(payload)


def hash_reviews(reviews: ReviewSet) -> str:
    """Canonical JSON SHA-256 of all review flags/statuses/fit decisions.

    Items are sorted by requirement ID; no timestamps are included.
    """
    payload = reviews.model_dump(mode="json")
    payload["items"] = sorted(
        payload["items"], key=lambda item: item["requirement_id"]
    )
    return _canonical_json_hash(payload)


def hash_extraction(result: ExtractionResult) -> str:
    """Canonical JSON SHA-256 preserving requirement and section order."""
    return _canonical_json_hash(result.model_dump(mode="json"))


def grant_id(source: SourceSnapshot) -> str:
    """Deterministic UUID5 identity read from the shared source model."""
    if source.kind == SourceKind.synthetic:
        key = "fixture:" + source.fixture_id
    elif source.source_url is not None:
        key = _canonical_url(source.source_url)
    else:
        key = "text:" + source.source_hash
    return str(uuid.uuid5(uuid.NAMESPACE_URL, GRANT_ID_PREFIX + key))


def draft_fingerprint(
    grant: Grant,
    profile: OrganizationProfile,
    reviews: ReviewSet,
    kind: str,
) -> str:
    """Canonical hash of the reviewed inputs a draft depends on.

    Excludes event IDs, output-origin labels, and timestamps so a replay can
    match equivalent reviewed inputs, but a different extraction of the same
    source cannot reuse an old draft.
    """
    if kind not in {member.value for member in DraftKind}:
        raise ValueError(f"kind must be one of proposal, clarification; got {kind!r}")
    payload = {
        "grant_id": grant.id,
        "source_hash": grant.source.source_hash,
        "extraction_hash": hash_extraction(grant.extraction),
        "profile_hash": hash_profile(profile),
        "review_hash": hash_reviews(reviews),
        "draft_kind": kind,
        "model_id": grant.extraction_meta.model_id,
        "extraction_prompt_version": grant.extraction_meta.prompt_version,
        "draft_prompt_version": DRAFT_PROMPT_VERSION,
    }
    return _canonical_json_hash(payload)


def validate_extraction(
    source: SourceSnapshot,
    result: ExtractionResult,
    profile: OrganizationProfile,
    meta: GenerationMeta,
    now: datetime,
) -> Grant:
    """Normalize IDs, check quotes, and assemble the :class:`Grant`.

    Invoked exactly once per provider ``(result, meta)`` tuple. Section IDs
    are replaced with ``S001``... in supplied order before the normalized
    result is stored in ``Grant.extraction``; requirement IDs ``R001``... are
    assigned in extraction order. Quote validation sets evidence flags and
    never erases invalid requirements; unknown suggested fact references are
    dropped and downgrade the suggestion to ``unknown``.
    """
    normalized_sections = [
        section.model_copy(update={"id": f"S{index:03d}"})
        for index, section in enumerate(result.application_sections, start=1)
    ]
    normalized_extraction = result.model_copy(
        update={"application_sections": normalized_sections}
    )
    normalized_source = normalize_for_quote(source.text)
    known_fact_ids = {fact.id for fact in profile.facts}

    requirements: list[Requirement] = []
    for index, extracted in enumerate(normalized_extraction.requirements, start=1):
        known_suggestions = [
            fact_id
            for fact_id in extracted.suggested_fact_ids
            if fact_id in known_fact_ids
        ]
        suggested_status = extracted.suggested_status
        if len(known_suggestions) != len(extracted.suggested_fact_ids):
            suggested_status = ReviewStatus.unknown
        requirement_data: dict[str, Any] = extracted.model_dump()
        requirement_data["suggested_fact_ids"] = known_suggestions
        requirement_data["suggested_status"] = suggested_status
        requirement_data["id"] = f"R{index:03d}"
        requirement_data["evidence_valid"] = _quote_matches(
            extracted.quote, normalized_source
        )
        requirements.append(Requirement(**requirement_data))

    metadata_evidence_valid = {
        "foundation": _quote_matches(
            normalized_extraction.foundation.quote, normalized_source
        ),
        "title": _quote_matches(normalized_extraction.title.quote, normalized_source),
        "amount": _quote_matches(normalized_extraction.amount.quote, normalized_source),
        "deadline": _quote_matches(
            normalized_extraction.deadline.quote, normalized_source
        ),
    }
    for section in normalized_sections:
        metadata_evidence_valid[f"section:{section.id}"] = _quote_matches(
            section.quote, normalized_source
        )

    return Grant(
        id=grant_id(source),
        source=source,
        extraction=normalized_extraction,
        requirements=requirements,
        metadata_evidence_valid=metadata_evidence_valid,
        extraction_profile_hash=hash_profile(profile),
        extraction_meta=meta,
        created_at=now,
        updated_at=now,
    )


def _canonical_json_hash(payload: Any) -> str:
    serialized = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _canonical_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _quote_matches(quote: str | None, normalized_source: str) -> bool:
    if quote is None:
        return False
    normalized_quote = normalize_for_quote(quote)
    if not normalized_quote:
        return False
    return normalized_quote in normalized_source
