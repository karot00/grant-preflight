"""Tests for the P2.4 synthetic Salesforce-style history adapter
(services/salesforce_service.py).

Pure in-memory/local-fixture tests under the P1.5 outbound-call guard: no
SDK, no network, no live authentication is possible here.
"""

import pytest
from pydantic import ValidationError

from errors import AppError
from services.salesforce_service import (
    NpspImpactMetric,
    load_npsp_data,
    map_history_facts,
    parse_npsp_data,
)


def npsp_payload(**overrides) -> dict:
    payload = {
        "is_mock": True,
        "projects": [
            {
                "id": "NPSP_PROJECT_2025_WORKSHOPS",
                "name": "Heart Health Workshops 2025",
                "description": "Four community workshops delivered during 2025.",
                "status": "completed",
                "period": "2025",
                "is_synthetic": True,
            },
            {
                "id": "NPSP_PROJECT_2026_SATURDAYS",
                "name": "Heart Health Saturdays 2026",
                "description": "Active initiative planned for 2026.",
                "status": "active",
                "period": "2026",
                "is_synthetic": True,
            },
        ],
        "past_grants": [
            {
                "id": "NPSP_GRANT_2025_001",
                "funder": "Synthetic Community Foundation",
                "amount_minor": 200000,
                "currency": "EUR",
                "period": "2025",
                "purpose": "Support for community workshops in 2025.",
                "is_synthetic": True,
            }
        ],
        "impact_metrics": [
            {
                "id": "NPSP_METRIC_WORKSHOPS_2025",
                "metric": "workshops_delivered",
                "value": 4,
                "period": "2025",
                "note": "Completed workshops delivered in 2025.",
                "is_synthetic": True,
            },
            {
                "id": "NPSP_METRIC_ATTENDANCE_2025",
                "metric": "workshop_attendances",
                "value": 80,
                "period": "2025",
                "note": "Total attendances; not unique people.",
                "is_synthetic": True,
            },
        ],
    }
    payload.update(overrides)
    return payload


# --- fixture loading ------------------------------------------------------------


def test_shipped_fixture_loads_and_is_mock():
    data = load_npsp_data()
    assert data.is_mock is True
    assert len(data.projects) == 2
    assert len(data.past_grants) == 1
    assert len(data.impact_metrics) == 2
    assert all(record.is_synthetic for record in data.impact_metrics)


def test_shipped_past_grant_is_synthetic_eur_2000():
    grant = load_npsp_data().past_grants[0]
    assert grant.amount_minor == 200000
    assert grant.currency == "EUR"
    assert grant.is_synthetic is True


def test_non_mock_payload_is_fixture_mismatch():
    with pytest.raises(AppError) as excinfo:
        parse_npsp_data(npsp_payload(is_mock=False))
    assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_non_synthetic_record_is_fixture_mismatch():
    payload = npsp_payload()
    payload["impact_metrics"][0]["is_synthetic"] = False
    with pytest.raises(AppError) as excinfo:
        parse_npsp_data(payload)
    assert excinfo.value.code == "FIXTURE_MISMATCH"
    assert "NPSP_METRIC_WORKSHOPS_2025" in excinfo.value.message


def test_malformed_payload_is_fixture_mismatch():
    with pytest.raises(AppError) as excinfo:
        parse_npsp_data({"is_mock": True})
    assert excinfo.value.code == "FIXTURE_MISMATCH"
    with pytest.raises(AppError):
        parse_npsp_data(npsp_payload(projects=[{"id": "x"}]))


# --- deterministic history mapping ------------------------------------------------


def test_mapping_returns_exactly_the_two_historical_facts():
    facts = map_history_facts(load_npsp_data())
    assert [fact.id for fact in facts] == ["HIST_WORKSHOPS", "HIST_ATTENDANCE"]
    assert all(fact.is_synthetic for fact in facts)
    assert all(fact.approved for fact in facts)


def test_mapping_is_deterministic():
    first = map_history_facts(load_npsp_data())
    second = map_history_facts(load_npsp_data())
    assert first == second


def test_workshops_fact_states_four_completed_workshops_in_2025():
    (workshops, _) = map_history_facts(load_npsp_data())
    assert "4" in workshops.text
    assert "2025" in workshops.text
    assert "workshops" in workshops.text
    assert workshops.provenance == (
        "salesforce_npsp_data.json:NPSP_METRIC_WORKSHOPS_2025 (synthetic mock)"
    )


def test_attendance_fact_preserves_the_attendances_wording():
    (_, attendance) = map_history_facts(load_npsp_data())
    assert "80" in attendance.text
    assert "attendances" in attendance.text
    assert "not a count of unique people" in attendance.text
    for forbidden in ("beneficiaries", "unique beneficiaries", "80 people"):
        assert forbidden not in attendance.text.lower()


def test_active_2026_initiative_never_becomes_a_completed_result():
    facts = map_history_facts(load_npsp_data())
    combined = " ".join(fact.text for fact in facts).lower()
    assert "2026" not in combined
    assert "saturdays" not in combined


def test_missing_metric_is_fixture_mismatch():
    payload = npsp_payload()
    payload["impact_metrics"] = [
        metric for metric in payload["impact_metrics"]
        if metric["metric"] != "workshop_attendances"
    ]
    with pytest.raises(AppError) as excinfo:
        map_history_facts(parse_npsp_data(payload))
    assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_duplicate_metric_is_fixture_mismatch():
    payload = npsp_payload()
    payload["impact_metrics"].append(dict(payload["impact_metrics"][0], id="DUPLICATE"))
    with pytest.raises(AppError) as excinfo:
        map_history_facts(parse_npsp_data(payload))
    assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_metric_from_another_period_is_not_mapped():
    payload = npsp_payload()
    for metric in payload["impact_metrics"]:
        metric["period"] = "2024"
    with pytest.raises(AppError) as excinfo:
        map_history_facts(parse_npsp_data(payload))
    assert excinfo.value.code == "FIXTURE_MISMATCH"


def test_non_integer_metric_value_is_rejected():
    payload = npsp_payload()
    payload["impact_metrics"][0]["value"] = 4.0
    with pytest.raises(AppError):
        parse_npsp_data(payload)


# --- P3C.5 read APIs remain honest stubs ---------------------------------------------


@pytest.mark.parametrize(
    "function_name",
    ["get_organization_history", "get_past_grants", "get_active_initiatives"],
)
def test_lane_c_read_apis_are_not_implemented_yet(function_name):
    import services.salesforce_service as module

    with pytest.raises(NotImplementedError):
        getattr(module, function_name)()


def test_npsp_models_forbid_extra_fields():
    with pytest.raises(ValidationError):
        NpspImpactMetric(
            id="X", metric="m", value=1, period="2025", is_synthetic=True, extra=1
        )
