from sqlalchemy import func, select

from tradefoundry.opportunity.compiler import OpportunityCompiler
from tradefoundry.opportunity.contracts import CompileRequest
from tradefoundry.opportunity.models import CompilerRunRow


def test_compiler_separates_facts_from_inference_and_replays_deterministically(
    session, product_concept_factory, world_event_factory, opportunity_template_factory
):
    product = product_concept_factory(label="Industrial Ball Valve")
    event = world_event_factory(product_concept_id=product.id)
    template = opportunity_template_factory(
        product_concept_id=product.id,
        event_types=["rfq"],
        signal_types=["explicit_rfq"],
    )
    request = CompileRequest(
        event_id=event.id,
        template_id=template.id,
        correlation_id="compile-golden-rfq",
        additional_unknowns=["Confirm delivery Incoterm."],
        risks=["Specification may change before deadline."],
    )
    compiler = OpportunityCompiler(session)
    first = compiler.compile(request)
    repeated = compiler.compile(request.model_copy(update={"correlation_id": "compile-replay"}))

    hypothesis = first[0]
    assert repeated[0].id == hypothesis.id
    assert hypothesis.statement.startswith("Verified event evidence")
    assert hypothesis.fact_assertions_json[0]["claim_ids"]
    assert hypothesis.inference_assertions_json == []
    assert 0 <= hypothesis.probability_low < hypothesis.probability_high <= 1
    assert all(not action["external_side_effect"] for action in hypothesis.probe_actions_json)
    assert hypothesis.stop_conditions_json
    assert len(hypothesis.route_candidate_ids_json) == 4
    runs = session.scalars(select(CompilerRunRow)).all()
    assert len(runs) == 2
    assert all(run.status == "completed" for run in runs)
    assert runs[0].metrics_json["hypothesis_count"] == 1
    assert session.scalar(select(func.count()).select_from(CompilerRunRow)) == 2
