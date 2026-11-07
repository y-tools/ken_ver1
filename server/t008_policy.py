"""T008 fail-closed acquisition/publication and non-merging identity decisions.

No network, database writes or external dependencies: unit-testable policy layer.
"""
from dataclasses import dataclass
from typing import Literal

FIELDS = frozenset({"title", "artist", "release_year", "hiragana", "katakana", "romaji", "official_english"})
ENTITY_TYPES = frozenset({"work", "recording", "release"})

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

def acquisition_allowed(policy: SourcePolicy, method: str) -> bool:
    return bool(policy.reviewed and policy.method == method
                and policy.content_license and policy.access_terms
                and policy.automated_access_allowed is True
                and policy.storage_allowed is True)

def publication_allowed(policy: SourcePolicy, method: str, fields: set[str],
                        evidence_fields: set[str], verified: bool) -> bool:
    return bool(acquisition_allowed(policy, method)
                and policy.publication_allowed is True
                and verified and fields <= FIELDS
                and fields <= policy.allowed_fields
                and fields <= evidence_fields)

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
    if existing is None:
        return "candidate"
    if incoming.manual_conflict or existing.manual_conflict:
        return "review"
    if incoming.existing_matches != 1 or existing.existing_matches != 1:
        return "review"
    if incoming.entity_type not in ENTITY_TYPES or existing.entity_type not in ENTITY_TYPES:
        return "review"
    if not all((incoming.external_source, incoming.external_id,
                existing.external_source, existing.external_id)):
        return "review"
    if incoming.entity_type != existing.entity_type:
        return "review"
    if (incoming.external_source, incoming.external_id) == (existing.external_source, existing.external_id):
        # Only linking a recording identifier. NEVER merge song rows here.
        return "link_recording" if incoming.entity_type == "recording" else "review"
    if incoming.entity_type == "recording":
        return "distinct_recording"
    return "review"
