import pytest
from fastapi.testclient import TestClient

from policy_ai.api import app

client = TestClient(app)
AUTH = {"Authorization": "Bearer test-service-token"}


@pytest.fixture(autouse=True)
def configure(monkeypatch):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "test-service-token")


def test_auth_required_and_config(monkeypatch):
    body = {"stage": "SEARCH", "question": "지원", "consultation_type": "POLICY_QA"}
    assert client.post("/ai/v1/consultations", json=body).status_code == 401
    monkeypatch.delenv("AI_SERVICE_TOKEN")
    assert client.post("/ai/v1/consultations", json=body, headers=AUTH).status_code == 503


def test_valid_contract_is_explicitly_unimplemented():
    response = client.post("/ai/v1/consultations", json={"stage": "SEARCH", "question": "지원", "consultation_type": "POLICY_QA"}, headers=AUTH)
    assert response.status_code == 501
    assert response.json()["result_code"] == 501


def test_numeric_id_rejected_and_input_not_echoed():
    response = client.post("/ai/v1/policy-indexes", headers=AUTH, json={"policy_id": 123, "documents": [], "source_version": "not-a-date", "secret": "private-value"})
    assert response.status_code == 400
    assert "private-value" not in response.text


def test_qa_rejects_personal_data():
    response = client.post("/ai/v1/consultations", headers=AUTH, json={"stage": "ANSWER", "question": "지원", "consultation_type": "POLICY_QA", "references": [], "user_conditions": {}})
    assert response.status_code == 400


def test_nine_operations_and_create_status():
    schema = app.openapi()
    operations = [(path, method) for path, methods in schema["paths"].items() if path.startswith("/ai/") for method in methods]
    assert len(operations) == 9
    assert "201" in schema["paths"]["/ai/v1/policy-indexes"]["post"]["responses"]
    for path, method in operations:
        assert schema["paths"][path][method]["security"]


@pytest.mark.parametrize("method,path,body", [
    ("POST", "recommendations", {"user_conditions": {}, "benefits": [], "policies": []}),
    ("POST", "eligibility-analyses", {"user_conditions": {}, "policy": {"policy_id": "1", "policy_name": "a", "eligibility_conditions": [], "duplicate_restrictions": []}}),
    ("POST", "duplicate-benefit-analyses", {"user_conditions": {}, "benefits": [], "policies": [], "target_policy_id": "1"}),
    ("POST", "scenario-analyses", {"before_conditions": {}, "after_conditions": {}, "benefits": [], "policies": []}),
    ("DELETE", "policy-indexes/1", None),
])
def test_pending_routes(method, path, body):
    response = client.request(method, f"/ai/v1/{path}", json=body, headers=AUTH)
    assert response.status_code == 501


@pytest.mark.parametrize("method,path", [("POST", "policy-indexes"), ("PUT", "policy-indexes/1"), ("POST", "policy-verifications")])
def test_document_contracts(method, path):
    body = {"documents": [{"document_id": "1", "document_title": "title", "policy_text": "text", "source_url": "https://example.org"}], "source_version": "2026-10-16T09:00:00+09:00"}
    if method == "POST":
        body["policy_id"] = "1"
    if path == "policy-verifications":
        body.update(eligibility_conditions=[], duplicate_restrictions=[])
    assert client.request(method, f"/ai/v1/{path}", headers=AUTH, json=body).status_code == 501
