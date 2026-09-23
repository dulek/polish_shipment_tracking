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
get_departed_parcel_events = HELPERS["get_departed_parcel_events"]


class ShipmentLifecycleTests(unittest.TestCase):
    def test_collected_parcel_emits_actual_terminal_status(self):
        previous = [{"shipmentNumber": "123", "status": "READY_TO_PICKUP"}]
        current = [{"shipmentNumber": "123", "status": "COLLECTED_BY_CUSTOMER"}]
        self.assertEqual(
            get_departed_parcel_events(previous, current, "inpost"),
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
        )

    def test_disappearance_does_not_claim_delivery(self):
        previous = [{"shipmentNumber": "123", "status": "READY_TO_PICKUP"}]
        self.assertEqual(
            get_departed_parcel_events(previous, [], "inpost"),
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
        )

    def test_archived_without_status_is_removed(self):
        previous = [{"trackingId": "123", "state": "AWIZOWANA"}]
        current = [{"trackingId": "123", "state": None, "archived": True}]
        self.assertEqual(
            get_departed_parcel_events(previous, current, "pocztex")[0][1]["reason"],
            "archived",
        )

    def test_first_refresh_and_active_transition_do_not_emit_departures(self):
        old = [{"shipmentNumber": "123", "status": "CONFIRMED"}]
        new = [{"shipmentNumber": "123", "status": "READY_TO_PICKUP"}]
        self.assertEqual(get_departed_parcel_events(None, new, "inpost"), [])
        self.assertEqual(get_departed_parcel_events(old, new, "inpost"), [])


if __name__ == "__main__":
    unittest.main()
