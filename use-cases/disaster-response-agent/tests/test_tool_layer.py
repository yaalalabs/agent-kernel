"""
Deterministic tests for tool.py's business logic - intake extraction, urgency scoring,
resource matching (including distance/transport), duplicate detection, merge behavior, and
notification behavior.

These tests call tool.py functions directly and never touch an LLM, so they run instantly,
for free, with no API key required - they're testing the deterministic tools the agents call,
not the agents' natural-language reasoning around them (see test_agent_e2e.py for that).

Run with:
    uv run pytest tests/test_tool_layer.py -v
"""

import json

import pytest

import tool


@pytest.fixture(autouse=True)
def reset_state():
    """Every test gets a clean slate: no leftover requests/offers/intakes from other tests."""
    tool._STATE.clear()
    tool._INTAKE_BUFFER.clear()
    tool._seed_demo_data()
    yield
    tool._STATE.clear()
    tool._INTAKE_BUFFER.clear()


def submit(**kwargs):
    """Helper: submit_intake and return (intake_id, parsed record)."""
    defaults = {
        "message_type": "need",
        "resource_type": "drinking water",
        "quantity": 10,
        "unit": "liters",
        "location": "Galle",
        "raw_message": "Need drinking water in Galle",
        "contact_name": "",
        "contact_phone": "",
    }
    defaults.update(kwargs)
    result = json.loads(tool.submit_intake(**defaults))
    return result["intake_id"], result["record"]


# ----------------------------------------------------------------------------------
# Intake extraction
# ----------------------------------------------------------------------------------
class TestIntakeExtraction:
    def test_basic_need_is_recorded(self):
        intake_id, record = submit()
        assert intake_id.startswith("intake-")
        assert record["message_type"] == "need"
        assert record["resource_type"] == "drinking water"
        assert record["region"] == "galle"
        assert record["quantity"] == 10

    def test_offer_message_type_normalizes(self):
        _, record = submit(message_type="OFFER", resource_type="Food Packs", location="Colombo")
        assert record["message_type"] == "offer"
        assert record["resource_type"] == "food packs"  # normalized lowercase

    def test_invalid_message_type_defaults_to_need(self):
        _, record = submit(message_type="banana")
        assert record["message_type"] == "need"

    def test_quantity_defaults_to_one_if_zero_or_missing(self):
        _, record = submit(quantity=0)
        assert record["quantity"] == 1

    def test_location_is_normalized_for_region_but_display_preserved(self):
        _, record = submit(location="  GALLE  ")
        assert record["region"] == "galle"
        assert record["location_display"] == "  GALLE  "

    def test_transport_flag_detected_for_need_with_no_transport(self):
        _, record = submit(raw_message="Elderly couple needs medicine urgently in Matara, no transport")
        assert record["transport_flag"] is True

    def test_transport_flag_false_when_not_mentioned(self):
        _, record = submit(raw_message="Need drinking water in Galle")
        assert record["transport_flag"] is False

    def test_transport_flag_detected_for_offer_that_can_deliver(self):
        _, record = submit(
            message_type="offer", raw_message="We have 50 food packs and can deliver in Colombo",
            resource_type="food packs", location="Colombo",
        )
        assert record["transport_flag"] is True


# ----------------------------------------------------------------------------------
# Urgency scoring
# ----------------------------------------------------------------------------------
class TestUrgencyScoring:
    def test_critical_resource_scores_higher_than_low_criticality(self):
        water_id, _ = submit(resource_type="drinking water")
        clothing_id, _ = submit(resource_type="clothing")

        water_result = json.loads(tool.score_urgency(water_id))
        clothing_result = json.loads(tool.score_urgency(clothing_id))

        assert water_result["urgency_score"] > clothing_result["urgency_score"]

    def test_vulnerable_group_detected_from_message_text(self):
        intake_id, _ = submit(raw_message="Elderly couple needs medicine urgently in Matara")
        result = json.loads(tool.score_urgency(intake_id))
        assert "elderly" in result["vulnerable_groups"]

    def test_explicit_vulnerable_groups_param_is_merged_in(self):
        intake_id, _ = submit(raw_message="Need food in Colombo")  # no keyword in text
        result = json.loads(tool.score_urgency(intake_id, vulnerable_groups="children, pregnant"))
        assert set(result["vulnerable_groups"]) == {"children", "pregnant"}

    def test_urgency_band_thresholds(self):
        # drinking water (criticality 5) + 2 vulnerable groups -> should land in critical/high
        intake_id, _ = submit(raw_message="Pregnant woman with infant needs drinking water urgently")
        result = json.loads(tool.score_urgency(intake_id))
        assert result["urgency_band"] in ("high", "critical")
        assert 0 <= result["urgency_score"] <= 100

    def test_unknown_intake_id_returns_error(self):
        result = json.loads(tool.score_urgency("intake-does-not-exist"))
        assert "error" in result


# ----------------------------------------------------------------------------------
# Resource matching (quantity, distance/proximity, transport)
# ----------------------------------------------------------------------------------
class TestResourceMatching:
    def test_same_region_offer_is_matched(self):
        # Seed data includes an open "drinking water" offer in Galle.
        intake_id, _ = submit(resource_type="drinking water", location="Galle", quantity=50)
        result = json.loads(tool.match_resources(intake_id))
        assert result["candidate_count"] >= 1
        assert result["matches"][0]["region"] == "galle"
        assert result["matches"][0]["distance_km"] == 0

    def test_same_region_match_outranks_cross_region_for_equal_coverage(self):
        # Two open offers of the same resource_type/quantity in different regions - same-region
        # one must win on proximity alone.
        tool._region_store("colombo")["offers"]["offer-near"] = {
            "id": "offer-near", "region": "colombo", "resource_type": "tents", "quantity": 10,
            "unit": "units", "donor_name": "Near Donor", "donor_phone": "+9400", "status": "open",
            "created_at": "now", "transport_flag": None, "history": [],
        }
        tool._region_store("ratnapura")["offers"]["offer-far"] = {
            "id": "offer-far", "region": "ratnapura", "resource_type": "tents", "quantity": 10,
            "unit": "units", "donor_name": "Far Donor", "donor_phone": "+9401", "status": "open",
            "created_at": "now", "transport_flag": None, "history": [],
        }
        intake_id, _ = submit(resource_type="tents", location="Colombo", quantity=10)
        result = json.loads(tool.match_resources(intake_id))
        assert result["matches"][0]["id"] == "offer-near"
        assert result["matches"][0]["match_score"] > result["matches"][1]["match_score"]

    def test_cross_region_match_surfaces_when_no_local_offer(self):
        # No "medicine" offer in Matara at all - the only one is in Ratnapura (seeded, can deliver).
        intake_id, _ = submit(
            resource_type="medicine", location="Matara", quantity=5,
            raw_message="Elderly couple needs medicine urgently in Matara, no transport",
        )
        result = json.loads(tool.match_resources(intake_id))
        assert result["candidate_count"] >= 1
        top = result["matches"][0]
        assert top["region"] == "ratnapura"
        assert top["distance_km"] > 0
        assert top["transport_flag"] is True
        assert "good fit" in top["transport_note"]

    def test_no_transport_requester_with_no_compatible_donor_scores_lower(self):
        tool._region_store("kalutara")["offers"]["offer-pickup-only"] = {
            "id": "offer-pickup-only", "region": "kalutara", "resource_type": "blankets",
            "quantity": 20, "unit": "units", "donor_name": "Pickup Donor", "donor_phone": "+9402",
            "status": "open", "created_at": "now", "transport_flag": False, "history": [],
        }
        intake_id, _ = submit(
            resource_type="blankets", location="matara", quantity=5,
            raw_message="Need blankets in Matara, no vehicle to travel",
        )
        result = json.loads(tool.match_resources(intake_id))
        top = result["matches"][0]
        assert top["transport_flag"] is False
        assert "confirm delivery" in top["transport_note"]

    def test_no_candidates_returns_empty_matches(self):
        intake_id, _ = submit(resource_type="boats", location="jaffna", quantity=1)
        result = json.loads(tool.match_resources(intake_id))
        assert result["candidate_count"] == 0
        assert result["matches"] == []

    def test_fulfilled_candidates_are_excluded(self):
        offers = tool._region_store("galle")["offers"]
        offer_id = next(iter(offers))
        offers[offer_id]["status"] = "fulfilled"
        intake_id, _ = submit(resource_type="drinking water", location="galle", quantity=10)
        result = json.loads(tool.match_resources(intake_id))
        assert all(m["id"] != offer_id for m in result["matches"])


# ----------------------------------------------------------------------------------
# Duplicate detection
# ----------------------------------------------------------------------------------
class TestDuplicateDetection:
    def test_no_duplicates_for_first_request_in_region(self):
        intake_id, _ = submit(resource_type="tents", location="jaffna")
        result = json.loads(tool.check_pending_duplicates(intake_id))
        assert result["duplicate_count"] == 0

    def test_detects_existing_open_request_same_type_and_region(self):
        first_id, _ = submit(resource_type="shelter", location="matara")
        tool.finalize_record(first_id)

        second_id, _ = submit(resource_type="shelter", location="matara")
        result = json.loads(tool.check_pending_duplicates(second_id))
        assert result["duplicate_count"] == 1

    def test_different_region_is_not_a_duplicate(self):
        first_id, _ = submit(resource_type="shelter", location="matara")
        tool.finalize_record(first_id)

        second_id, _ = submit(resource_type="shelter", location="galle")
        result = json.loads(tool.check_pending_duplicates(second_id))
        assert result["duplicate_count"] == 0

    def test_fulfilled_record_is_not_a_duplicate(self):
        first_id, _ = submit(resource_type="shelter", location="matara")
        finalized = json.loads(tool.finalize_record(first_id))
        finalized_id = finalized["record"]["id"]
        tool._region_store("matara")["requests"][finalized_id]["status"] = "fulfilled"

        second_id, _ = submit(resource_type="shelter", location="matara")
        result = json.loads(tool.check_pending_duplicates(second_id))
        assert result["duplicate_count"] == 0


# ----------------------------------------------------------------------------------
# Merge behavior
# ----------------------------------------------------------------------------------
class TestMergeBehavior:
    def test_finalize_without_duplicate_creates_new_record(self):
        intake_id, _ = submit(resource_type="tents", location="jaffna", quantity=3)
        result = json.loads(tool.finalize_record(intake_id))
        assert result["merged"] is False
        assert result["record"]["quantity"] == 3
        assert result["record"]["status"] == "open"

    def test_finalize_with_duplicate_id_merges_quantities(self):
        first_id, _ = submit(resource_type="tents", location="jaffna", quantity=3)
        first_result = json.loads(tool.finalize_record(first_id))
        first_record_id = first_result["record"]["id"]

        second_id, _ = submit(resource_type="tents", location="jaffna", quantity=4)
        second_result = json.loads(tool.finalize_record(second_id, duplicate_id=first_record_id))

        assert second_result["merged"] is True
        assert second_result["record"]["id"] == first_record_id
        assert second_result["record"]["quantity"] == 7  # 3 + 4
        assert len(second_result["record"]["history"]) == 2  # created + merged

    def test_merge_takes_the_higher_urgency_score(self):
        first_id, _ = submit(resource_type="medicine", location="galle", quantity=2)
        tool.score_urgency(first_id, vulnerable_groups="")
        first_result = json.loads(tool.finalize_record(first_id))
        first_record_id = first_result["record"]["id"]
        low_score = first_result["record"]["urgency_score"]

        second_id, _ = submit(
            resource_type="medicine", location="galle", quantity=2,
            raw_message="Pregnant woman needs medicine urgently",
        )
        tool.score_urgency(second_id)
        second_result = json.loads(tool.finalize_record(second_id, duplicate_id=first_record_id))

        assert second_result["record"]["urgency_score"] >= low_score

    def test_merge_adopts_transport_flag_if_not_already_set(self):
        first_id, _ = submit(resource_type="medicine", location="galle", quantity=2)
        first_result = json.loads(tool.finalize_record(first_id))
        first_record_id = first_result["record"]["id"]
        assert first_result["record"]["transport_flag"] is False  # no keyword in default message

        second_id, _ = submit(
            resource_type="medicine", location="galle", quantity=2,
            raw_message="Need medicine in Galle, no vehicle available",
        )
        second_result = json.loads(tool.finalize_record(second_id, duplicate_id=first_record_id))
        assert second_result["record"]["transport_flag"] is True


# ----------------------------------------------------------------------------------
# Notification / dispatch behavior
# ----------------------------------------------------------------------------------
class TestDispatchNotification:
    def test_dispatch_between_valid_records_simulates_in_dummy_mode(self):
        intake_id, _ = submit(resource_type="drinking water", location="galle", quantity=10)
        matches = json.loads(tool.match_resources(intake_id))
        offer_id = matches["matches"][0]["id"]
        final = json.loads(tool.finalize_record(intake_id))
        record_id = final["record"]["id"]

        result = json.loads(tool.dispatch_notification(record_id=record_id, matched_id=offer_id))
        assert result["status"] == "simulated"
        assert result["whatsapp_send_result"]["sent"] is False
        assert result["cross_region"] is False

    def test_dispatch_marks_both_records_matched(self):
        intake_id, _ = submit(resource_type="drinking water", location="galle", quantity=10)
        matches = json.loads(tool.match_resources(intake_id))
        offer_id = matches["matches"][0]["id"]
        final = json.loads(tool.finalize_record(intake_id))
        record_id = final["record"]["id"]

        tool.dispatch_notification(record_id=record_id, matched_id=offer_id)

        assert tool._region_store("galle")["requests"][record_id]["status"] == "matched"
        assert tool._region_store("galle")["offers"][offer_id]["status"] == "matched"

    def test_dispatch_flags_cross_region_matches(self):
        intake_id, _ = submit(
            resource_type="medicine", location="matara", quantity=5,
            raw_message="Elderly couple needs medicine urgently in Matara, no transport",
        )
        matches = json.loads(tool.match_resources(intake_id))
        offer_id = matches["matches"][0]["id"]  # the seeded Ratnapura offer
        final = json.loads(tool.finalize_record(intake_id))
        record_id = final["record"]["id"]

        result = json.loads(tool.dispatch_notification(record_id=record_id, matched_id=offer_id))
        assert result["cross_region"] is True
        assert result["distance_km"] > 0
        assert "cross-region match" in result["message_text"]

    def test_dispatch_with_missing_ids_returns_error(self):
        result = json.loads(tool.dispatch_notification(record_id="nope", matched_id="also-nope"))
        assert "error" in result
        assert result["record_id_found"] is False
        assert result["matched_id_found"] is False


# ----------------------------------------------------------------------------------
# End-to-end tool-layer workflow (no LLM - exercises the full chain of tool calls a
# dedup_dispatch_agent run would make, in the order the agents call them)
# ----------------------------------------------------------------------------------
class TestEndToEndToolWorkflow:
    def test_full_pipeline_need_to_dispatch(self):
        intake_id, _ = submit(
            resource_type="drinking water", location="Galle", quantity=100,
            raw_message="Need drinking water in Galle",
        )
        urgency = json.loads(tool.score_urgency(intake_id))
        assert urgency["urgency_band"] in ("low", "medium", "high", "critical")

        matches = json.loads(tool.match_resources(intake_id))
        assert matches["candidate_count"] >= 1

        dup_check = json.loads(tool.check_pending_duplicates(intake_id))
        assert dup_check["duplicate_count"] == 0

        finalized = json.loads(tool.finalize_record(intake_id))
        assert finalized["merged"] is False
        record_id = finalized["record"]["id"]

        best_match_id = matches["matches"][0]["id"]
        dispatch = json.loads(tool.dispatch_notification(record_id=record_id, matched_id=best_match_id))
        assert dispatch["status"] in ("dispatched", "simulated")

        status = json.loads(tool.get_region_status("galle"))
        matched_ids = {r["id"] for r in status["open_requests"] + status["open_offers"]}
        # Both records are now "matched", not "fulfilled", so they still show up as open.
        assert record_id in matched_ids
        assert best_match_id in matched_ids
