"""T008: fail-closed acquisition/publication gates and conservative identity matching.

A match NEVER authorizes merging or deleting existing Denmok song IDs.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

FIELDS = frozenset({
    "title", "artist", "release_year", "hiragana", "katakana",
    "romaji", "official_english"
})
ENTITY_TYPES = frozenset({"work", "recording", "release", "unknown"})
_UNDECIDED = frozenset({
    "", "unknown", "undefined", "none", "null", "pending", "unreviewed",
    "tbd", "n/a", "na", "not checked", "not reviewed", "unspecified",
    "不明", "未確認", "未審査", "未定"
})


def _meaningful(value: str | None) -> bool:
    return isinstance(value, str) and value.strip().casefold() not in _UNDECIDED


@dataclass(frozen=True)
class SourcePolicy:
    source_code: str
    method: str
    content_license: str | None
    access_terms: str | None
    allowed_fields: frozenset[str]
    automated_access_allowed: bool | None = None
    storage_allowed: bool | None = None
    publication_allowed: bool | None = None
    reviewed: bool = False
    reviewed_at: datetime | None = None
    expires_at: datetime | None = None


def _valid_dates(policy: SourcePolicy, now: datetime) -> bool:
    return (
        isinstance(policy.reviewed_at, datetime)
        and isinstance(policy.expires_at, datetime)
        and policy.reviewed_at.tzinfo is not None
        and policy.expires_at.tzinfo is not None
        and policy.reviewed_at <= now < policy.expires_at
    )


def acquisition_allowed(policy: SourcePolicy, method: str,
                        fields: set[str] | None = None,
                        now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if not (
        policy.reviewed is True
        and _meaningful(policy.source_code)
        and _meaningful(policy.method)
        and _meaningful(method)
        and policy.method == method
        and _meaningful(policy.content_license)
        and _meaningful(policy.access_terms)
        and _valid_dates(policy, now)
        and policy.automated_access_allowed is True
        and policy.storage_allowed is True
        and isinstance(policy.allowed_fields, (set, frozenset))
        and bool(policy.allowed_fields)
        and policy.allowed_fields <= FIELDS
    ):
        return False
    return fields is None or (bool(fields) and fields <= policy.allowed_fields
                              and fields <= FIELDS)


def publication_allowed(policy: SourcePolicy, method: str,
                        fields: set[str], evidence_fields: set[str],
                        verified: bool, now: datetime | None = None) -> bool:
    return (
        bool(fields)
        and verified is True
        and policy.publication_allowed is True
        and acquisition_allowed(policy, method, fields, now)
        and fields <= evidence_fields
    )


@dataclass(frozen=True)
class Identity:
    title_key: str
    artist_key: str
    entity_type: str | None = None
    external_source: str | None = None
    external_id: str | None = None
    existing_matches: int = 0
    manual_conflict: bool = False


Decision = Literal["link_recording", "review", "distinct_recording", "candidate"]


def decide_identity(incoming: Identity, existing: Identity | None) -> Decision:
    if incoming.manual_conflict or (existing and existing.manual_conflict):
        return "review"
    if incoming.existing_matches > 1 or not incoming.title_key or not incoming.artist_key:
        return "review"
    if existing is None:
        return "candidate" if incoming.existing_matches == 0 else "review"
    if existing.existing_matches != 1 or incoming.existing_matches != 1:
        return "review"
    if incoming.entity_type not in ENTITY_TYPES or existing.entity_type not in ENTITY_TYPES:
        return "review"
    if not all((incoming.external_source, incoming.external_id,
                existing.external_source, existing.external_id)):
        return "review"
    if incoming.entity_type != existing.entity_type:
        return "review"
    # External IDs have meaning only in the source's namespace.
    if incoming.external_source != existing.external_source:
        return "review"
    # Matching IDs with differing metadata may indicate source correction or collision.
    if (incoming.title_key, incoming.artist_key) != (existing.title_key, existing.artist_key):
        return "review"
    if incoming.external_id == existing.external_id:
        return "link_recording" if incoming.entity_type == "recording" else "review"
    if incoming.entity_type == "recording":
        return "distinct_recording"
    return "review"
