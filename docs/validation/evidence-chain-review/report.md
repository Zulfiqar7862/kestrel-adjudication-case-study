# Evidence-chain re-seal review

These specific defects were addressed; overall safety and production readiness remain unvalidated.

## Scope and root cause (code inspection)

Baseline `0bb233710ce1b905c50d1687237bfd4efa2e8b83`, branch
`fix/correctness-review`; source imports from `/workspace/kprod/src/kestrel/__init__.py`.
The old verifier checked a file's self-declared hash and other files' predecessor
claims, but did not bind them to SQLite hashes/links or inventory unindexed files.
`get()` did no integrity check; basis/replay used it. Signing already rejected a
direct file/index hash mismatch, but could sign a clean-looking child of a damaged
ancestor. No clinical rule, input data, recommendation or notification policy was changed.

## Failing tests first, then implementation (executed)

The initial 25 cases were run before **any production-code edit**: **25 failed**
in 16.48s ([full failing output](red.txt)). The middle-record attack also relinks its
successor, so the old file-only chain reports OK rather than merely detecting an
unrepaired next link. After that first implementation, two additional field-presence
tests failed before their fix: **2 failed, 25 deselected** ([output](metadata-red.txt)).
Missing `prev_hash` on a first record must not silently equal explicit null.
All **27 passed in 16.76s** ([named passing output](green.txt)).

The table quotes each observed failure (long first lines shortened here only);
full traceback text is retained. PASSED is observed from the subsequent named run.
Some baseline cases already detected a generic chain break, or rejected direct
signing, but failed the specific diagnostic/shared-verifier requirement. They are
not falsely described as newly discovered acceptance bypasses.

| Test in `tests/test_evidence_integrity.py` | Observed failing output | After |
|---|---|---|
| `test_chain_reconciles_both_stores[resealed_tail-INDEX_HASH_MISMATCH]` | `AssertionError: {'tenant_code': 'T-A', 'length': 3, 'ok': True, 'errors': []}` | PASSED |
| `test_chain_reconciles_both_stores[resealed_middle-INDEX_HASH_MISMATCH]` | `AssertionError: {'tenant_code': 'T-A', 'length': 3, 'ok': True, 'errors': []}` | PASSED |
| `test_chain_reconciles_both_stores[deleted_tail-MISSING_FILE]` | `FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pytest-of-box/pytest-98/test_chain_reconciles_both_sto2/evidence/T-A/EVB-8500909e4e72e1b9.json'` | PASSED |
| `test_chain_reconciles_both_stores[swapped_files-INDEX_METADATA_MISMATCH:bundle_id]` | `AssertionError: {'tenant_code': 'T-A', 'length': 3, 'ok': False, 'errors': ['EVB-b5c4b63334a2fd7d: chain break at index 0: prev_hash=d...b4: chain break at index 2: prev_hash=None expected=d28fa79323bb8c64db3e0b698604083c17b9d5a8528a7d0aa15` | PASSED |
| `test_chain_reconciles_both_stores[index_hash-INDEX_HASH_MISMATCH]` | `AssertionError: {'tenant_code': 'T-A', 'length': 3, 'ok': True, 'errors': []}` | PASSED |
| `test_chain_reconciles_both_stores[index_predecessor-INDEX_PREDECESSOR_MISMATCH]` | `AssertionError: {'tenant_code': 'T-A', 'length': 3, 'ok': True, 'errors': []}` | PASSED |
| `test_chain_reconciles_both_stores[file_predecessor-FILE_PREDECESSOR_MISMATCH]` | `AssertionError: {'tenant_code': 'T-A', 'length': 3, 'ok': False, 'errors': ['EVB-0cc2e87682a7ea32: chain break at index 2: prev_hash=0...000000000000000000000000000000000000000000 expected=104b44a9d39207c4d332f42da9692b6cdaa9d2a0a5ffc4ecb1f` | PASSED |
| `test_chain_reconciles_both_stores[index_without_file-MISSING_FILE]` | `FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pytest-of-box/pytest-98/test_chain_reconciles_both_sto7/evidence/T-A/EVB-f7d54c406d0fb65c.json'` | PASSED |
| `test_chain_reconciles_both_stores[file_without_index-UNINDEXED_FILE]` | `AssertionError: {'tenant_code': 'T-A', 'length': 2, 'ok': True, 'errors': []}` | PASSED |
| `test_chain_reconciles_both_stores[cross_tenant_path-PATH_MISMATCH]` | `AssertionError: {'tenant_code': 'T-A', 'length': 3, 'ok': True, 'errors': []}` | PASSED |
| `test_chain_reconciles_both_stores[cross_tenant_document-INDEX_METADATA_MISMATCH:tenant_code]` | `AssertionError: {'tenant_code': 'T-A', 'length': 3, 'ok': True, 'errors': []}` | PASSED |
| `test_chain_reconciles_both_stores[malformed_json-UNREADABLE_FILE]` | `json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)` | PASSED |
| `test_resealed_ancestor_blocks_consumers[get]` | `Failed: DID NOT RAISE ValueError` | PASSED |
| `test_resealed_ancestor_blocks_consumers[basis]` | `Failed: DID NOT RAISE ValueError` | PASSED |
| `test_resealed_ancestor_blocks_consumers[replay]` | `Failed: DID NOT RAISE ValueError` | PASSED |
| `test_resealed_ancestor_blocks_consumers[sign]` | `Failed: DID NOT RAISE StaleEvidenceError` | PASSED |
| `test_cli_verify_fails_closed` | `assert 0 == 1` | PASSED |
| `test_api_verify_reports_missing_file` | `assert 404 == 200` | PASSED |
| `test_api_rejects_resealed_evidence[get]` | `assert 200 == 409` | PASSED |
| `test_api_rejects_resealed_evidence[basis]` | `assert 200 == 409` | PASSED |
| `test_api_rejects_resealed_evidence[replay]` | `assert 200 == 409` | PASSED |
| `test_api_rejects_resealed_evidence[sign]` | `assert 'INDEX_HASH_MISMATCH' in '{"detail":"evidence changed since it was viewed; reload before signing"}'` | PASSED |
| `test_unindexed_file_in_other_tenant_is_rejected` | `AssertionError: {'tenant_code': 'T-B', 'length': 0, 'ok': True, 'errors': []}` | PASSED |
| `test_orphan_files_with_empty_index_fail_closed` | `AssertionError: {'tenant_code': 'T-A', 'length': 0, 'ok': True, 'errors': []}` | PASSED |
| `test_sign_resealed_bundle_uses_shared_verification` | `AssertionError: Regex pattern did not match.` | PASSED |
| `test_explicit_null_metadata_cannot_be_omitted[prev_hash]` | `AssertionError: {'tenant_code': 'T-A', 'length': 3, 'ok': True, 'errors': []}` | PASSED |
| `test_explicit_null_metadata_cannot_be_omitted[case_id]` | `AssertionError: {'tenant_code': 'T-A', 'length': 3, 'ok': False, 'errors': ['EVB-af3456f5243e2597: INDEX_HASH_MISMATCH']}` | PASSED |

## Focused fix

- `storage/evidence.py::_inspect_chain`: shared reconciliation of recomputed core
  hash/self-hash, indexed hash, required fields, indexed identifiers/metadata,
  schema/content address, expected tenant/bundle path, file/index predecessor and
  preceding **indexed** hash. Missing, malformed and misplaced files produce
  specific failure codes. Inventory tenant JSON files to reject unindexed files,
  including when the tenant's index is empty. Errors never silently shorten a chain.
- `verify_chain()` returns the reconciliation report; `get()` raises
  `EvidenceIntegrityError` if the whole tenant fails and returns the already-parsed
  inspected document on success. Basis, replay and signing therefore share the
  same verification; a different read of the file is not returned after checking.
- `lifecycle.py::sign` preserves the underlying integrity reason in its existing
  stale-evidence refusal. No new clinical signing authority is inferred.
- `api/app.py`: shared integrity errors return HTTP 409 with reason/report;
  `/evidence/verify` remains a diagnostic HTTP 200 with `ok: false` on integrity
  failure. A missing indexed file no longer becomes an unhelpful verify-route 404.
- `cli.py::_cmd_verify`: prints the same report and returns exit 1 on failure,
  0 on an untouched valid chain.

## Executed end-to-end results

Exact substantive commands and results: [commands.txt](commands.txt).

- Full suite: **235 passed, 1 warning in 45.61s** ([output](pytest.txt)). The warning
  is the existing Starlette/httpx deprecation. No test assertion was weakened.
- An initial full run exposed **2 failed / 231 passed** because the old shared
  `TestEvidenceChain` fixture left a tampered file behind ([output](full-initial.txt)).
  Its tamper test now registers cleanup restoring the original bytes. All original
  assertions remain; later tests no longer inherit deliberate corruption.
- Fresh temp run-all: **420 rows**, **0 AUTO_CLOSE / 290 QA / 130 unverified historical
  candidates**, verified closures **0**, note/quarantine/destroy **0/0/0**.
  Notifications **28 PENDING / 392 UNKNOWN**. **No count or recommendation changes**.
  These are sample observations, not production accuracy or clinical ground truth.
- **420/420 identical full-result replays; all 8 untouched tenant chains pass**
  ([verification](verification.json), [run-all](run-all.json)). Direct CLI verify
  exits 0 ([output](cli-verify.json)); direct CLI EXC-107133 replay is identical
  ([output](cli-replay.json)).
- The earlier isolated re-seal probe now reports `ok: false`, `INDEX_HASH_MISMATCH`
  while the indexed hash remains unchanged ([probe](integrity-probe.json)).
- An independent temporary one-case CLI/API probe rejects the re-seal: actual CLI
  exit **1** ([report](cli-damaged-verify.json)); API verify returns **200 / ok:false**;
  basis, replay and sign each return **409 / INDEX_HASH_MISMATCH**; case remains
  `AWAITING_REVIEWER` ([responses](surface-probe.json)). The primary run was untouched.
- Ruff lint/format and local link/image checks are retained alongside this report.
  Engine decision rules, source data and notification policy are unchanged.

## Remaining limitations (inspection/design, not newly executed guarantees)

**A local SQLite index plus files is not an independent anchor. Someone who can
consistently rewrite both can still forge a history.** Matching deletion of files
and rows, including the entire chain, cannot be detected without an externally
anchored head/count. No signed checkpoint, timestamp authority, WORM archive,
external backup or authenticated signer identity was added.

Reconciliation is not an atomic filesystem/SQLite snapshot; concurrent mutation,
publication/crash recovery and hostile privileged administrators remain outside
this fix. Reads scan the whole tenant and conservatively block on unrelated
integrity errors; large-scale performance is unvalidated. File presence is
inventoried for tenant JSON evidence, not arbitrary filesystem artifacts. Existing
clinical authority, identity, tenant authentication and provenance gaps remain in
[04](../../04-system-design.md) and [07](../../07-limitations-and-roadmap.md).
These limitations come from inspected design, not a claim that a joint-store
forgery attack was prevented by the executed tests.

No merge, PR or force-push. Final commit SHA and watched CI result are reported
separately after the normal branch push. Existing historical reports remain
versioned records of earlier behaviour, not current guarantees.
