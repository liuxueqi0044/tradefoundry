from tradefoundry.opportunity.participants import ParticipantDiscoveryService
from tradefoundry.opportunity.routes import RouteCandidateService
from tradefoundry.opportunity.signals import SignalClassifier


def test_route_generation_preserves_feasible_and_excluded_paths(session, world_event_factory):
    event = world_event_factory(event_type="rfq", subject_role="buyer")
    SignalClassifier(session).classify(event.id)
    ParticipantDiscoveryService(session).discover(event.id)
    service = RouteCandidateService(session)

    routes = service.generate(event.id)
    repeated = service.generate(event.id)
    by_type = {route.route_type: route for route in routes}

    assert len(routes) == 4
    assert by_type["direct_bid"].feasibility == "feasible"
    assert by_type["direct_bid"].participant_candidate_ids_json
    assert by_type["pre_award_supply"].feasibility == "excluded"
    assert "EPC candidate" in by_type["pre_award_supply"].missing_requirements_json
    assert by_type["channel"].reasons_json[0].startswith("Excluded because")
    assert [route.id for route in repeated] == [route.id for route in routes]
