"""Fixed-version, auditable operating KPI snapshots."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.execution.common import aware, idempotent_row, new_id, request_fingerprint, utcnow
from tradefoundry.execution.contracts_learning import (
    DashboardSnapshotRequest,
    DashboardSnapshotView,
)
from tradefoundry.execution.models_learning import DashboardSnapshotRow


class DashboardService:
    def __init__(self, session: Session):
        self.session = session

    def snapshot(self, request: DashboardSnapshotRequest) -> DashboardSnapshotView:
        if not any(
            (
                request.invoice_ids,
                request.pnl_snapshot_ids,
                request.outcome_ids,
                request.cashflow_plan_ids,
            )
        ):
            raise ValueError("dashboard snapshot requires immutable execution fact references")
        sales, contribution, capital, outcomes = self._aggregate(request)
        request_hash = request_fingerprint({"service": "dashboard"}, request)
        existing = idempotent_row(
            self.session, DashboardSnapshotRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return DashboardSnapshotView.model_validate(existing)
        row = DashboardSnapshotRow(
            id=new_id(),
            snapshot_key=request.snapshot_key,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            as_of=request.as_of,
            version=request.version,
            # Keep sales and contribution PnL in separate top-level objects. Consumers can
            # drill down using stable refs without rebuilding this historical snapshot.
            sales_json=sales,
            contribution_json=contribution,
            capital_json=capital,
            outcomes_json=outcomes,
            drilldown_refs_json=self._refs(request),
            created_at=utcnow(),
        )
        self.session.add(row)
        self.session.commit()
        return DashboardSnapshotView.model_validate(row)

    create = snapshot

    def _aggregate(self, request: DashboardSnapshotRequest):
        from decimal import Decimal

        from tradefoundry.execution.models_settlement import (
            ContributionPnlSnapshotRow,
            InvoiceRefRow,
        )

        invoices = [self.session.get(InvoiceRefRow, row_id) for row_id in request.invoice_ids]
        pnl_rows = [
            self.session.get(ContributionPnlSnapshotRow, row_id)
            for row_id in request.pnl_snapshot_ids
        ]
        if any(row is None for row in invoices + pnl_rows):
            raise LookupError("dashboard references a missing invoice or PnL snapshot")
        if any(aware(row.created_at) > aware(request.as_of) for row in invoices + pnl_rows):
            raise ValueError("dashboard cannot include facts recorded after snapshot as_of")
        if any(aware(row.as_of) > aware(request.as_of) for row in pnl_rows):
            raise ValueError("dashboard cannot include PnL snapshots after snapshot as_of")
        target = request.reporting_currency
        if any(
            (row.normalized_currency or row.currency).upper() != target for row in invoices
        ) or any(row.currency.upper() != target for row in pnl_rows):
            raise ValueError("dashboard facts must be normalized to the reporting currency")
        if len({row.order_id for row in pnl_rows}) != len(pnl_rows):
            raise ValueError("dashboard accepts only one PnL snapshot per order")
        gross_sales = sum(
            (
                row.normalized_amount or row.amount
                for row in invoices
                if row.invoice_kind == "sales" and row.status != "void"
            ),
            Decimal("0"),
        )
        contribution_pnl = sum((row.contribution for row in pnl_rows), Decimal("0"))
        capital = {}
        if request.cashflow_plan_ids:
            from tradefoundry.controltower.models import CashflowPlanRow

            plans = [
                self.session.get(CashflowPlanRow, row_id) for row_id in request.cashflow_plan_ids
            ]
            if any(row is None for row in plans):
                raise LookupError("dashboard references a missing cashflow plan")
            if any(aware(row.created_at) > aware(request.as_of) for row in plans):
                raise ValueError(
                    "dashboard cannot include cashflow plans recorded after snapshot as_of"
                )
            if any(row.currency.upper() != target for row in plans):
                raise ValueError("cashflow plans must use the dashboard reporting currency")
            capital["peak_working_capital"] = str(
                max((row.peak_working_capital for row in plans), default=Decimal("0"))
            )
        outcome_counts = {"success": 0, "failure": 0, "no_reply": 0}
        if request.outcome_ids:
            from tradefoundry.execution.models_learning import OutcomeRow

            outcome_rows = [self.session.get(OutcomeRow, row_id) for row_id in request.outcome_ids]
            if any(row is None for row in outcome_rows):
                raise LookupError("dashboard references a missing outcome")
            if any(aware(row.created_at) > aware(request.as_of) for row in outcome_rows):
                raise ValueError("dashboard cannot include outcomes recorded after snapshot as_of")
            if any(aware(row.outcome_cutoff_at) > aware(request.as_of) for row in outcome_rows):
                raise ValueError("dashboard cannot include outcomes after snapshot as_of")
            if len({row.route_id for row in outcome_rows}) != len(outcome_rows):
                raise ValueError("dashboard accepts only one outcome per route")
            for row in outcome_rows:
                label = "success" if row.success else "no_reply" if row.no_reply else "failure"
                outcome_counts[label] += 1
        return (
            {
                "gross_sales": str(gross_sales),
                "invoice_count": len(invoices),
                "currency": target,
            },
            {
                "contribution_pnl": str(contribution_pnl),
                "pnl_snapshot_count": len(pnl_rows),
                "currency": target,
            },
            capital,
            outcome_counts,
        )

    @staticmethod
    def _refs(request: DashboardSnapshotRequest) -> list[str]:
        return [
            *request.invoice_ids,
            *request.pnl_snapshot_ids,
            *request.outcome_ids,
            *request.cashflow_plan_ids,
        ]

    snapshot_from_ledger = snapshot

    def latest(self, snapshot_key: str, version: str = "v1") -> DashboardSnapshotView:
        row = self.session.scalar(
            select(DashboardSnapshotRow)
            .where(
                DashboardSnapshotRow.snapshot_key == snapshot_key,
                DashboardSnapshotRow.version == version,
            )
            .order_by(DashboardSnapshotRow.as_of.desc(), DashboardSnapshotRow.id.desc())
        )
        if row is None:
            raise LookupError(f"dashboard snapshot {snapshot_key}/{version} was not found")
        return DashboardSnapshotView.model_validate(row)
