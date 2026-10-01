"""Checks for departures before active parcels are filtered."""

import runpy
import unittest
from pathlib import Path


HELPERS = runpy.run_path(
    str(
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "polish_shipment_tracking"
        / "helpers.py"
    )
)
reconcile_departed_parcels = HELPERS["reconcile_departed_parcels"]
get_shipment_entity_id = HELPERS["get_shipment_entity_id"]


class ShipmentLifecycleTests(unittest.TestCase):
    def test_collected_parcel_emits_actual_terminal_status(self):
        previous = [{"shipmentNumber": "123", "status": "READY_TO_PICKUP"}]
        current = [{"shipmentNumber": "123", "status": "COLLECTED_BY_CUSTOMER"}]
        self.assertEqual(
            reconcile_departed_parcels(previous, current, "inpost", {}),
            (
                [
                    (
                        "shipment_status_changed",
                        {
                            "courier": "inpost",
                            "shipment_id": "123",
                            "old_status_raw": "READY_TO_PICKUP",
                            "old_status_key": "waiting_for_pickup",
                            "new_status_raw": "COLLECTED_BY_CUSTOMER",
                            "new_status_key": "delivered",
                        },
                    )
                ],
                [],
                {},
            ),
        )

    def test_disappearance_requires_two_consecutive_polls(self):
        previous = [{"shipmentNumber": "123", "status": "READY_TO_PICKUP"}]
        first = reconcile_departed_parcels(previous, [], "inpost", {})
        self.assertEqual(first, ([], previous, {"123": 1}))
        self.assertEqual(
            reconcile_departed_parcels(first[1], [], "inpost", first[2]),
            (
                [
                    (
                        "shipment_removed",
                        {
                            "courier": "inpost",
                            "shipment_id": "123",
                            "old_status_raw": "READY_TO_PICKUP",
                            "old_status_key": "waiting_for_pickup",
                            "reason": "missing_from_feed",
                        },
                    )
                ],
                [],
                {},
            ),
        )

    def test_reappearance_resets_missing_count(self):
        previous = [{"shipmentNumber": "123", "status": "READY_TO_PICKUP"}]
        first = reconcile_departed_parcels(previous, [], "inpost", {})
        self.assertEqual(
            reconcile_departed_parcels(first[1], previous, "inpost", first[2]),
            ([], [], {}),
        )
        self.assertEqual(reconcile_departed_parcels(previous, [], "inpost", {}), first)

    def test_archived_without_status_is_removed(self):
        previous = [{"trackingId": "123", "state": "AWIZOWANA"}]
        current = [{"trackingId": "123", "state": None, "archived": True}]
        self.assertEqual(
            reconcile_departed_parcels(previous, current, "pocztex", {})[0][0][1]["reason"],
            "archived",
        )

    def test_explicit_terminal_status_after_one_missing_poll(self):
        previous = [{"shipmentNumber": "123", "status": "READY_TO_PICKUP"}]
        first = reconcile_departed_parcels(previous, [], "inpost", {})
        terminal = [{"shipmentNumber": "123", "status": "COLLECTED_BY_CUSTOMER"}]
        events, retained, counts = reconcile_departed_parcels(
            first[1], terminal, "inpost", first[2]
        )
        self.assertEqual(events[0][0], "shipment_status_changed")
        self.assertEqual((retained, counts), ([], {}))

    def test_first_refresh_and_active_transition_do_not_emit_departures(self):
        old = [{"shipmentNumber": "123", "status": "CONFIRMED"}]
        new = [{"shipmentNumber": "123", "status": "READY_TO_PICKUP"}]
        self.assertEqual(reconcile_departed_parcels(None, new, "inpost", {}), ([], [], {}))
        self.assertEqual(reconcile_departed_parcels(old, new, "inpost", {}), ([], [], {}))

    def test_entity_id_lookup_prefers_account_scoped_and_checks_owner(self):
        class Entity:
            def __init__(self, entry_id):
                self.config_entry_id = entry_id

        class Registry:
            def __init__(self, entries):
                self.entries = entries

            def async_get_entity_id(self, domain, platform, unique_id):
                return self.entries.get(unique_id, (None, None))[0]

            def async_get(self, entity_id):
                return next(
                    (Entity(owner) for entity, owner in self.entries.values() if entity == entity_id),
                    None,
                )

        registry = Registry({
            "inpost_account-1_123": ("sensor.new", "account-1"),
            "inpost_123": ("sensor.old", "other-account"),
        })
        self.assertEqual(
            get_shipment_entity_id(registry, "polish_shipment_tracking", "inpost", "account-1", "123"),
            "sensor.new",
        )
        self.assertIsNone(
            get_shipment_entity_id(registry, "polish_shipment_tracking", "inpost", "account-2", "123")
        )
        registry = Registry({"inpost_123": ("sensor.old", "account-1")})
        self.assertEqual(
            get_shipment_entity_id(registry, "polish_shipment_tracking", "inpost", "account-1", "123"),
            "sensor.old",
        )


if __name__ == "__main__":
    unittest.main()
