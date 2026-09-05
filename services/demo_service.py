"""Recorded/authored demo provider and canonical fixture-profile builder.

P2.4 implements :func:`build_demo_profile`, the single canonical
fixture-profile builder for tests, public loading, smoke scripts, and capture
validation. It loads the fixed fictional profile from
``data/demo_profile.json``, performs the deterministic history mapping from
:mod:`services.salesforce_service`, and returns detached data with all
review/fact approvals set to the requested value. Callers must not
independently reconstruct the profile.

The fictional profile is always synthetic: ``is_synthetic`` is not an editable
checkbox, and fact approval never removes ``is_synthetic`` or ``provenance``.
The shipped public fixture is pre-reviewed (``approved=True``); operator mode
initializes approvals false (``approved=False``) and requires explicit user
confirmation before live generation.

The P2.5 demo-case/recording loaders and the P3D.1-P3D.2 ``DemoService``
provider are added by their own work units; ``DemoService`` raises
``NotImplementedError`` until then.
"""

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from errors import AppError
from models import OrganizationProfile
from services.salesforce_service import load_npsp_data, map_history_facts
from settings import PROJECT_ROOT

DEMO_PROFILE_PATH = PROJECT_ROOT / "data" / "demo_profile.json"

#: Fixed automated-test clock and clearly labeled fixture-authorship
#: timestamp (P2.5). The running app uses actual current time; this is never
#: a claimed API request time.
FIXTURE_CLOCK = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


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
    try:
        payload = json.loads(DEMO_PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AppError(
            "FIXTURE_MISMATCH",
            "data/demo_profile.json is missing or not valid UTF-8 JSON",
        ) from error
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
