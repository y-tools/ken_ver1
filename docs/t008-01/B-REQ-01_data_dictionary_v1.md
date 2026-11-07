# T008-01 B-REQ-01: 楽曲データ辞書 v1
Status: proposal for B review; no production migration. 2026-11-07.
## Identity and display
- Public identity: immutable existing songs.id. This is a display/search record for provisional title_key + primary_artist_id, NOT a definitive Work identifier.
- Artist: artists.id; record credit/version uncertainty separately. songs primary_artist constraint alone cannot prove a recording identity.
- Work: conceptual musical composition; Recording: particular performed/fixed audio; Release: specific publication/product. Maintain independent optional association proposals in review/staging, never infer one-to-one.
- Never auto-merge, delete or reassign existing songs.id from same title/artist, external ID collisions or matching strings. Disputed joins remain in review.
- Proposed auxiliary mapping (not yet deployed): mapping_id, songs_id nullable, recording_id nullable, entity_type [work,recording,release,unknown], source_namespace, source_entity_id, link_status [proposed,verified,rejected], evidence_ids, reviewed_by, reviewed_at. Keys in namespaces, not global.
## Required source-backed fields
- title, primary_artist: Unicode original display strings; do not overwrite from unreviewed source.
- song title and artist name aliases are separately supported by song_names / artist_names. Each may have hiragana / katakana / romaji / english / alternate. Store original, source, evidence, review state.
- hiragana: only confirmed reading or explicitly unverified; NEVER guess reading of English strings, symbols, kanji or proper names.
- katakana: confirmed directly or generated from verified hiragana with verification=derived_from_confirmed; retain original reference and transform version.
- romaji: derived from verified Japanese reading using versioned transliteration rule (adopt Hepburn with documented long vowels/punctuation convention) or independently source-confirmed; store provenance. Search-normalized aliases separate from official spelling.
- english: explicitly OFFICIAL English title or artist spelling; require credible evidence and source_confirmed/human_confirmed; no machine translations, no romanization passed as English.
- All aliases require distinct target entity and verification; never copy song reading to artist reading.
## Release date meaning
- Internally collect value + year_semantics enum [work_first_published,recording_first_released,specific_release_date,unknown] + precision [unknown,year,month,day] + evidence and target identity.
- Existing songs.release_year has UNKNOWN semantics until independently established; never mass reinterpret it as recording debut.
- Cover/new recording/live recording and original track each require distinct date semantics. Release evidence is proof, not a Release entity.
- Unknown value is NULL with reason [not_checked,no_reliable_source,conflict,not_applicable]; never write placeholder year. Distinguish unknown from known-unpublished or deliberately omitted.
## Evidentiary requirements
- For each verified field: field target, precise value, origin source namespace/record/url or immutable reference, acquisition method, rights-policy version, capture/checked timestamps, reviewer/transform, verification, original evidence hash as available, and provenance lineage.
- Existing name verification flags: estimated,source_confirmed,human_confirmed,derived_from_confirmed. estimated is nonpublic candidate hint, never verified output.
- Ambiguous conflict: record both claims, no silent overwrite. Source-approved acquisition does not imply publication authorization.
## Acceptance
All 30 fixture cases preserve public song IDs; no erroneous merges; alias-language fields and date semantics independently validated; unknown never guessed. This is a vocabulary/specification, not a DB schema change or claim that current schema has all proposed columns.

## B-026-01: legacy vs new-candidate estimated readings
- Existing GET /api/v1/search (server/api/main.py) returns estimated names in the existing "verified_or_estimated" shape and adds *Verification fields; this behavior MUST remain unchanged for G1/G3 compatibility.
- New T008 staged candidates MUST NOT graduate an estimated title/artist reading into verified publication or present it as source-confirmed. Unknown new aliases remain NULL / absent.
- Any future unified API/read layer needs explicit G3/G5 approval, field-wise provenance, client compatibility and public rights review; this document does not authorize a breaking change to legacy output.
