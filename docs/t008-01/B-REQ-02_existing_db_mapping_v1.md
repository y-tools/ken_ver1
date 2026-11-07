# T008-01 B-REQ-02: 既存DB対応表 v1
Code inspected: server/sql/001_init.sql (main), 004_t008_staging.sql (Draft PR #3).
Status: design only; no SQL executed.
| Logical object | Current DB | Relation / limitation | Non-breaking action |
| --- | --- | --- | --- |
| Public search/display song | songs(id,title,title_key,primary_artist_id,release_year,release_precision,release_source_id) | UNIQUE(title_key,primary_artist_id); one row may represent multiple recordings; release_year meaning not guaranteed | Preserve id and API response; attach metadata only in isolated review |
| Artist display | artists(id,name,name_key) | global name_key uniqueness may conflate stage-name collisions | keep IDs and collisions in review, do not auto-merge |
| Recording | recordings(id,song_id,musicbrainz_recording_id,isrc,recording_type,version_label) | recording associated with song; no independent full Work/Release graph | review links by provenance and specific recording evidence |
| Title aliases | song_names(song_id,kind,value,verification,derived_from_id,source_id) | support individual title readings; derived values provenance | validate title separately, never assume artist reading |
| Artist aliases | artist_names(artist_id,kind,value,verification,derived_from_id,source_id) | support individual artist readings | validate artist separately |
| Date evidence | release_evidence(song_id,source_id,release_year,precision,reference_url) | evidence attached to song, not a unique Release entity; lacks year_semantics | add typed review metadata outside legacy tables first |
| Source identifiers | source_song_links(song_id,source_id,external_id) | PK(source_id,external_id), not reliable cross-source recording match | keep source namespace + entity type; conflicts in review |
| Source terms | source_catalogs(code,license_id,license_url,...) | declared source metadata not equivalent to permission for each field/use | bind evidence to reviewed policy versions |
| Intake staging | t008_candidates(id,batch_id,title,artist,external_entity_type,external_id,verification) | preview/test, not public song row | append-only intake + review; no legacy mutation |
| Per-field evidence | t008_evidence(candidate_id,field_name,source_code,method,hash,verification,original_evidence_id) | field provenance in staging, not public API | attach field-specific proof and approval |
| Relationship proposal | t008_recording_works(recording_external_id,work_external_id,source_code,relation_type) | may suggest work/recording relation; not proof of real-world equivalence | require independent evidence review |
| Approval and preview | t008_* review, policy, publication tables from PR #3 | isolated, nonproduction only | preserve Draft HOLD; don't connect to public API |
## Mapping invariant
1. No change to existing songs.id, artist.id, recordings.song_id, or current search endpoint during initial fixture work.
2. A pair (title_key,primary_artist_id) describes current Denmok grouping; it is NOT a canonical Work/Recording key.
3. Every proposed link has provenance, target entity type, and review status. Unresolved means no link and no legacy changes.
4. Historical songs.release_year remains unchanged and semantically unknown until reviewed; retain separate proposed semantics.
5. Explicit Release entity is FUTURE OPTION, not assumed from release_evidence.
## Exit
Review of this document can be completed without redesigning the production DB or granting VPS access. Any later schema alteration requires G3-G5.
