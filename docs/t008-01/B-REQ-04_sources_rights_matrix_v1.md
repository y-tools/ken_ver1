# T008-01 B-REQ-04: source/method/field permissions decision matrix v1
Status: initial triage; NOT a real-source usage authorization. Permission unknown => deny collection/storage/publication until documented.
## Matrix (each proposed method and field family needs independent evidence)
| Source / method | Possible research role | Automated acquisition | Persistent storage | Public re-display | Decision |
|---|---|---|---|---|---|
| DAM public song search / automated scrape | reference for existence and catalog coverage | not verified | not verified | not verified | HOLD; no scrape/ingest |
| JOYSOUND public song search / automated scrape | reference for existence and catalog coverage | not verified | not verified | not verified | HOLD; no scrape/ingest |
| DAM/JOYSOUND official contract/API or directly permitted data exchange | potential governed provider | only within signed method scope | per field permission required | per field permission required | HOLD until authorization artifacts |
| MusicBrainz published core data / official API or downloadable dump | candidate for metadata research under its current data release / API conditions | confirm data category, current terms and rate limits | confirm category and obligations | confirm category and obligations | CONDITIONAL; not approved without evidence mapping |
| Artist/label official site / manual review | confirm specific titles and official English/date claims | manual reading does not imply bulk extraction authorization | case-by-case | case-by-case | HOLD per item until documented basis |
| User-owned or directly licensed catalog / approved import | highest-control pilot | explicit agreement | explicit agreement | explicit agreement | ELIGIBLE when documented and reviewed |
| Entirely fictional data / local generator | technical fixture only | yes, by project owner | yes, isolated test environment | no real-life catalogue claim | APPROVED for synthetic G1 |
## Required per-source decision record
source_code, source URL/contract ID, who checked and when, terms version/expiration, acquisition_method [manual,official_api,dump,permissioned_import], rights acquisition_allowed/storage_allowed/publication_allowed, allowed_fields exact list, attribution/retention obligations, rate-limit details, geographic and usage scope, evidence snapshot/hash, independent reviewer, decision [allow,deny,pending].
A source may be allowed for one field (e.g. title) but denied for another (e.g. official translated title), or allowed privately but disallowed publicly; deny-by-default for absent, conflicting or expired evidence.
## Graduation
- G1 synthetic cases may proceed immediately without any real supplier rights.
- G2 real metadata acquisition must have a usable rights record for each source/method/field and separate storage/publication decisions.
- Any public search requires a live, revocable policy gate and G3-G5. Provider presence in a list does not constitute permission.
- This matrix documents unknown statuses, not confirmation of DAM/JOYSOUND prohibitions or MusicBrainz blanket rights.
