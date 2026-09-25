"""Identity Foundation.

Deterministic, content-addressed identity for business objects plus a small
registry supporting direct resolution, aliases, and conflict detection.

A canonical identity is derived from the object type and its keyedBy identifiers,
independent of any particular system's encoding. Aliases let an external/system-
specific identifier resolve to an existing identity; mapping the same identifier
to two different identities is a hard conflict, never a silent merge.

Cross-system probabilistic matching/merge is intentionally absent (single source).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


class IdentityError(ValueError):
    """Invalid identity input (unknown type or empty identifiers)."""


class IdentityConflict(Exception):
    """An identifier is already bound to a different canonical identity."""


def canonical_identity(object_type: str, identifiers: dict[str, str]) -> str:
    """Content-addressed stable identity for a business object.

    Order-independent: identifiers are canonicalized by sorted keys.
    """
    if not object_type:
        raise IdentityError("object_type is required")
    clean = {
        str(key): str(value)
        for key, value in identifiers.items()
        if value not in (None, "")
    }
    if not clean:
        raise IdentityError("at least one keyedBy identifier is required")

    canonical = hashlib.sha256()
    canonical.update(object_type.encode("utf-8"))
    for key in sorted(clean):
        canonical.update(b"\x00")
        canonical.update(key.encode("utf-8"))
        canonical.update(b"=")
        canonical.update(clean[key].encode("utf-8"))
    return f"id:{canonical.hexdigest()}"


@dataclass(frozen=True)
class Resolution:
    identity: str
    kind: str  # direct | alias | new


class IdentityRegistry:
    """Maps known identifier sets and aliases to canonical identities."""

    def __init__(self) -> None:
        # frozenset of "key=value" pairs -> identity
        self._by_keys: dict[frozenset[str], str] = {}
        self._aliases: dict[str, str] = {}

    @staticmethod
    def _key_set(object_type: str, identifiers: dict[str, str]) -> frozenset[str]:
        return frozenset(
            [f"type={object_type}"]
            + [f"{k}={v}" for k, v in sorted(identifiers.items()) if v != ""]
        )

    def resolve(
        self, object_type: str, identifiers: dict[str, str]
    ) -> Resolution:
        key_set = self._key_set(object_type, identifiers)

        if key_set in self._by_keys:
            return Resolution(self._by_keys[key_set], "direct")

        # Alias: supplied tokens map to a previously established identity.
        alias_hits = {
            self._aliases[token]
            for token in key_set
            if token in self._aliases
        }
        if alias_hits:
            if len(alias_hits) > 1:
                raise IdentityConflict(
                    "identifiers resolve to multiple identities"
                )
            identity = next(iter(alias_hits))
            self._by_keys[key_set] = identity
            return Resolution(identity, "alias")

        identity = canonical_identity(object_type, identifiers)
        self._by_keys[key_set] = identity
        return Resolution(identity, "new")

    def register_alias(
        self,
        identity: str,
        object_type: str,
        alias: dict[str, str],
    ) -> None:
        """Bind an external identifier set to an existing identity."""
        key_set = self._key_set(object_type, alias)
        existing = self._identity_for(key_set)
        if existing is not None and existing != identity:
            raise IdentityConflict(
                f"alias already bound to {existing}, cannot bind {identity}"
            )
        for token in key_set:
            bound = self._aliases.get(token)
            if bound is not None and bound != identity:
                raise IdentityConflict(
                    f"identifier {token!r} already aliased to {bound}"
                )
        for token in key_set:
            self._aliases[token] = identity
        self._by_keys[key_set] = identity

    def _identity_for(self, key_set: frozenset[str]) -> str | None:
        if key_set in self._by_keys:
            return self._by_keys[key_set]
        hits = {self._aliases[t] for t in key_set if t in self._aliases}
        if len(hits) > 1:
            raise IdentityConflict("identifier set resolves to multiple identities")
        return next(iter(hits), None)
