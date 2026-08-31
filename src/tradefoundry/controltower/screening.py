from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.controltower.common import (
    idempotent_row,
    new_id,
    rate,
    request_fingerprint,
    require_row,
)
from tradefoundry.controltower.contracts import RiskCaseOpen, ScreeningCreate
from tradefoundry.controltower.governance import FreezeService
from tradefoundry.controltower.models import (
    ComplianceDatasetRow,
    ComplianceEntryRow,
    FreezeRow,
    ScreeningMatchRow,
    ScreeningRunRow,
)
from tradefoundry.master.models import EntityRow

MATCHER_VERSION = "board8-screening-rapidfuzz-1.0"


def normalize_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    ascii_value = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[\w]+", ascii_value, flags=re.UNICODE))


def _identifiers(values: dict[str, list[str]]) -> set[tuple[str, str]]:
    return {
        (kind.casefold().strip(), value.casefold().strip())
        for kind, items in values.items()
        for value in items
        if value.strip()
    }


class ScreeningService:
    def __init__(self, session: Session, freeze_service: FreezeService | None = None):
        self.session = session
        self.freezes = freeze_service or FreezeService(session)

    def screen(self, request: ScreeningCreate) -> ScreeningRunRow:
        request_hash = request_fingerprint({"operation": "risk.screening.run"}, request)
        existing = idempotent_row(
            self.session, ScreeningRunRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        require_row(self.session, EntityRow, request.entity_id, "entity")
        dataset = self._dataset(request.dataset_id)
        query_names = [normalize_name(value) for value in request.names if normalize_name(value)]
        query_identifiers = _identifiers(request.identifiers)
        query_countries = {value.upper() for value in request.countries}
        matches: list[dict] = []
        reasons: list[str] = []
        overall = "clear"
        for entry in self.session.scalars(
            select(ComplianceEntryRow).where(ComplianceEntryRow.dataset_id == dataset.id)
        ):
            listed_names = [
                normalize_name(value) for value in entry.names_json if normalize_name(value)
            ]
            name_score = max(
                (
                    Decimal(str(fuzz.WRatio(query, listed))) / Decimal("100")
                    for query in query_names
                    for listed in listed_names
                ),
                default=Decimal("0"),
            )
            listed_identifiers = _identifiers(entry.identifiers_json)
            identifier_hit = bool(query_identifiers & listed_identifiers)
            identifier_score = Decimal("1") if identifier_hit else Decimal("0")
            listed_countries = {value.upper() for value in entry.countries_json}
            if query_countries and listed_countries:
                country_score = Decimal("1") if query_countries & listed_countries else Decimal("0")
            else:
                country_score = Decimal("0.5")
            total = (
                name_score * Decimal("0.65")
                + identifier_score * Decimal("0.30")
                + country_score * Decimal("0.05")
            )
            matched_fields: list[str] = []
            explanation: list[str] = []
            if identifier_hit:
                outcome = "blocked"
                matched_fields.append("identifier")
                explanation.append("An exact strong identifier matched the active list snapshot.")
            elif total >= Decimal("0.88") or name_score >= Decimal("0.88"):
                outcome = "possible_match"
                matched_fields.append("name")
                explanation.append("Name similarity crossed the possible-match review threshold.")
            elif total >= Decimal("0.65"):
                outcome = "review"
                matched_fields.append("name")
                explanation.append("Weak or partial identity evidence cannot be auto-cleared.")
            else:
                outcome = "clear"
            if country_score == 1:
                matched_fields.append("country")
                explanation.append("Country evidence overlaps the listed entity.")
            if outcome != "clear" or total >= Decimal("0.50"):
                matches.append(
                    {
                        "entry": entry,
                        "name_score": name_score,
                        "identifier_score": identifier_score,
                        "country_score": country_score,
                        "total": total,
                        "matched_fields": sorted(set(matched_fields)),
                        "explanation": explanation,
                        "outcome": outcome,
                    }
                )
            overall = self._more_restrictive(overall, outcome)
        for owner_run_id in request.owner_screening_run_ids:
            owner = require_row(self.session, ScreeningRunRow, owner_run_id, "owner screening run")
            if owner.outcome == "blocked":
                overall = "blocked"
                reasons.append(f"Owner screening {owner.id} is blocked.")
            elif owner.outcome in {"possible_match", "review"}:
                overall = self._more_restrictive(overall, "possible_match")
                reasons.append(f"Owner screening {owner.id} requires resolution.")
        if overall == "clear" and not request.identity_complete:
            overall = "review"
            reasons.append("Identity is incomplete; weak evidence cannot be auto-cleared.")
        if overall == "clear":
            reasons.append("No candidate match was found against the active immutable snapshot.")
        else:
            reasons.append(f"Screening outcome is {overall}; external actions are frozen.")
        maximum_score = max((value["total"] for value in matches), default=Decimal("0"))
        run = ScreeningRunRow(
            id=new_id(),
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            entity_id=request.entity_id,
            dataset_id=dataset.id,
            query_snapshot_json={
                "names": request.names,
                "identifiers": request.identifiers,
                "countries": sorted(query_countries),
                "identity_complete": request.identity_complete,
                "owner_screening_run_ids": request.owner_screening_run_ids,
                "dataset_content_hash": dataset.content_hash,
            },
            outcome=overall,
            maximum_score=rate(maximum_score),
            reasons_json=reasons,
            matcher_version=MATCHER_VERSION,
            freeze_id=None,
        )
        self.session.add(run)
        self.session.flush()
        for value in matches:
            self.session.add(
                ScreeningMatchRow(
                    id=new_id(),
                    screening_run_id=run.id,
                    entry_id=value["entry"].id,
                    name_score=rate(value["name_score"]),
                    identifier_score=rate(value["identifier_score"]),
                    country_score=rate(value["country_score"]),
                    total_score=rate(value["total"]),
                    matched_fields_json=value["matched_fields"],
                    explanation_json=value["explanation"],
                    outcome=value["outcome"],
                )
            )
        if overall != "clear":
            case = self.freezes.open_case(
                RiskCaseOpen(
                    case_key=f"screening:{run.id}",
                    idempotency_key=f"screening-freeze:{run.id}",
                    case_type="sanctions_screening",
                    severity="critical" if overall == "blocked" else "high",
                    source_reference=run.id,
                    subject_refs=[request.entity_id, f"entity:{request.entity_id}"],
                    scopes=["external_action"],
                    reason="; ".join(reasons),
                    opened_by=request.requested_by,
                )
            )
            first_freeze = self.session.scalar(
                select(FreezeRow)
                .where(FreezeRow.risk_case_id == case.id)
                .order_by(FreezeRow.created_at)
            )
            run.freeze_id = first_freeze.id
        self.session.commit()
        return run

    def matches(self, screening_run_id: str) -> list[ScreeningMatchRow]:
        require_row(self.session, ScreeningRunRow, screening_run_id, "screening run")
        return list(
            self.session.scalars(
                select(ScreeningMatchRow)
                .where(ScreeningMatchRow.screening_run_id == screening_run_id)
                .order_by(ScreeningMatchRow.total_score.desc())
            )
        )

    def _dataset(self, dataset_id: str | None) -> ComplianceDatasetRow:
        if dataset_id is not None:
            dataset = require_row(
                self.session, ComplianceDatasetRow, dataset_id, "compliance dataset"
            )
        else:
            dataset = self.session.scalar(
                select(ComplianceDatasetRow)
                .where(
                    ComplianceDatasetRow.dataset_type == "sanctions",
                    ComplianceDatasetRow.status == "active",
                )
                .order_by(ComplianceDatasetRow.published_at.desc())
            )
            if dataset is None:
                raise LookupError("active sanctions dataset was not found")
        if dataset.status != "active":
            raise ValueError("screening must use the active compliance dataset snapshot")
        if dataset.dataset_type != "sanctions":
            raise ValueError("screening requires a sanctions dataset")
        return dataset

    @staticmethod
    def _more_restrictive(current: str, candidate: str) -> str:
        priority = {"clear": 0, "review": 1, "possible_match": 2, "blocked": 3}
        return candidate if priority[candidate] > priority[current] else current
