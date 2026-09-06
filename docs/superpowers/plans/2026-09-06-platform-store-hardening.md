# Shambles Platform Store Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing macOS Keychain and Windows Credential Manager adapters into honestly verified production paths before their binaries are advertised as supported.

**Architecture:** Pure store behavior remains injectable and cross-platform tested. An opt-in validation command runs only on a real host with explicit user consent, compares cryptographic hashes in memory, restores the original credential in a `finally` block, and prints no credential material. Platform status is generated from committed validation records rather than optimistic build success.

**Tech Stack:** Python 3.10+, existing Keychain/Credman stores, pytest, macOS `/usr/bin/security`, Windows Credential APIs

**Spec:** `docs/superpowers/specs/2026-09-06-terminal-ui-design.md`

## Global Constraints

- Complete the application-service plan first.
- Never print, persist, upload, or commit credential contents or hashes.
- Live validation is opt-in and refuses to run without a disposable second profile.
- Always restore the original live credential in a `finally` block.
- A CI build is not evidence of a successful live credential switch.
- Windows remains experimental until its target-name mapping is observed.
- macOS support requires live Keychain round-trip validation.

---

### Task 1: Strengthen store conformance tests

**Files:**
- Create: `tests/contract/test_secure_store_contract.py`
- Modify: `tests/test_state.py`

**Interfaces:**
- Consumes: `KeychainStore`, `CredmanStore`, injected fake backends
- Produces: shared secure-store contract tests

- [ ] **Step 1: Write parametrized failing contract cases**

```python
@pytest.mark.parametrize("store", [fake_keychain_store(), fake_credman_store()])
def test_secure_store_round_trip_is_byte_exact(store):
    payload = b'{"unicode":"\\u2603","newline":"x\\n"}\n'
    store.write(payload)
    assert store.read() == payload
    store.delete()
    assert store.read() is None

@pytest.mark.parametrize("store", [fake_keychain_store(), fake_credman_store()])
def test_interrupted_write_never_returns_truncated_bytes(store):
    store.write(b"old-complete")
    store.backend.fail_before_commit = True
    with pytest.raises(StoreUnavailableError):
        store.write(b"new-complete")
    assert store.read() in (b"old-complete", b"new-complete")
```

- [ ] **Step 2: Run and expose backend differences**

Run: `.venv/bin/python -m pytest tests/contract/test_secure_store_contract.py -v`
Expected: at least the interrupted-write assertion fails before both adapters
meet the contract.

- [ ] **Step 3: Make store commits explicit**

For Credential Manager, write numbered chunks first and the metadata count
last; remove obsolete excess chunks only after the new count is committed. For
Keychain, keep the single `security add-generic-password -U -X` operation and
classify nonzero status as `StoreUnavailableError`.

- [ ] **Step 4: Run store and provider contracts**

Run: `.venv/bin/python -m pytest tests/contract tests/test_state.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shambles/stores tests/contract/test_secure_store_contract.py tests/test_state.py
git commit -m "test: enforce secure store round trips"
```

### Task 2: Safe live-validation command

**Files:**
- Create: `shambles/app/validate_store.py`
- Create: `tests/test_validate_store.py`
- Modify: `shambles/app/cli.py`

**Interfaces:**
- Consumes: provider store and two existing profile names
- Produces: `validate-store <provider> <profile-a> <profile-b>` report with
  booleans only

- [ ] **Step 1: Write restoration and redaction tests**

```python
def test_validation_restores_live_bytes_after_failure(fake_store):
    original = b"original-secret"
    fake_store.write(original)
    fake_store.fail_on_write_number = 2
    with pytest.raises(ValidationFailed):
        validate_round_trip(fake_store, b"profile-a", b"profile-b")
    assert fake_store.read() == original

def test_report_contains_no_payload_or_hash():
    report = ValidationReport(read=True, write=True, restore=True)
    text = report.to_json()
    assert "secret" not in text
    assert set(json.loads(text)) == {"read", "write", "restore"}
```

- [ ] **Step 2: Confirm validator is missing**

Run: `.venv/bin/python -m pytest tests/test_validate_store.py -v`
Expected: FAIL on missing module.

- [ ] **Step 3: Implement in-memory comparison and unconditional restoration**

```python
def validate_round_trip(store, first: bytes, second: bytes) -> ValidationReport:
    original = store.read()
    if original is None:
        raise ValidationFailed("No live credential is available to restore.")
    try:
        store.write(first)
        first_ok = hmac.compare_digest(store.read() or b"", first)
        store.write(second)
        second_ok = hmac.compare_digest(store.read() or b"", second)
        return ValidationReport(True, first_ok and second_ok, False)
    finally:
        store.write(original)
```

Set `restore=True` only after a final read compares equal to `original`.
The command requires `--i-understand-this-writes-my-live-login`; without it,
exit with usage code before reading the store.

- [ ] **Step 4: Run failure-injection tests**

Run: `.venv/bin/python -m pytest tests/test_validate_store.py -v`
Expected: PASS for first-write, second-write, read, and restoration failures.

- [ ] **Step 5: Commit**

```bash
git add shambles/app/validate_store.py shambles/app/cli.py tests/test_validate_store.py
git commit -m "feat: add opt-in credential store validator"
```

### Task 3: Record real-host evidence

**Files:**
- Create: `docs/platform-validation.json`
- Create: `docs/platform-validation.schema.json`
- Create: `tests/test_platform_validation.py`

**Interfaces:**
- Consumes: redacted output from `validate-store`
- Produces: reviewable validation entries with no machine identity or secrets

- [ ] **Step 1: Write schema tests**

```python
def test_every_supported_platform_has_passing_live_evidence():
    records = load_validation_records()
    supported = {(r["provider"], r["platform"]) for r in records
                 if r["read"] and r["write"] and r["restore"]}
    assert advertised_supported_pairs() <= supported
```

- [ ] **Step 2: Confirm supported claims lack evidence**

Run: `.venv/bin/python -m pytest tests/test_platform_validation.py -v`
Expected: FAIL for any platform currently advertised without a record.

- [ ] **Step 3: Define the redacted record**

```json
{
  "provider": "claude",
  "platform": "macos-arm64",
  "vendor_version": "2.1.220",
  "shambles_commit": "full-commit-id",
  "observed_store": "keychain",
  "read": true,
  "write": true,
  "restore": true,
  "performed_at": "2026-09-06"
}
```

The schema rejects usernames, paths under a user home, emails, organization
identifiers, hashes, and arbitrary notes.

- [ ] **Step 4: Perform explicit real-machine validation**

On macOS, validate Claude against the computed Keychain service name and Codex
against its configured file store. On Windows, first record the actual
`TargetName` family produced by Claude Code without recording payloads, then
correct `TARGET_TEMPLATE` and validate the round trip. Repeat after switching
between two disposable profiles and confirm a newly started vendor CLI reports
the intended account.

- [ ] **Step 5: Run evidence and contract tests**

Run: `.venv/bin/python -m pytest tests/test_platform_validation.py tests/contract -v`
Expected: PASS only for platform/provider pairs whose evidence is committed.

- [ ] **Step 6: Commit**

```bash
git add docs/platform-validation.json docs/platform-validation.schema.json tests/test_platform_validation.py shambles/stores/credman.py
git commit -m "docs: record live credential store validation"
```

### Task 4: Gate product status on validation

**Files:**
- Modify: `shambles/app/snapshot.py`
- Modify: `README.md`
- Modify: `TECH_SPEC.md`
- Modify: `.github/workflows/release.yml`
- Modify: `tests/test_platform_validation.py`

**Interfaces:**
- Consumes: platform validation records
- Produces: accurate supported/experimental labels and release gates

- [ ] **Step 1: Write a failing release-status test**

```python
def test_release_cannot_promote_unvalidated_store():
    status = support_status("claude", "windows-x64", records=[])
    assert status == "experimental"
```

- [ ] **Step 2: Confirm status is not centrally derived**

Run: `.venv/bin/python -m pytest tests/test_platform_validation.py -v`
Expected: FAIL on missing `support_status`.

- [ ] **Step 3: Implement status derivation**

```python
def support_status(provider, platform, records):
    passed = any(
        r["provider"] == provider and r["platform"] == platform
        and r["read"] and r["write"] and r["restore"]
        for r in records)
    return "supported" if passed else "experimental"
```

Use this status in generated release notes and the snapshot capability message.
Do not disable fixture-tested experimental paths; label them accurately.

- [ ] **Step 4: Add the release gate**

Run the platform-validation tests before package publication. A missing record
may leave a package experimental, but the workflow must not describe it as
supported.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest && git diff --check`
Expected: all tests pass and documentation agrees with recorded evidence.

```bash
git add shambles/app/snapshot.py README.md TECH_SPEC.md .github/workflows/release.yml tests/test_platform_validation.py
git commit -m "build: gate platform support on live evidence"
```
