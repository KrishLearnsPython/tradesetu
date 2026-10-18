
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIRECTORY = PROJECT_ROOT / "tradesetu"

if str(APP_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(APP_DIRECTORY))

import app as tradesetu_app


@pytest.fixture
def client():
    tradesetu_app.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=True,
    )
    with tradesetu_app.app.test_client() as test_client:
        yield test_client


def test_home_page_is_accessible(client):
    response = client.get("/")
    assert response.status_code == 200


def test_dashboard_redirects_when_not_logged_in(client):
    response = client.get("/dashboard")
    assert response.status_code in (302, 401, 403)


def test_distributor_dashboard_denies_unauthenticated_access(client):
    response = client.get("/distributor_dashboard")
    assert response.status_code in (302, 401, 403)


def test_retailer_dashboard_denies_unauthenticated_access(client):
    response = client.get("/retailer_dashboard")
    assert response.status_code in (302, 401, 403)


def test_logout_get_does_not_log_out_via_get(client):
    response = client.get("/logout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers.get("Location") is not None


def test_post_without_csrf_token_is_rejected(client):
    response = client.post("/logout")
    assert response.status_code == 400



def test_get_logout_preserves_session(client):
    with client.session_transaction() as session:
        session["user_id"] = 123
        session["role"] = "retailer"

    client.get("/logout", follow_redirects=False)

    with client.session_transaction() as session:
        assert session.get("user_id") == 123
        assert session.get("role") == "retailer"



def test_retailer_cannot_access_distributor_dashboard(client, monkeypatch):
    with client.session_transaction() as session:
        session["user_id"] = 123
        session["role"] = "retailer"

    def fail_if_database_is_accessed():
        pytest.fail("Database should not be accessed for an unauthorized role")

    monkeypatch.setattr(
        tradesetu_app,
        "get_db_connection",
        fail_if_database_is_accessed,
    )

    response = client.get("/distributor_dashboard")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "Unauthorized"



def test_retailer_cannot_access_manufacturer_dashboard(client):
    with client.session_transaction() as session:
        session["user_id"] = 123
        session["role"] = "retailer"

    response = client.get("/manufacturer_dashboard")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "Unauthorized"




def test_shipment_assignment_conflict_returns_409(client, monkeypatch):
    class FakeCursor:
        rowcount = 0

        def execute(self, query, params=None):
            pass

        def fetchone(self):
            return {"pan_tan_id": "TEST-PAN"}

        def close(self):
            pass

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()
            self.rolled_back = False
            self.closed = False

        def cursor(self):
            return self.fake_cursor

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    fake_connection = FakeConnection()

    monkeypatch.setattr(
        tradesetu_app,
        "get_db_connection",
        lambda: fake_connection,
    )

    with client.session_transaction() as session:
        session["user_id"] = 123
        session["role"] = "manufacturer"

    with tradesetu_app.app.test_client() as route_client:
        route_client.application.config["WTF_CSRF_ENABLED"] = False
        with route_client.session_transaction() as session:
            session["user_id"] = 123
            session["role"] = "manufacturer"

        response = route_client.post(
            "/my_shipments",
            data={
                "shipment_id": "SHP123456",
                "distributor_id": "456",
            },
            follow_redirects=False,
        )

    assert response.status_code == 409
    assert fake_connection.rolled_back is True
    assert fake_connection.closed is True




def test_invalid_distributor_selection_does_not_update_shipment(
    client, monkeypatch
):
    class FakeCursor:
        def __init__(self):
            self.closed = False

        def execute(self, query, params=None):
            pass

        def fetchone(self):
            # Simulate a distributor that is not valid or active.
            return None

        def close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self):
            self.fake_cursor = FakeCursor()
            self.closed = False

        def cursor(self):
            return self.fake_cursor

        def close(self):
            self.closed = True

    fake_connection = FakeConnection()

    monkeypatch.setattr(
        tradesetu_app,
        "get_db_connection",
        lambda: fake_connection,
    )

    with tradesetu_app.app.test_client() as route_client:
        route_client.application.config["WTF_CSRF_ENABLED"] = False

        with route_client.session_transaction() as session:
            session["user_id"] = 123
            session["role"] = "manufacturer"

        response = route_client.post(
            "/my_shipments",
            data={
                "shipment_id": "SHP123456",
                "distributor_id": "456",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert fake_connection.fake_cursor.closed is True
    assert fake_connection.closed is True





def test_verify_hash_redirects_unauthenticated_user():
    with tradesetu_app.app.test_client() as route_client:
        route_client.application.config["WTF_CSRF_ENABLED"] = False

        response = route_client.post(
            "/verify_hash",
            json={
                "shipment_id": "SHP123456",
                "qr_hash": "a" * 64,
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_verify_hash_rejects_invalid_json():
    with tradesetu_app.app.test_client() as route_client:
        route_client.application.config["WTF_CSRF_ENABLED"] = False

        with route_client.session_transaction() as session:
            session["user_id"] = 456
            session["role"] = "distributor"

        response = route_client.post(
            "/verify_hash",
            json=[],
        )

    assert response.status_code == 400
    assert response.get_json()["status"] == "invalid_data"


def test_verify_hash_detects_tampered_hash(monkeypatch):
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            pass

        def fetchone(self):
            return {
                "shipment_id": "SHP123456",
                "distributor_id": 456,
                "storage_id": 789,
                "retailer_id": 101,
                "current_hash": "a" * 64,
            }

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(
        tradesetu_app,
        "get_db_connection",
        lambda: FakeConnection(),
    )

    with tradesetu_app.app.test_client() as route_client:
        route_client.application.config["WTF_CSRF_ENABLED"] = False

        with route_client.session_transaction() as session:
            session["user_id"] = 456
            session["role"] = "distributor"

        response = route_client.post(
            "/verify_hash",
            json={
                "shipment_id": "SHP123456",
                "qr_hash": "b" * 64,
            },
        )

    assert response.status_code == 200
    assert response.get_json()["status"] == "tampered"


def test_verify_hash_accepts_matching_hash(monkeypatch):
    expected_hash = "a" * 64

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params=None):
            pass

        def fetchone(self):
            return {
                "shipment_id": "SHP123456",
                "distributor_id": 456,
                "storage_id": 789,
                "retailer_id": 101,
                "current_hash": expected_hash,
            }

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(
        tradesetu_app,
        "get_db_connection",
        lambda: FakeConnection(),
    )

    with tradesetu_app.app.test_client() as route_client:
        route_client.application.config["WTF_CSRF_ENABLED"] = False

        with route_client.session_transaction() as session:
            session["user_id"] = 456
            session["role"] = "distributor"

        response = route_client.post(
            "/verify_hash",
            json={
                "shipment_id": "SHP123456",
                "qr_hash": expected_hash,
            },
        )

    assert response.status_code == 200
    assert response.get_json()["status"] == "valid"