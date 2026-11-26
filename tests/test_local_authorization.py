"""Standalone tests for the local, exact-match OCPP policy."""

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import load_package_module, register_package

MODULE = Path(__file__).parents[1] / "custom_components/growatt_thor/charging/authorization.py"
package = register_package("thor_authorization_unit")
auth = load_package_module("thor_authorization_unit.authorization", MODULE)


def restricted(*tags):
    return auth.policy_from_input(
        auth.AuthorizationPolicy(),
        {
            auth.CONF_RESTRICT_AUTHORIZATION: True,
            auth.CONF_AUTHORIZED_TAGS: "\n".join(tags),
        },
    )


def restricted_without_ha_start(*tags):
    return auth.policy_from_input(
        auth.AuthorizationPolicy(),
        {
            auth.CONF_RESTRICT_AUTHORIZATION: True,
            auth.CONF_ALLOW_HA_REMOTE_START: False,
            auth.CONF_AUTHORIZED_TAGS: "\n".join(tags),
        },
    )


class AuthorizationPolicyTest(unittest.TestCase):
    def test_named_cards_round_trip_and_keep_exact_matching(self):
        policy = restricted("00AbC | Familienauto", "OTHER", "A|B | Work | Home")
        self.assertEqual(policy.status("00AbC"), "Accepted")
        self.assertEqual(policy.status("00abc"), "Invalid")
        self.assertEqual(policy.status("Familienauto"), "Invalid")
        self.assertEqual(policy.aliases, {"00AbC": "Familienauto", "A|B": "Work | Home"})
        restored = auth.AuthorizationPolicy.from_config(json.loads(json.dumps(policy.as_config())))
        self.assertEqual(restored, policy)
        self.assertEqual(restricted(*policy.editable_tags().splitlines()), policy)
        self.assertNotIn("Familienauto", repr(policy))
        kept = auth.policy_from_input(policy, {auth.CONF_RESTRICT_AUTHORIZATION: True})
        self.assertEqual(kept, policy)
        cleared = auth.policy_from_input(
            policy,
            {
                auth.CONF_RESTRICT_AUTHORIZATION: True,
                auth.CONF_AUTHORIZED_TAGS: "00AbC",
            },
        )
        self.assertEqual(cleared.aliases, {})
        self.assertEqual(cleared.id_tags, {"00AbC"})

    def test_learning_addition_preserves_permissions_and_enforces_limits(self):
        policy = restricted_without_ha_start("OLD | Old name")
        added = policy.with_card("00New", "New name")
        self.assertTrue(added.restricted)
        self.assertFalse(added.allow_ha_remote_start)
        self.assertEqual(added.aliases, {"OLD": "Old name", "00New": "New name"})
        self.assertEqual(added.with_card("00New").aliases, {"OLD": "Old name"})
        full = restricted(*(f"CARD{i}" for i in range(100)))
        self.assertEqual(len(full.with_card("CARD0", "Rename").id_tags), 100)
        with self.assertRaisesRegex(ValueError, "^invalid_authorization$"):
            full.with_card("EXTRA")
        for alias in ("x" * 81, "Line\nbreak", "Tab\tname", "Nul\x00", 12):
            with (
                self.subTest(alias=alias),
                self.assertRaisesRegex(ValueError, "^invalid_rfid_alias$"),
            ):
                policy.with_card("NEW", alias)
        for text in ("A | First\nA | Second", "A | " + "x" * 81):
            with self.assertRaises(ValueError):
                restricted(text)

    def test_legacy_and_malformed_alias_metadata_do_not_change_access(self):
        legacy = {"restricted": True, "id_tags": ["A"]}
        self.assertEqual(auth.AuthorizationPolicy.from_config(legacy).aliases, {})
        for aliases in (None, [], {"A": 123}, {"A": "bad\nname", "B": "Unexpected"}):
            policy = auth.AuthorizationPolicy.from_config({**legacy, "aliases": aliases})
            self.assertTrue(policy.valid)
            self.assertEqual(policy.status("A"), "Accepted")
            self.assertEqual(policy.status("B"), "Invalid")
            self.assertEqual(policy.aliases, {})

    def test_missing_configuration_preserves_open_access(self):
        self.assertEqual(auth.AuthorizationPolicy.from_config(None).status("TEST-CARD"), "Accepted")

    def test_restricted_empty_list_denies(self):
        self.assertEqual(restricted().status("TEST-CARD"), "Invalid")

    def test_exact_match_keeps_case_and_leading_zeroes(self):
        policy = restricted("00TestCard")
        self.assertEqual(policy.status("00TestCard"), "Accepted")
        for tag in ("TestCard", "00testcard", "00TestCard ", 123, None):
            with self.subTest(tag=tag):
                self.assertEqual(policy.status(tag), "Invalid")

    def test_no_builtin_tag_bypass(self):
        policy = restricted("TEST-CARD")
        for tag in ("12345678", "freevenIdTag"):
            self.assertEqual(policy.status(tag), "Invalid")
            self.assertEqual(restricted(tag).status(tag), "Accepted")

    def test_ha_remote_start_is_a_separate_permission(self):
        policy = restricted("TEST-CARD")
        self.assertTrue(policy.allows_ha_remote_start())
        self.assertEqual(policy.status("12345678"), "Invalid")
        self.assertFalse(restricted_without_ha_start("TEST-CARD").allows_ha_remote_start())

    def test_legacy_configuration_allows_ha_remote_start(self):
        legacy = restricted("TEST-CARD").as_config()
        legacy.pop(auth.CONF_ALLOW_HA_REMOTE_START)
        self.assertTrue(auth.AuthorizationPolicy.from_config(legacy).allows_ha_remote_start())

    def test_configuration_round_trip_persists_editable_identifiers(self):
        policy = restricted("TEST-CARD", "SECOND-CARD", "TEST-CARD")
        data = json.loads(json.dumps(policy.as_config()))
        self.assertEqual(data["id_tags"], ["SECOND-CARD", "TEST-CARD"])
        self.assertEqual(auth.AuthorizationPolicy.from_config(data), policy)
        self.assertNotIn(next(iter(policy.id_tags)), repr(policy))

    def test_corrupt_configuration_denies_instead_of_opening_access(self):
        for data in (
            {},
            [],
            "open",
            {"restricted": False, "tag_hashes": []},
            {"restricted": False, "id_tags": ["TEST CARD"]},
            {"restricted": "false", "id_tags": []},
        ):
            with self.subTest(data=data):
                policy = auth.AuthorizationPolicy.from_config(data)
                self.assertFalse(policy.valid)
                self.assertEqual(policy.status("TEST-CARD"), "Invalid")

    def test_hash_only_list_is_not_migrated_but_keeps_ha_form_preference(self):
        policy = auth.AuthorizationPolicy.from_config(
            {
                "restricted": True,
                "tag_hashes": ["0" * 64],
                auth.CONF_ALLOW_HA_REMOTE_START: True,
            }
        )
        self.assertFalse(policy.valid)
        self.assertTrue(policy.allow_ha_remote_start)
        self.assertTrue(policy.allows_ha_remote_start())
        self.assertFalse(policy.id_tags)

    def test_legacy_cards_keep_only_explicit_ha_grants(self):
        config = {
            "restricted": True,
            "tag_hashes": ["0" * 64],
            auth.CONF_ALLOW_HA_REMOTE_START: True,
        }
        original = json.dumps(config)
        runtime = auth.LocalAuthorization(config)
        self.assertTrue(runtime.begin_ha_remote_start("12345678"))
        self.assertEqual(runtime.decide("12345678", "Authorize", "now"), "Invalid")
        self.assertEqual(runtime.decide("12345678", "StartTransaction", "now"), "Accepted")
        self.assertEqual(runtime.decide("12345678", "StartTransaction", "later"), "Invalid")
        self.assertEqual(json.dumps(config), original)
        for flag in (False, None, "true", 1):
            data = {**config, auth.CONF_ALLOW_HA_REMOTE_START: flag}
            self.assertFalse(auth.LocalAuthorization(data).begin_ha_remote_start("12345678"))
        for data in (
            {"restricted": True, "tag_hashes": []},
            {**config, "restricted": "true"},
            [],
        ):
            self.assertFalse(auth.LocalAuthorization(data).begin_ha_remote_start("12345678"))

    def test_omitted_list_preserves_and_supplied_list_replaces(self):
        policy = restricted("OLD-CARD")
        kept = auth.policy_from_input(policy, {auth.CONF_RESTRICT_AUTHORIZATION: True})
        self.assertEqual(kept, policy)
        replaced = auth.policy_from_input(
            policy,
            {
                auth.CONF_RESTRICT_AUTHORIZATION: True,
                auth.CONF_AUTHORIZED_TAGS: " NEW-CARD \n\n",
            },
        )
        self.assertEqual(replaced.status("OLD-CARD"), "Invalid")
        self.assertEqual(replaced.status("NEW-CARD"), "Accepted")

    def test_blank_list_and_restrict_denies_everyone(self):
        cleared = auth.policy_from_input(
            restricted("TEST-CARD"),
            {
                auth.CONF_RESTRICT_AUTHORIZATION: True,
                auth.CONF_AUTHORIZED_TAGS: "",
            },
        )
        self.assertEqual(cleared.status("TEST-CARD"), "Invalid")
        self.assertFalse(cleared.id_tags)

    def test_invalid_input_is_rejected_without_echoing_identifiers(self):
        for tag in (
            "X" * 21,
            "TEST CARD",
            "TÉST",
            "\n".join(f"TEST{i}" for i in range(101)),
        ):
            with self.subTest(length=len(tag)):
                with self.assertRaisesRegex(ValueError, "^invalid_authorization$"):
                    restricted(tag)

    def test_invalid_wire_identifier_denied_even_in_open_mode(self):
        for tag in ("", "X" * 21, None, 123, "TEST CARD"):
            self.assertEqual(auth.AuthorizationPolicy().status(tag), "Invalid")

    def test_diagnostics_are_bounded_and_do_not_disclose_tags(self):
        runtime = auth.LocalAuthorization(restricted("TEST-CARD").as_config())
        runtime.decide("TEST-CARD", "Authorize", "2026-09-04T10:00:00Z")
        runtime.decide("OTHER-CARD", "StartTransaction", "2026-09-04T10:01:00Z")
        data = runtime.diagnostics()
        self.assertEqual(data["last_decision"]["status"], "Invalid")
        self.assertEqual(data["last_decision"]["action"], "StartTransaction")
        self.assertEqual(data["allowed_tag_count"], 1)
        self.assertNotIn("CARD", json.dumps(data))
        self.assertNotIn(next(iter(runtime.policy.id_tags)), json.dumps(data))
        data["last_decision"]["status"] = "Accepted"
        self.assertEqual(runtime.last_decision["status"], "Invalid")

    def test_policy_update_takes_effect_for_next_decision(self):
        runtime = auth.LocalAuthorization(restricted("TEST-CARD").as_config())
        self.assertEqual(runtime.decide("TEST-CARD", "Authorize", "now"), "Accepted")
        runtime.policy = restricted("OTHER-CARD")
        self.assertEqual(runtime.decide("TEST-CARD", "StartTransaction", "later"), "Invalid")

    def test_ha_remote_start_grant_is_one_shot_and_does_not_authorize_cards(self):
        runtime = auth.LocalAuthorization(restricted("TEST-CARD").as_config())
        self.assertTrue(runtime.begin_ha_remote_start("12345678"))
        self.assertEqual(runtime.decide("12345678", "Authorize", "now"), "Invalid")
        self.assertEqual(runtime.decide("12345678", "StartTransaction", "later"), "Accepted")
        self.assertEqual(runtime.decide("12345678", "StartTransaction", "again"), "Invalid")

    def test_disabled_ha_remote_start_never_creates_grant(self):
        runtime = auth.LocalAuthorization(restricted_without_ha_start("TEST-CARD").as_config())
        self.assertFalse(runtime.begin_ha_remote_start("12345678"))
        self.assertEqual(runtime.decide("12345678", "StartTransaction", "later"), "Invalid")

    def test_expired_ha_remote_start_grant_is_rejected(self):
        runtime = auth.LocalAuthorization(restricted("TEST-CARD").as_config())
        self.assertTrue(runtime.begin_ha_remote_start("12345678", ttl=-1))
        self.assertEqual(runtime.decide("12345678", "StartTransaction", "later"), "Invalid")

    def test_explicit_charger_mode_can_bypass_card_policy_for_start_only(self):
        runtime = auth.LocalAuthorization(restricted("TEST-CARD").as_config())
        self.assertEqual(
            runtime.decide(
                "freevenIdTag",
                "StartTransaction",
                "now",
                card_policy_applies=False,
            ),
            "Accepted",
        )
        self.assertEqual(runtime.last_decision["source"], "charger_mode")
        self.assertEqual(runtime.decide("freevenIdTag", "Authorize", "later"), "Invalid")


class RfidLearningTest(unittest.IsolatedAsyncioTestCase):
    async def test_capture_is_opt_in_one_shot_and_never_grants_access(self):
        runtime = auth.LocalAuthorization(restricted("OLD").as_config())
        runtime.decide("BEFORE", "Authorize", "now")
        session = runtime.learning.begin()
        self.assertIsNone(runtime.learning.identifier(session))
        runtime.decide("TECHNICAL", "StartTransaction", "now")
        runtime.decide("INVALID CARD", "Authorize", "now")
        self.assertIsNone(runtime.learning.identifier(session))
        self.assertEqual(runtime.decide("00AbC", "Authorize", "now"), "Invalid")
        runtime.decide("SECOND", "Authorize", "now")
        self.assertEqual(runtime.learning.identifier(session), "00AbC")
        self.assertNotIn("00AbC", repr(session))
        self.assertEqual(runtime.policy.id_tags, {"OLD"})
        self.assertNotIn("00AbC", json.dumps(runtime.diagnostics()))
        other = auth.LocalAuthorization()
        other_session = other.learning.begin()
        self.assertIsNone(other.learning.identifier(other_session))
        runtime.learning.cancel(session)
        self.assertIsNone(session.id_tag)
        other.learning.cancel(other_session)

    async def test_timeout_clears_identifier_and_old_dialog_cannot_cancel_new(self):
        runtime = auth.LocalAuthorization()
        clock_module = sys.modules[auth.RfidLearning.__module__]
        with patch.object(clock_module, "monotonic", return_value=100):
            session = runtime.learning.begin()
            runtime.decide("FIRST", "Authorize", "now")
            with self.assertRaisesRegex(ValueError, "rfid_learning_busy"):
                runtime.learning.begin()
        with patch.object(clock_module, "monotonic", return_value=221):
            with self.assertRaisesRegex(ValueError, "rfid_learning_expired"):
                runtime.learning.identifier(session)
            self.assertIsNone(session.id_tag)
            second = runtime.learning.begin()
            runtime.learning.cancel(session)
            runtime.decide("SECOND", "Authorize", "now")
            self.assertEqual(runtime.learning.identifier(second), "SECOND")
            runtime.learning.cancel(second)

    async def test_closed_dialog_capture_is_cleared_by_timer_without_further_requests(
        self,
    ):
        runtime = auth.LocalAuthorization()
        clock_module = sys.modules[auth.RfidLearning.__module__]
        with patch.object(clock_module, "LEARNING_SECONDS", 0.001):
            session = runtime.learning.begin()
            runtime.decide("TEMPORARY", "Authorize", "now")
            await asyncio.sleep(0.01)
        self.assertIsNone(session.id_tag)
        with self.assertRaisesRegex(ValueError, "rfid_learning_expired"):
            runtime.learning.identifier(session)


if __name__ == "__main__":
    unittest.main()
