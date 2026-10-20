"""Standalone tests for the local, exact-match OCPP policy."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

MODULE = Path(__file__).parents[1] / 'custom_components/growatt_thor/authorization.py'
spec = importlib.util.spec_from_file_location('thor_authorization_unit', MODULE)
auth = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = auth
spec.loader.exec_module(auth)


def restricted(*tags):
    return auth.policy_from_input(auth.AuthorizationPolicy(), {
        auth.CONF_RESTRICT_AUTHORIZATION: True,
        auth.CONF_AUTHORIZED_TAGS: '\n'.join(tags),
    })


def restricted_without_ha_start(*tags):
    return auth.policy_from_input(auth.AuthorizationPolicy(), {
        auth.CONF_RESTRICT_AUTHORIZATION: True,
        auth.CONF_ALLOW_HA_REMOTE_START: False,
        auth.CONF_AUTHORIZED_TAGS: '\n'.join(tags),
    })


class AuthorizationPolicyTest(unittest.TestCase):
    def test_missing_configuration_preserves_open_access(self):
        self.assertEqual(auth.AuthorizationPolicy.from_config(None).status('TEST-CARD'), 'Accepted')

    def test_restricted_empty_list_denies(self):
        self.assertEqual(restricted().status('TEST-CARD'), 'Invalid')

    def test_exact_match_keeps_case_and_leading_zeroes(self):
        policy = restricted('00TestCard')
        self.assertEqual(policy.status('00TestCard'), 'Accepted')
        for tag in ('TestCard', '00testcard', '00TestCard ', 123, None):
            with self.subTest(tag=tag):
                self.assertEqual(policy.status(tag), 'Invalid')

    def test_no_builtin_tag_bypass(self):
        policy = restricted('TEST-CARD')
        for tag in ('12345678', 'freevenIdTag'):
            self.assertEqual(policy.status(tag), 'Invalid')
            self.assertEqual(restricted(tag).status(tag), 'Accepted')

    def test_ha_remote_start_is_a_separate_permission(self):
        policy = restricted('TEST-CARD')
        self.assertTrue(policy.allows_ha_remote_start())
        self.assertEqual(policy.status('12345678'), 'Invalid')
        self.assertFalse(restricted_without_ha_start('TEST-CARD').allows_ha_remote_start())

    def test_legacy_configuration_allows_ha_remote_start(self):
        legacy = restricted('TEST-CARD').as_config()
        legacy.pop(auth.CONF_ALLOW_HA_REMOTE_START)
        self.assertTrue(auth.AuthorizationPolicy.from_config(legacy).allows_ha_remote_start())

    def test_configuration_round_trip_persists_editable_identifiers(self):
        policy = restricted('TEST-CARD', 'SECOND-CARD', 'TEST-CARD')
        data = json.loads(json.dumps(policy.as_config()))
        self.assertEqual(data['id_tags'], ['SECOND-CARD', 'TEST-CARD'])
        self.assertEqual(auth.AuthorizationPolicy.from_config(data), policy)
        self.assertNotIn(next(iter(policy.id_tags)), repr(policy))

    def test_corrupt_configuration_denies_instead_of_opening_access(self):
        for data in (
            {},
            [],
            'open',
            {'restricted': False, 'tag_hashes': []},
            {'restricted': False, 'id_tags': ['TEST CARD']},
            {'restricted': 'false', 'id_tags': []},
        ):
            with self.subTest(data=data):
                policy = auth.AuthorizationPolicy.from_config(data)
                self.assertFalse(policy.valid)
                self.assertEqual(policy.status('TEST-CARD'), 'Invalid')

    def test_hash_only_list_is_not_migrated_but_keeps_ha_form_preference(self):
        policy = auth.AuthorizationPolicy.from_config({
            'restricted': True,
            'tag_hashes': ['0' * 64],
            auth.CONF_ALLOW_HA_REMOTE_START: True,
        })
        self.assertFalse(policy.valid)
        self.assertTrue(policy.allow_ha_remote_start)
        self.assertFalse(policy.allows_ha_remote_start())
        self.assertFalse(policy.id_tags)

    def test_omitted_list_preserves_and_supplied_list_replaces(self):
        policy = restricted('OLD-CARD')
        kept = auth.policy_from_input(policy, {auth.CONF_RESTRICT_AUTHORIZATION: True})
        self.assertEqual(kept, policy)
        replaced = auth.policy_from_input(policy, {
            auth.CONF_RESTRICT_AUTHORIZATION: True,
            auth.CONF_AUTHORIZED_TAGS: ' NEW-CARD \n\n',
        })
        self.assertEqual(replaced.status('OLD-CARD'), 'Invalid')
        self.assertEqual(replaced.status('NEW-CARD'), 'Accepted')

    def test_blank_list_and_restrict_denies_everyone(self):
        cleared = auth.policy_from_input(restricted('TEST-CARD'), {
            auth.CONF_RESTRICT_AUTHORIZATION: True,
            auth.CONF_AUTHORIZED_TAGS: '',
        })
        self.assertEqual(cleared.status('TEST-CARD'), 'Invalid')
        self.assertFalse(cleared.id_tags)

    def test_invalid_input_is_rejected_without_echoing_identifiers(self):
        for tag in ('X' * 21, 'TEST CARD', 'TÉST', '\n'.join(f'TEST{i}' for i in range(101))):
            with self.subTest(length=len(tag)):
                with self.assertRaisesRegex(ValueError, '^invalid_authorization$'):
                    restricted(tag)
    def test_invalid_wire_identifier_denied_even_in_open_mode(self):
        for tag in ('', 'X' * 21, None, 123, 'TEST CARD'):
            self.assertEqual(auth.AuthorizationPolicy().status(tag), 'Invalid')

    def test_diagnostics_are_bounded_and_do_not_disclose_tags(self):
        runtime = auth.LocalAuthorization(restricted('TEST-CARD').as_config())
        runtime.decide('TEST-CARD', 'Authorize', '2026-09-04T10:00:00Z')
        runtime.decide('OTHER-CARD', 'StartTransaction', '2026-09-04T10:01:00Z')
        data = runtime.diagnostics()
        self.assertEqual(data['last_decision']['status'], 'Invalid')
        self.assertEqual(data['last_decision']['action'], 'StartTransaction')
        self.assertEqual(data['allowed_tag_count'], 1)
        self.assertNotIn('CARD', json.dumps(data))
        self.assertNotIn(next(iter(runtime.policy.id_tags)), json.dumps(data))
        data['last_decision']['status'] = 'Accepted'
        self.assertEqual(runtime.last_decision['status'], 'Invalid')

    def test_policy_update_takes_effect_for_next_decision(self):
        runtime = auth.LocalAuthorization(restricted('TEST-CARD').as_config())
        self.assertEqual(runtime.decide('TEST-CARD', 'Authorize', 'now'), 'Accepted')
        runtime.policy = restricted('OTHER-CARD')
        self.assertEqual(runtime.decide('TEST-CARD', 'StartTransaction', 'later'), 'Invalid')

    def test_ha_remote_start_grant_is_one_shot_and_does_not_authorize_cards(self):
        runtime = auth.LocalAuthorization(restricted('TEST-CARD').as_config())
        self.assertTrue(runtime.begin_ha_remote_start('12345678'))
        self.assertEqual(runtime.decide('12345678', 'Authorize', 'now'), 'Invalid')
        self.assertEqual(runtime.decide('12345678', 'StartTransaction', 'later'), 'Accepted')
        self.assertEqual(runtime.decide('12345678', 'StartTransaction', 'again'), 'Invalid')

    def test_disabled_ha_remote_start_never_creates_grant(self):
        runtime = auth.LocalAuthorization(restricted_without_ha_start('TEST-CARD').as_config())
        self.assertFalse(runtime.begin_ha_remote_start('12345678'))
        self.assertEqual(runtime.decide('12345678', 'StartTransaction', 'later'), 'Invalid')

    def test_expired_ha_remote_start_grant_is_rejected(self):
        runtime = auth.LocalAuthorization(restricted('TEST-CARD').as_config())
        self.assertTrue(runtime.begin_ha_remote_start('12345678', ttl=-1))
        self.assertEqual(runtime.decide('12345678', 'StartTransaction', 'later'), 'Invalid')

    def test_explicit_charger_mode_can_bypass_card_policy_for_start_only(self):
        runtime = auth.LocalAuthorization(restricted('TEST-CARD').as_config())
        self.assertEqual(
            runtime.decide(
                'freevenIdTag',
                'StartTransaction',
                'now',
                card_policy_applies=False,
            ),
            'Accepted',
        )
        self.assertEqual(runtime.last_decision['source'], 'charger_mode')
        self.assertEqual(runtime.decide('freevenIdTag', 'Authorize', 'later'), 'Invalid')


if __name__ == '__main__':
    unittest.main()
