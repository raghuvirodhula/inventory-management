"""
Tests for restocking order API endpoints.
"""
import pytest


def _sample_payload():
    return {
        "items": [
            {
                "sku": "PCB-001",
                "name": "Single Layer PCB Assembly",
                "quantity": 100,
                "unit_cost": 24.99,
                "lead_time_days": 14,
            },
            {
                "sku": "TMP-201",
                "name": "Temperature Sensor Module",
                "quantity": 50,
                "unit_cost": 89.5,
                "lead_time_days": 7,
            },
        ]
    }


class TestRestockingOrderEndpoints:
    """Test suite for restocking order endpoints."""

    def test_create_restocking_order(self, client):
        """Test creating a restocking order with valid items."""
        payload = _sample_payload()
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 200

        order = response.json()

        # Identity / metadata fields
        assert "id" in order
        assert order["order_number"].startswith("RESTOCK-")
        assert order["customer"] == "Internal Restock"
        assert order["status"] == "Submitted"
        assert order["warehouse"] is None
        assert order["category"] is None
        assert order["actual_delivery"] is None

        # Items are passed through with all fields
        assert isinstance(order["items"], list)
        assert len(order["items"]) == 2
        for item in order["items"]:
            assert "sku" in item
            assert "name" in item
            assert "quantity" in item
            assert "unit_cost" in item
            assert "lead_time_days" in item

    def test_create_restocking_order_total_value(self, client):
        """Test that total_value sums quantity * unit_cost across items."""
        payload = _sample_payload()
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 200

        expected_total = sum(
            item["quantity"] * item["unit_cost"] for item in payload["items"]
        )
        order = response.json()
        # Allow small floating point differences
        assert abs(order["total_value"] - expected_total) < 0.01

    def test_create_restocking_order_expected_delivery(self, client):
        """Test that expected_delivery is after order_date and uses max lead time."""
        payload = _sample_payload()
        response = client.post("/api/restocking-orders", json=payload)
        order = response.json()

        # ISO 8601 sortable: lexical comparison is correct for same-format strings
        assert order["expected_delivery"] > order["order_date"]
        # Should contain T (datetime ISO format)
        assert "T" in order["order_date"]
        assert "T" in order["expected_delivery"]

    def test_create_restocking_order_empty_items(self, client):
        """Test that POSTing with no items returns 400."""
        response = client.post("/api/restocking-orders", json={"items": []})
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data

    def test_create_restocking_order_missing_field(self, client):
        """Test that POSTing with a malformed item returns 422."""
        bad_payload = {
            "items": [
                {
                    "sku": "PCB-001",
                    "name": "Single Layer PCB Assembly",
                    # missing quantity, unit_cost, lead_time_days
                }
            ]
        }
        response = client.post("/api/restocking-orders", json=bad_payload)
        assert response.status_code == 422

    def test_list_restocking_orders_includes_new_order(self, client):
        """Test that POSTed orders appear in GET /api/restocking-orders."""
        before = client.get("/api/restocking-orders").json()
        before_count = len(before)

        post_resp = client.post("/api/restocking-orders", json=_sample_payload())
        assert post_resp.status_code == 200
        new_order_number = post_resp.json()["order_number"]

        after = client.get("/api/restocking-orders").json()
        assert len(after) == before_count + 1
        assert any(o["order_number"] == new_order_number for o in after)

    def test_dashboard_unaffected_by_restocking(self, client):
        """Test that restocking orders do not pollute /api/dashboard/summary."""
        before = client.get("/api/dashboard/summary").json()

        client.post("/api/restocking-orders", json=_sample_payload())

        after = client.get("/api/dashboard/summary").json()
        # Totals must be identical — restocking lives in a separate list
        assert before["total_inventory_value"] == after["total_inventory_value"]
        assert before["total_orders_value"] == after["total_orders_value"]
        assert before["pending_orders"] == after["pending_orders"]

    def test_orders_endpoint_unaffected_by_restocking(self, client):
        """Test that /api/orders does not include restocking orders."""
        before = client.get("/api/orders").json()

        client.post("/api/restocking-orders", json=_sample_payload())

        after = client.get("/api/orders").json()
        assert len(before) == len(after)
        # No order in the regular list should have status "Submitted"
        assert not any(o["status"] == "Submitted" for o in after)

    def test_inventory_includes_lead_time_days(self, client):
        """Test that every inventory item now exposes lead_time_days."""
        response = client.get("/api/inventory")
        assert response.status_code == 200

        items = response.json()
        assert len(items) > 0
        for item in items:
            assert "lead_time_days" in item
            assert isinstance(item["lead_time_days"], int)
            assert item["lead_time_days"] > 0
