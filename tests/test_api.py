import pytest

from app import create_app
from conftest import vuln
from scanner import ScanError, Scanner


@pytest.fixture
def client(cache, osv_stub):
    app = create_app(scanner=Scanner())
    app.config["TESTING"] = True
    return app.test_client()


class TestScanEndpoint:
    def test_clean_scan_is_200_with_no_findings(self, client, osv_stub):
        response = client.post("/scan", json={"dependencies": ["totally-fake==1.0"]})
        assert response.status_code == 200
        assert response.get_json()["findings"] == []

    def test_findings_are_200(self, client, osv_stub):
        osv_stub.vulnerable = {"flask": [vuln("GHSA-1", cve="CVE-2023-30861")]}
        response = client.post("/scan", json={"dependencies": ["flask==2.2.2"]})
        assert response.status_code == 200
        assert response.get_json()["vulnerable"] == 1

    def test_scan_failure_is_503_never_an_empty_clean_result(self, client, osv_stub):
        """The single most important behaviour: a failed scan must not read as clean."""
        osv_stub.error = "upstream down"
        response = client.post("/scan", json={"dependencies": ["flask==2.2.2"]})
        assert response.status_code == 503
        assert "findings" not in response.get_json()

    def test_unexpected_error_is_500(self, cache, monkeypatch):
        class Exploding(Scanner):
            def scan(self, dependencies):
                raise ValueError("boom")

        app = create_app(scanner=Exploding())
        app.config["TESTING"] = True
        response = app.test_client().post("/scan", json={"dependencies": ["flask"]})
        assert response.status_code == 500

    @pytest.mark.parametrize("payload", [
        {}, {"wrong": "shape"}, {"dependencies": 42}, [1, 2, 3],
    ])
    def test_malformed_body_is_400(self, client, payload):
        response = client.post("/scan", json=payload)
        assert response.status_code == 400

    def test_non_json_body_is_400_not_500(self, client):
        response = client.post("/scan", data="not json", content_type="text/plain")
        assert response.status_code == 400

    def test_response_identifies_the_serving_node(self, client):
        response = client.post("/scan", json={"dependencies": ["clean==1.0"]})
        assert response.get_json()["node"]


class TestOperationalEndpoints:
    def test_health_is_200_even_without_mongo(self, client, monkeypatch):
        """Liveness must not flap on a cache outage, or HAProxy drops every backend."""
        import db
        monkeypatch.setattr(db, "ping", lambda: (_ for _ in ()).throw(RuntimeError("down")))
        response = client.get("/health")
        assert response.status_code == 200
        assert "unavailable" in response.get_json()["mongo"]

    def test_ready_is_503_without_mongo(self, client, monkeypatch):
        import db
        monkeypatch.setattr(db, "ping", lambda: (_ for _ in ()).throw(RuntimeError("down")))
        assert client.get("/ready").status_code == 503

    def test_health_reports_leadership(self, cache):
        class FakeCoordinator:
            is_leader = True
            connected = True

        app = create_app(coordinator=FakeCoordinator(), scanner=Scanner())
        app.config["TESTING"] = True
        body = app.test_client().get("/health").get_json()
        assert body["leader"] is True
        assert body["zookeeper"] == "connected"
