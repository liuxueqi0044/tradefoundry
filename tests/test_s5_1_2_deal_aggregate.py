from decimal import Decimal

import pytest
from sqlalchemy import func, select

from tradefoundry.deals.aggregates import (
    DealCellService,
    DealRouteService,
    OptimisticLockError,
)
from tradefoundry.deals.contracts import DealCellCreate, DealCellUpdate, DealRouteCreate
from tradefoundry.deals.models import StageTransitionRow
from tradefoundry.opportunity.models import RouteCandidateRow


def test_deal_cell_is_issued_once_preserves_boundaries_and_uses_optimistic_lock(
    session, ready_issuance_factory
):
    issuance, _ = ready_issuance_factory()
    request = DealCellCreate(
        issuance_command_id=issuance.id,
        owner="commercial-owner",
        amount=Decimal("1000.00"),
        currency="usd",
    )
    service = DealCellService(session)
    cell = service.create(request)
    repeated = service.create(request)

    assert repeated.id == cell.id
    assert cell.currency == "USD"
    assert set(cell.boundaries_json) == {"unknowns", "risks", "stop_conditions"}
    assert cell.command_snapshot_json["contract_version"] == "deal-cell-create-command-v1"
    updated = service.update_owner(cell.id, DealCellUpdate(expected_version=1, owner="new-owner"))
    assert updated.version == 2
    with pytest.raises(OptimisticLockError, match="version conflict"):
        service.update_owner(cell.id, DealCellUpdate(expected_version=1, owner="stale-writer"))
    changed = request.model_copy(update={"owner": "other-owner"})
    with pytest.raises(ValueError, match="reused"):
        service.create(changed)


def test_multiple_routes_have_independent_state_and_bounded_allocations(
    session, ready_issuance_factory
):
    issuance, hypothesis = ready_issuance_factory()
    cell = DealCellService(session).create(
        DealCellCreate(
            issuance_command_id=issuance.id,
            owner="route-owner",
            amount=Decimal("700.00"),
            currency="USD",
        )
    )
    candidates = [
        session.get(RouteCandidateRow, candidate_id)
        for candidate_id in hypothesis.route_candidate_ids_json
    ]
    feasible = [candidate for candidate in candidates if candidate.feasibility == "feasible"]
    route_service = DealRouteService(session)
    first_request = DealRouteCreate(
        route_key="direct-route",
        source_route_candidate_id=feasible[0].id,
        roles={"buyer": "candidate-a"},
        amount=Decimal("300.00"),
        currency="USD",
    )
    first = route_service.create(cell.id, first_request)
    second = route_service.create(
        cell.id,
        DealRouteCreate(
            route_key="partner-route",
            source_route_candidate_id=feasible[-1].id,
            roles={"partner": "candidate-b"},
            amount=Decimal("350.00"),
            currency="USD",
        ),
    )

    assert route_service.create(cell.id, first_request).id == first.id
    assert first.id != second.id
    assert first.version == second.version == 1
    assert first.roles_json != second.roles_json
    assert session.scalar(select(func.count()).select_from(StageTransitionRow)) == 2
    with pytest.raises(ValueError, match="exceed"):
        route_service.create(
            cell.id,
            DealRouteCreate(
                route_key="over-budget-route",
                source_route_candidate_id=feasible[0].id,
                amount=Decimal("100.00"),
                currency="USD",
            ),
        )
