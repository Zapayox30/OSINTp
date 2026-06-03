"""Tests for case / dossier management and manual intel (uses temp DB)."""

from __future__ import annotations


def _new_case(client, name="Test Case"):
    resp = client.post("/api/v1/cases", json={"name": name, "notes": "n"})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_create_get_list_case(client):
    cid = _new_case(client, "Alpha")
    got = client.get(f"/api/v1/cases/{cid}")
    assert got.status_code == 200
    assert got.json()["case"]["name"] == "Alpha"
    assert any(c["id"] == cid for c in client.get("/api/v1/cases").json())


def test_missing_case_is_404(client):
    assert client.get("/api/v1/cases/deadbeef").status_code == 404


def test_add_manual_entities_marked_manual(client):
    cid = _new_case(client)
    resp = client.post(
        f"/api/v1/cases/{cid}/entities",
        json=[{"type": "email", "value": "a@b.com"}, {"type": "phone", "value": "+15550001"}],
    )
    assert resp.status_code == 200
    saved = resp.json()
    assert {e["value"] for e in saved} == {"a@b.com", "+15550001"}
    assert all(e["origin"] == "manual" for e in saved)
    # email is pivotable, phone is a leaf
    by_value = {e["value"]: e for e in saved}
    assert by_value["a@b.com"]["pivotable"] is True
    assert by_value["+15550001"]["pivotable"] is False


def test_invalid_entity_type_is_422(client):
    cid = _new_case(client)
    resp = client.post(f"/api/v1/cases/{cid}/entities", json=[{"type": "wormhole", "value": "x"}])
    assert resp.status_code == 422


def test_add_edge_creates_endpoints(client):
    cid = _new_case(client)
    resp = client.post(
        f"/api/v1/cases/{cid}/edges",
        json={
            "source_type": "person", "source_value": "Jane Doe",
            "target_type": "email", "target_value": "jane@acme.com", "relation": "owns",
        },
    )
    assert resp.status_code == 200
    graph = client.get(f"/api/v1/cases/{cid}").json()
    assert {e["type"] for e in graph["entities"]} == {"person", "email"}
    assert graph["edges"][0]["relation"] == "owns"
    assert graph["edges"][0]["origin"] == "manual"


def test_import_export_roundtrip(client):
    cid = _new_case(client, "Import")
    imp = client.post(
        f"/api/v1/cases/{cid}/import",
        json={
            "entities": [{"type": "username", "value": "jdoe"}, {"type": "domain", "value": "acme.com"}],
            "edges": [{"source_type": "username", "source_value": "jdoe",
                       "target_type": "domain", "target_value": "acme.com", "relation": "registered"}],
        },
    )
    assert imp.status_code == 200
    assert imp.json()["entities_added"] == 2

    dossier = client.get(f"/api/v1/cases/{cid}/export").json()
    values = {e["value"] for e in dossier["entities"]}
    assert {"jdoe", "acme.com"} <= values
    assert dossier["case"]["edge_count"] == 1


def test_enrich_merges_and_preserves_manual_origin(client):
    cid = _new_case(client, "Enrich")
    client.post(f"/api/v1/cases/{cid}/entities", json=[{"type": "ip", "value": "10.0.0.7"}])
    resp = client.get(f"/api/v1/cases/{cid}/enrich", params={"target": "10.0.0.7", "max_depth": 1})
    assert resp.status_code == 200
    assert "event: done" in resp.text

    graph = client.get(f"/api/v1/cases/{cid}").json()
    ip_node = next(e for e in graph["entities"] if e["value"] == "10.0.0.7")
    # the auto-pivot re-touched the seed but must not erase manual provenance
    assert ip_node["origin"] == "manual"


def test_enrich_without_seeds_errors_gracefully(client):
    cid = _new_case(client, "Empty")
    resp = client.get(f"/api/v1/cases/{cid}/enrich")
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "event: done" in resp.text
