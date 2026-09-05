"""Synthetic Salesforce-style organization history adapter.

P2.4 implements the deterministic history mapping used by
``demo_service.build_demo_profile``: :func:`load_npsp_data` validates the
local ``data/salesforce_npsp_data.json`` fixture and :func:`map_history_facts`
maps it to the two historical profile facts ``HIST_WORKSHOPS`` and
``HIST_ATTENDANCE``. No SDK, no network, no live authentication; every record
stays synthetic.

Mapping honesty rules (P2.4):

* Attendances are never turned into unique beneficiaries; the fact text
  preserves the attendances-versus-unique-people distinction.
* A planned activity is never turned into a completed result; only the
  completed 2025 metrics produce historical facts. The active 2026 initiative
  produces no fact.
* ``is_mock`` must be true and every record must carry ``is_synthetic: true``;
  anything else is a ``FIXTURE_MISMATCH``.

The remaining P3C.5 read APIs (``get_organization_history``,
``get_past_grants``, ``get_active_initiatives``) are implemented in Phase 3,
Lane C and raise ``NotImplementedError`` until then.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import StrictBool, StrictInt, ValidationError

from errors import AppError
from models import Fact, StrictRecord
from settings import PROJECT_ROOT

NPSP_DATA_PATH = PROJECT_ROOT / "data" / "salesforce_npsp_data.json"

HIST_WORKSHOPS_METRIC = "workshops_delivered"
HIST_ATTENDANCE_METRIC = "workshop_attendances"
HISTORY_PERIOD = "2025"


class NpspProject(StrictRecord):
    id: str
    name: str
    description: str
    status: str
    period: str
    is_synthetic: StrictBool


class NpspPastGrant(StrictRecord):
    id: str
    funder: str
    amount_minor: StrictInt
    currency: str
    period: str
    purpose: str
    is_synthetic: StrictBool


class NpspImpactMetric(StrictRecord):
    id: str
    metric: str
    value: StrictInt
    period: str
    note: str | None = None
    is_synthetic: StrictBool


class NpspData(StrictRecord):
    is_mock: StrictBool
    projects: list[NpspProject]
    past_grants: list[NpspPastGrant]
    impact_metrics: list[NpspImpactMetric]


def load_npsp_data() -> NpspData:
    """Load and validate the local synthetic NPSP fixture."""
    return parse_npsp_data(_read_json(NPSP_DATA_PATH))


def parse_npsp_data(payload: dict[str, Any]) -> NpspData:
    """Validate an NPSP payload; reject non-mock or non-synthetic data."""
    try:
        data = NpspData.model_validate(payload)
    except ValidationError as error:
        raise AppError(
            "FIXTURE_MISMATCH",
            "salesforce_npsp_data.json does not match the expected fixture shape",
        ) from error
    if not data.is_mock:
        raise AppError(
            "FIXTURE_MISMATCH",
            "salesforce_npsp_data.json must declare is_mock=true; real Salesforce "
            "data is never used",
        )
    records: list[tuple[str, bool]] = [
        (record.id, record.is_synthetic)
        for record in (*data.projects, *data.past_grants, *data.impact_metrics)
    ]
    non_synthetic = [record_id for record_id, synthetic in records if not synthetic]
    if non_synthetic:
        raise AppError(
            "FIXTURE_MISMATCH",
            "every synthetic NPSP record must carry is_synthetic=true; offending "
            f"record IDs: {', '.join(sorted(non_synthetic))}",
        )
    return data


def map_history_facts(data: NpspData) -> list[Fact]:
    """Deterministically map completed 2025 metrics to historical facts.

    Returns exactly ``HIST_WORKSHOPS`` and ``HIST_ATTENDANCE``. Only completed
    metrics produce facts; the active 2026 initiative is never mapped to a
    completed result, and attendances are never reworded as unique people.
    """
    workshops = _single_metric(data, HIST_WORKSHOPS_METRIC)
    attendance = _single_metric(data, HIST_ATTENDANCE_METRIC)
    return [
        Fact(
            id="HIST_WORKSHOPS",
            text=(
                f"The association delivered {workshops.value} community "
                f"cardiovascular-health workshops in {workshops.period}."
            ),
            approved=True,
            provenance=f"salesforce_npsp_data.json:{workshops.id} (synthetic mock)",
            is_synthetic=True,
        ),
        Fact(
            id="HIST_ATTENDANCE",
            text=(
                f"There were {attendance.value} workshop attendances in "
                f"{attendance.period}. This is a total number of attendances, "
                "not a count of unique people."
            ),
            approved=True,
            provenance=f"salesforce_npsp_data.json:{attendance.id} (synthetic mock)",
            is_synthetic=True,
        ),
    ]


def get_organization_history() -> Any:
    raise NotImplementedError(
        "get_organization_history is implemented in Phase 3, Lane C (P3C.5)"
    )


def get_past_grants() -> Any:
    raise NotImplementedError(
        "get_past_grants is implemented in Phase 3, Lane C (P3C.5)"
    )


def get_active_initiatives() -> Any:
    raise NotImplementedError(
        "get_active_initiatives is implemented in Phase 3, Lane C (P3C.5)"
    )


def _single_metric(data: NpspData, metric: str) -> NpspImpactMetric:
    matches = [
        entry
        for entry in data.impact_metrics
        if entry.metric == metric and entry.period == HISTORY_PERIOD
    ]
    if len(matches) != 1:
        raise AppError(
            "FIXTURE_MISMATCH",
            f"expected exactly one synthetic {metric!r} metric for "
            f"{HISTORY_PERIOD}; found {len(matches)}",
        )
    return matches[0]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AppError(
            "FIXTURE_MISMATCH",
            f"fixture file {path.name} is missing or not valid UTF-8 JSON",
        ) from error
