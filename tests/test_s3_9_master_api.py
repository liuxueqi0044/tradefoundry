from fastapi.testclient import TestClient

from tradefoundry.api import app
from tradefoundry.db import get_session


def test_master_data_api_search_profile_identifier_and_graph(session, master_claim_factory):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        buyer_claim = master_claim_factory(value="Global Buyer")
        project_claim = master_claim_factory(value="Port Project")
        relation_claim = master_claim_factory(value="buyer_for", verified=True)
        buyer = client.post(
            "/v1/master/entities",
            json={
                "entity_key": "api:buyer",
                "entity_type": "organization",
                "source_claim_id": buyer_claim.id,
                "primary_name": "Global Buyer Limited",
                "aliases": [{"value": "全球买方有限公司", "language": "zh"}],
                "attributes": [{"field_name": "country", "value": "CN"}],
            },
        )
        project = client.post(
            "/v1/master/entities",
            json={
                "entity_key": "api:project",
                "entity_type": "project",
                "source_claim_id": project_claim.id,
                "primary_name": "Port Project",
            },
        )
        assert buyer.status_code == 201
        assert project.status_code == 201
        buyer_id = buyer.json()["id"]
        project_id = project.json()["id"]

        identifier = client.post(
            f"/v1/master/entities/{buyer_id}/identifiers",
            json={
                "scheme": "domain",
                "value": "buyer.example",
                "source_claim_id": buyer_claim.id,
            },
        )
        assert identifier.status_code == 201
        assert identifier.json()["outcome"] == "recorded_unique"
        assert (
            client.get(
                "/v1/master/search/identifiers",
                params={"scheme": "domain", "value": "www.buyer.example"},
            ).json()[0]["canonical_entity_id"]
            == buyer_id
        )
        assert (
            client.get(
                "/v1/master/search/names", params={"q": "全球买方", "language": "zh"}
            ).json()[0]["canonical_entity_id"]
            == buyer_id
        )

        relation = client.post(
            "/v1/master/relations",
            json={
                "subject_entity_id": buyer_id,
                "relation_type": "buyer_for",
                "object_entity_id": project_id,
                "evidence_claim_id": relation_claim.id,
                "confidence": 0.97,
                "review_status": "verified",
            },
        )
        assert relation.status_code == 201
        graph = client.get(
            f"/v1/master/entities/{buyer_id}/relations",
            params={"max_depth": 1, "direction": "outgoing"},
        )
        assert graph.status_code == 200
        assert graph.json()[0]["end_entity_id"] == project_id

        profile = client.get(f"/v1/master/entities/{buyer_id}/profile")
        assert profile.status_code == 200
        assert profile.json()["golden_fields"]["country"]["value"] == "CN"
    finally:
        app.dependency_overrides.clear()


def test_product_and_specification_http_flow(session, master_claim_factory):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        product_claim = master_claim_factory(value="pump")
        product = client.post(
            "/v1/master/products",
            json={
                "concept_key": "api-pump",
                "preferred_label": "Industrial Pump",
                "source_claim_id": product_claim.id,
            },
        )
        assert product.status_code == 201
        concept_id = product.json()["id"]
        synonym_claim = master_claim_factory(value="water pump")
        synonym = client.post(
            f"/v1/master/products/{concept_id}/synonyms",
            json={"label": "Water Pump", "source_claim_id": synonym_claim.id},
        )
        assert synonym.status_code == 201
        code_claim = master_claim_factory(value="8413")
        mapping = client.post(
            f"/v1/master/products/{concept_id}/codes",
            json={
                "scheme": "hs",
                "code": "8413",
                "confidence": 0.8,
                "method": "fixture",
                "source_claim_id": code_claim.id,
            },
        )
        assert mapping.status_code == 201
        reviewed = client.post(
            f"/v1/master/product-codes/{mapping.json()['id']}/review",
            json={
                "action": "verify",
                "reviewer": "classifier",
                "reason": "Confirmed against tariff notes.",
            },
        )
        assert reviewed.json()["status"] == "verified"
        assert (
            client.get("/v1/master/search/products", params={"q": "water pump"}).json()[0][
                "concept"
            ]["id"]
            == concept_id
        )

        first_claim = master_claim_factory(value="10 kg")
        second_claim = master_claim_factory(value="12 kg")
        specifications = []
        for version, claim, value in ((1, first_claim, "10"), (2, second_claim, "12")):
            response = client.post(
                "/v1/master/specifications",
                json={
                    "specification_key": f"api-pump:v{version}",
                    "concept_id": concept_id,
                    "version_no": version,
                    "original_text": f"Weight {value} kg",
                    "source_claim_id": claim.id,
                    "requirements": [
                        {
                            "requirement_key": "weight",
                            "mode": "required",
                            "value": value,
                            "unit": "kg",
                            "target_unit": "kg",
                            "original_text": f"Weight {value} kg",
                        }
                    ],
                },
            )
            assert response.status_code == 201
            specifications.append(response.json()["id"])
        differences = client.get(
            f"/v1/master/specifications/{specifications[0]}/diff/{specifications[1]}"
        )
        assert differences.status_code == 200
        assert differences.json()[0]["change_type"] == "changed"
    finally:
        app.dependency_overrides.clear()


def test_merge_undo_split_and_distinct_http_commands(session, master_claim_factory):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        entity_ids = []
        for index in range(2):
            claim = master_claim_factory(value=f"Company {index}")
            response = client.post(
                "/v1/master/entities",
                json={
                    "entity_key": f"api:merge:{index}",
                    "entity_type": "organization",
                    "source_claim_id": claim.id,
                    "primary_name": f"Company {index}",
                },
            )
            entity_ids.append(response.json()["id"])
        merge = client.post(
            "/v1/master/merges",
            json={
                "winner_entity_id": entity_ids[0],
                "loser_entity_id": entity_ids[1],
                "idempotency_key": "api:merge-command",
                "actor": "reviewer",
                "reason": "Same legal entity.",
            },
        )
        assert merge.status_code == 201
        assert client.get(f"/v1/master/entities/{entity_ids[1]}").json()["status"] == "merged"
        undo = client.post(
            f"/v1/master/merges/{merge.json()['id']}/undo",
            json={"actor": "reviewer", "reason": "Evidence changed."},
        )
        assert undo.json()["status"] == "undone"
        second_merge = client.post(
            "/v1/master/merges",
            json={
                "winner_entity_id": entity_ids[0],
                "loser_entity_id": entity_ids[1],
                "idempotency_key": "api:merge-command:2",
                "actor": "reviewer",
                "reason": "Temporary merge for split acceptance.",
            },
        )
        split = client.post(
            f"/v1/master/entities/{entity_ids[1]}/split",
            json={
                "idempotency_key": "api:split-command",
                "actor": "reviewer",
                "reason": "Detach the incorrect member.",
            },
        )
        assert second_merge.status_code == 201
        assert split.status_code == 201
        distinct = client.post(
            "/v1/master/distinct-pairs",
            json={
                "left_entity_id": entity_ids[0],
                "right_entity_id": entity_ids[1],
                "actor": "reviewer",
                "reason": "Confirmed separate registrations.",
            },
        )
        assert distinct.status_code == 201
    finally:
        app.dependency_overrides.clear()
