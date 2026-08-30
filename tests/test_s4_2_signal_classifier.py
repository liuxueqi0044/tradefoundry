from tradefoundry.opportunity.signals import SignalClassifier


def test_signal_classifier_is_idempotent_and_priority_ordered(session, world_event_factory):
    event = world_event_factory(
        event_type="rfq",
        title="RFQ following project award and expansion",
        value="The expansion award requests a quotation.",
    )
    service = SignalClassifier(session)
    signals = service.classify(event.id)
    repeated = service.classify(event.id)

    types = {signal.signal_type for signal in signals}
    assert {"explicit_rfq", "award", "expansion"}.issubset(types)
    assert signals[0].signal_type == "explicit_rfq"
    assert all(signal.basis_json["matches"] for signal in signals)
    assert [signal.id for signal in repeated] == [signal.id for signal in signals]
