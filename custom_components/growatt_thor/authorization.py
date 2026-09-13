"""Local OCPP authorisation policy; independent of card/cloud provisioning."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from time import monotonic
from typing import Mapping

CONF_AUTHORIZATION = "local_authorization"
CONF_ALLOW_HA_REMOTE_START = "allow_ha_remote_start"
CONF_RESTRICT_AUTHORIZATION = "restrict_authorization"
CONF_AUTHORIZED_TAGS = "authorized_id_tags"
CONF_STORED_TAGS = "id_tags"


def _valid_id_tag(value: object) -> bool:
    # Preserve the wire identifier exactly, including case and leading zeroes.
    return isinstance(value, str) and 1 <= len(value) <= 20 and all(
        33 <= ord(char) <= 126 for char in value
    )


def _digest(id_tag: str) -> str:
    return sha256(id_tag.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthorizationPolicy:
    """Missing configuration preserves open access; corrupt data denies."""

    restricted: bool = False
    id_tags: frozenset[str] = field(default_factory=frozenset, repr=False)
    allow_ha_remote_start: bool = True
    valid: bool = True

    @classmethod
    def from_config(cls, data: object) -> AuthorizationPolicy:
        if data is None:
            return cls()
        if not isinstance(data, dict):
            return cls(restricted=True, valid=False)
        restricted = data.get("restricted")
        id_tags = data.get(CONF_STORED_TAGS)
        allow_ha_remote_start = data.get(CONF_ALLOW_HA_REMOTE_START, True)
        if (
            type(restricted) is not bool
            or type(allow_ha_remote_start) is not bool
            or not isinstance(id_tags, list)
            or any(not _valid_id_tag(value) for value in id_tags)
        ):
            return cls(
                restricted=True,
                # Keep the independent form preference visible while the
                # obsolete or corrupt card list itself remains fail-closed.
                allow_ha_remote_start=(
                    allow_ha_remote_start
                    if type(allow_ha_remote_start) is bool
                    else False
                ),
                valid=False,
            )
        return cls(
            restricted=restricted,
            id_tags=frozenset(id_tags),
            allow_ha_remote_start=allow_ha_remote_start,
        )

    def status(self, id_tag: object) -> str:
        """Decide afresh for both Authorize and StartTransaction."""
        if not self.valid or not _valid_id_tag(id_tag):
            return "Invalid"
        if not self.restricted or id_tag in self.id_tags:
            return "Accepted"
        return "Invalid"

    def as_config(self) -> dict:
        return {
            "restricted": self.restricted,
            CONF_STORED_TAGS: sorted(self.id_tags),
            CONF_ALLOW_HA_REMOTE_START: self.allow_ha_remote_start,
        }

    def allows_ha_remote_start(self) -> bool:
        """HA authentication, not a card identifier, controls remote starts."""
        return self.valid and self.allow_ha_remote_start


def policy_from_input(
    existing: AuthorizationPolicy, user_input: Mapping
) -> AuthorizationPolicy:
    """Replace the editable list when supplied; an omitted field preserves it."""
    text = user_input.get(CONF_AUTHORIZED_TAGS)
    restricted = user_input.get(CONF_RESTRICT_AUTHORIZATION, False)
    allow_ha_remote_start = user_input.get(
        CONF_ALLOW_HA_REMOTE_START, existing.allow_ha_remote_start
    )
    if (
        (text is not None and not isinstance(text, str))
        or type(restricted) is not bool
        or type(allow_ha_remote_start) is not bool
    ):
        raise ValueError("invalid_authorization")
    tags = existing.id_tags
    if text is not None:
        entered_tags = [line.strip() for line in text.splitlines() if line.strip()]
        if len(entered_tags) > 100 or any(
            not _valid_id_tag(tag) for tag in entered_tags
        ):
            raise ValueError("invalid_authorization")
        tags = frozenset(entered_tags)
    return AuthorizationPolicy(
        restricted=restricted,
        id_tags=tags,
        allow_ha_remote_start=allow_ha_remote_start,
    )


class LocalAuthorization:
    """Live policy and bounded, identifier-free decision diagnostics."""

    def __init__(self, config: object = None):
        self.policy = AuthorizationPolicy.from_config(config)
        self.last_decision: dict | None = None
        self._pending_ha_remote_start: tuple[str, float] | None = None

    def begin_ha_remote_start(self, id_tag: object, *, ttl: float = 60.0) -> bool:
        """Create a short-lived, one-shot grant for a HA-initiated start."""
        if not self.policy.allows_ha_remote_start() or not _valid_id_tag(id_tag):
            self._pending_ha_remote_start = None
            return False
        self._pending_ha_remote_start = (_digest(id_tag), monotonic() + ttl)
        return True

    def cancel_ha_remote_start(self) -> None:
        """Discard a grant when the charger rejects or loses the request."""
        self._pending_ha_remote_start = None

    def _consume_ha_remote_start(self, id_tag: object) -> bool:
        grant = self._pending_ha_remote_start
        self._pending_ha_remote_start = None
        if (
            grant is None
            or not self.policy.allows_ha_remote_start()
            or not _valid_id_tag(id_tag)
        ):
            return False
        digest, expires_at = grant
        return monotonic() <= expires_at and _digest(id_tag) == digest

    def decide(
        self,
        id_tag: object,
        action: str,
        timestamp: str,
        *,
        card_policy_applies: bool = True,
    ) -> str:
        ha_remote_start = (
            action == "StartTransaction" and self._consume_ha_remote_start(id_tag)
        )
        charger_mode_grant = action == "StartTransaction" and not card_policy_applies
        status = (
            "Accepted"
            if ha_remote_start or charger_mode_grant
            else self.policy.status(id_tag)
        )
        source = (
            "home_assistant"
            if ha_remote_start
            else "charger_mode"
            if charger_mode_grant
            else "rfid_or_charger"
        )
        self.last_decision = {
            "action": action,
            "status": status,
            "timestamp": timestamp,
            "restricted": self.policy.restricted,
            "configuration_valid": self.policy.valid,
            "source": source,
        }
        return status

    def diagnostics(self) -> dict:
        return {
            "restricted": self.policy.restricted,
            "configuration_valid": self.policy.valid,
            "allowed_tag_count": len(self.policy.id_tags),
            "ha_remote_start_allowed": self.policy.allows_ha_remote_start(),
            "ha_remote_start_pending": self._pending_ha_remote_start is not None,
            "last_decision": dict(self.last_decision) if self.last_decision else None,
        }
