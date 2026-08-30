from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.bilateral.common import (
    idempotent_row,
    new_id,
    request_fingerprint,
    require_row,
)
from tradefoundry.bilateral.contracts import RfqCreate, RfqFinalizeRequest
from tradefoundry.bilateral.models import RfqVersionRow
from tradefoundry.deals.models import DealRouteRow
from tradefoundry.ingestion.hashing import payload_hash
from tradefoundry.master.models import ProductConceptRow


class RfqService:
    def __init__(self, session: Session):
        self.session = session

    def generate(self, route_id: str, request: RfqCreate) -> RfqVersionRow:
        require_row(self.session, DealRouteRow, route_id, "route")
        product = require_row(
            self.session, ProductConceptRow, request.product_concept_id, "product concept"
        )
        request_hash = request_fingerprint(
            {"operation": "rfq.generate", "route_id": route_id}, request
        )
        existing = idempotent_row(
            self.session, RfqVersionRow, request.idempotency_key, request_hash
        )
        if existing is not None:
            return existing
        version_no = (
            self.session.scalar(
                select(func.max(RfqVersionRow.version_no)).where(
                    RfqVersionRow.route_id == route_id,
                    RfqVersionRow.rfq_key == request.rfq_key,
                )
            )
            or 0
        ) + 1
        requirement = request.requirement
        unresolved: list[str] = []
        if not requirement.specification:
            unresolved.append("specification")
        if requirement.quantity is None:
            unresolved.append("quantity")
        if requirement.packaging is None:
            unresolved.append("packaging")
        if requirement.certifications is None:
            unresolved.append("certifications")
        if requirement.requested_delivery_at is None:
            unresolved.append("requested_delivery_at")
        if requirement.incoterm is None:
            unresolved.append("incoterm")
        if requirement.payment_terms is None:
            unresolved.append("payment_terms")
        questions = [*_questions_for(unresolved), *request.extra_questions]
        content = _render_chinese_rfq(
            product_name=product.preferred_label,
            destination_country=request.destination_country,
            requirement=requirement.model_dump(mode="json"),
            questions=questions,
            unresolved=unresolved,
        )
        row = RfqVersionRow(
            id=new_id(),
            route_id=route_id,
            rfq_key=request.rfq_key,
            version_no=version_no,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            product_concept_id=request.product_concept_id,
            requirement_json=requirement.model_dump(mode="json"),
            quantity=requirement.quantity,
            quantity_unit=requirement.quantity_unit,
            destination_country=request.destination_country,
            incoterm=requirement.incoterm,
            requested_delivery_at=requirement.requested_delivery_at,
            questions_json=questions,
            unresolved_fields_json=unresolved,
            content_zh=content,
            content_hash=payload_hash(content),
            status="draft",
            created_by=request.created_by,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def finalize(self, rfq_id: str, request: RfqFinalizeRequest) -> RfqVersionRow:
        row = require_row(self.session, RfqVersionRow, rfq_id, "RFQ")
        if row.content_hash != request.expected_content_hash:
            raise ValueError("RFQ content changed after review")
        if row.status == "final":
            return row
        if row.status != "draft":
            raise ValueError(f"RFQ in status {row.status} cannot be finalized")
        if row.unresolved_fields_json:
            raise ValueError("RFQ with unresolved required fields cannot be finalized")
        row.status = "final"
        row.finalized_by = request.actor
        from tradefoundry.ingestion.models import utcnow

        row.finalized_at = utcnow()
        self.session.commit()
        return row


def _questions_for(unresolved: list[str]) -> list[str]:
    labels = {
        "specification": "请确认完整技术规格和可接受偏差。",
        "quantity": "请确认采购数量及计量单位。",
        "packaging": "请确认包装、标签和托盘要求。",
        "certifications": "请确认所需认证及报告版本。",
        "requested_delivery_at": "请确认期望交付日期。",
        "incoterm": "请确认 Incoterms 2020 条款及指定地点。",
        "payment_terms": "请确认付款方式和账期。",
    }
    return [labels[field] for field in unresolved]


def _render_chinese_rfq(
    *,
    product_name: str,
    destination_country: str,
    requirement: dict,
    questions: list[str],
    unresolved: list[str],
) -> str:
    quantity_value = requirement.get("quantity")
    quantity_text = (
        f"{Decimal(quantity_value):f} {requirement['quantity_unit']}"
        if quantity_value is not None
        else "待确认"
    )
    certifications = requirement.get("certifications")
    certification_text = certifications if certifications is not None else "待确认"
    lines = [
        f"产品：{product_name}",
        f"目的国：{destination_country}",
        f"规格：{requirement.get('specification') or '待确认'}",
        f"数量：{quantity_text}",
        f"包装：{requirement.get('packaging') or '待确认'}",
        f"认证：{certification_text}",
        f"交期：{requirement.get('requested_delivery_at') or '待确认'}",
        f"贸易术语：{requirement.get('incoterm') or '待确认'}",
        f"付款条款：{requirement.get('payment_terms') or '待确认'}",
        f"未确认字段：{', '.join(unresolved) if unresolved else '无'}",
        "请在报价中分别列明单价、币种、税费、MOQ、交期、付款条款、"
        "Incoterms 2020 条款、报价有效期及规格偏差。",
    ]
    if questions:
        lines.extend(["问题清单：", *[f"- {question}" for question in questions]])
    return "\n".join(lines)
