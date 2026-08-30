from sqlalchemy import select
from test_s2_3_conversion import GoldenConverter

from tradefoundry.evidence.conversion import ConversionService
from tradefoundry.evidence.models import EvidenceFragmentRow


def test_fragment_keeps_exact_version_page_bbox_section_and_table_cell(
    session, artifact_store, evidence_document_factory
):
    document = evidence_document_factory(logical_id="located", convert=False)
    ConversionService(session, artifact_store).convert(document.id, GoldenConverter())
    fragment = session.scalar(
        select(EvidenceFragmentRow).where(EvidenceFragmentRow.fragment_key == "page-2-table")
    )

    assert fragment.document_id == document.id
    assert fragment.page_no == 2
    assert fragment.bbox_json["left"] == 30
    assert fragment.section_path == ["Procurement"]
    assert fragment.table_cell_json == {"row": 1, "column": 2}
