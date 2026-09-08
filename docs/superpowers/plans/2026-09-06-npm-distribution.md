# Shambles npm Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish self-contained Shambles executables through a safe npm launcher with explicit updates and tested platform selection.

**Architecture:** A platform-neutral npm package exposes `shambles` through a small Node launcher. Platform-specific optional dependencies contain executables built by the existing release workflow. The launcher performs no downloads and reads no Shambles state; it selects the installed package, synchronously starts its binary, and returns the same exit status.

**Tech Stack:** Node.js 20+, npm 10+, CommonJS launcher, Python/PyInstaller, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-09-06-terminal-ui-design.md`

## Global Constraints

- Complete the application-service, Textual-TUI, and platform-store-hardening
  plans first.
- npm, Python, platform-package, and release versions must match exactly.
- The npm packages contain no `preinstall`, `install`, or `postinstall` scripts.
- The launcher never reads `~/.shambles`, `~/.claude`, or `~/.codex`.
- The **npm launcher** performs no version check; the Python app may check
  GitHub Releases only when `update.check` is enabled.
- Publish platform packages before publishing the launcher.
- Package names remain configurable until npm scope ownership is confirmed.
- Windows stays experimental until live Credential Manager validation succeeds.

---

### Task 1: Platform-neutral launcher

**Files:**
- Create: `npm/shambles/package.json`
- Create: `npm/shambles/bin/shambles.js`
- Create: `npm/shambles/lib/platform.js`
- Create: `npm/tests/platform.test.js`
- Create: `npm/package.json`
- Create: `npm/package-lock.json`

**Interfaces:**
- Consumes: Node `process.platform`, `process.arch`
- Produces: `platformPackage(platform, arch)` and executable launcher

- [ ] **Step 1: Write failing platform-selection tests**

```javascript
const test = require("node:test");
const assert = require("node:assert/strict");
const { platformPackage } = require("../shambles/lib/platform");

test("maps supported hosts", () => {
  assert.equal(platformPackage("linux", "x64"), "@shambles/linux-x64");
  assert.equal(platformPackage("linux", "arm64"), "@shambles/linux-arm64");
  assert.equal(platformPackage("darwin", "x64"), "@shambles/darwin-x64");
  assert.equal(platformPackage("darwin", "arm64"), "@shambles/darwin-arm64");
  assert.equal(platformPackage("win32", "x64"), "@shambles/windows-x64");
});

test("rejects unsupported hosts clearly", () => {
  assert.throws(
    () => platformPackage("freebsd", "x64"),
    /Unsupported Shambles platform: freebsd-x64/
  );
});
```

- [ ] **Step 2: Run and confirm the module is missing**

Run: `cd npm && npm test`
Expected: FAIL with `Cannot find module '../shambles/lib/platform'`.

- [ ] **Step 3: Implement exact platform mapping**

```javascript
const PACKAGES = new Map([
  ["linux-x64", "@shambles/linux-x64"],
  ["linux-arm64", "@shambles/linux-arm64"],
  ["darwin-x64", "@shambles/darwin-x64"],
  ["darwin-arm64", "@shambles/darwin-arm64"],
  ["win32-x64", "@shambles/windows-x64"],
]);

function platformPackage(platform, arch) {
  const key = `${platform}-${arch}`;
  const name = PACKAGES.get(key);
  if (!name) throw new Error(`Unsupported Shambles platform: ${key}`);
  return name;
}

module.exports = { platformPackage };
```

- [ ] **Step 4: Implement the launcher without lifecycle scripts**

```javascript
#!/usr/bin/env node
const { spawnSync } = require("node:child_process");
const path = require("node:path");
const { platformPackage } = require("../lib/platform");

const packageName = platformPackage(process.platform, process.arch);
let packageJson;
try {
  packageJson = require.resolve(`${packageName}/package.json`);
} catch {
  console.error(`Shambles executable package ${packageName} is missing.`);
  process.exit(1);
}
const executable = process.platform === "win32" ? "shambles.exe" : "shambles";
const binary = path.join(path.dirname(packageJson), "bin", executable);
const result = spawnSync(binary, process.argv.slice(2), { stdio: "inherit" });
if (result.error) {
  console.error(`Could not start Shambles: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status === null ? 1 : result.status);
```

Declare `bin.shambles`, Node `>=20`, and exact-version
`optionalDependencies` in `npm/shambles/package.json`. Do not add a scripts
key other than development tests at the workspace root.

Run `npm install --package-lock-only` in `npm/` to create the committed lock
file used by CI.

- [ ] **Step 5: Run launcher tests**

Run: `cd npm && npm test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add npm
git commit -m "feat: add npm platform launcher"
```

### Task 2: Platform package builder

**Files:**
- Create: `scripts/build-npm-package.py`
- Create: `npm/platform-template/package.json`
- Create: `tests/test_npm_packaging.py`

**Interfaces:**
- Consumes: platform id, architecture, executable path, project version
- Produces: `dist/npm/<package>/package.json` and `bin/shambles[.exe]`

- [ ] **Step 1: Write a failing package-generation test**

```python
def test_linux_package_contains_binary_and_constraints(tmp_path):
    binary = tmp_path / "shambles"
    binary.write_bytes(b"binary")
    out = build_platform_package(
        target="linux-x64", executable=binary, version="2.1.0",
        output=tmp_path / "out")
    metadata = json.loads((out / "package.json").read_text())
    assert metadata["name"] == "@shambles/linux-x64"
    assert metadata["version"] == "2.1.0"
    assert metadata["os"] == ["linux"]
    assert metadata["cpu"] == ["x64"]
    assert "scripts" not in metadata
    assert (out / "bin" / "shambles").read_bytes() == b"binary"
```

- [ ] **Step 2: Confirm the builder module is missing**

Run: `.venv/bin/python -m pytest tests/test_npm_packaging.py -v`
Expected: FAIL on missing builder import.

- [ ] **Step 3: Implement deterministic package generation**

```python
TARGETS = {
    "linux-x64": ("@shambles/linux-x64", "linux", "x64", "shambles"),
    "linux-arm64": ("@shambles/linux-arm64", "linux", "arm64", "shambles"),
    "darwin-x64": ("@shambles/darwin-x64", "darwin", "x64", "shambles"),
    "darwin-arm64": ("@shambles/darwin-arm64", "darwin", "arm64", "shambles"),
    "windows-x64": ("@shambles/windows-x64", "win32", "x64", "shambles.exe"),
}
```

Use `shutil.copyfile`, set executable mode `0o755` on POSIX payloads, and
serialize JSON with sorted keys and a trailing newline. Refuse an unknown
target, missing executable, or version that differs from `pyproject.toml`.

- [ ] **Step 4: Test all target metadata**

Run: `.venv/bin/python -m pytest tests/test_npm_packaging.py -v`
Expected: PASS for all five targets.

- [ ] **Step 5: Commit**

```bash
git add scripts/build-npm-package.py npm/platform-template tests/test_npm_packaging.py
git commit -m "build: generate npm platform packages"
```

### Task 3: Pack-and-install integration tests

**Files:**
- Create: `npm/tests/install.test.js`
- Create: `npm/tests/fixtures/fake-binary.js`
- Modify: `npm/package.json`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: packed launcher and generated host platform tarball
- Produces: isolated npm installation proof

- [ ] **Step 1: Write an integration test that packs local packages**

```javascript
test("global-style install forwards args and exit status", () => {
  const install = makeIsolatedInstall();
  installLocalPlatformFixture(install, process.platform, process.arch);
  installLauncher(install);
  const result = runInstalled(install, ["--version"]);
  assert.equal(result.status, 0);
  assert.match(result.stdout, /fake-shambles --version/);
});
```

The fixture executable prints its arguments and exits with the integer from
`SHAMBLES_FAKE_EXIT`. Add a second test setting that variable to `7` and
asserting the launcher exits `7`.

- [ ] **Step 2: Run and observe the missing harness failure**

Run: `cd npm && npm test`
Expected: FAIL on missing fixture or install helpers.

- [ ] **Step 3: Implement isolated installs**

Use `fs.mkdtempSync`, `npm pack --json`, and
`npm install --prefix <temp> <tarball>`. Pass the local platform package
tarball as an explicit dependency override so tests never contact the public
registry. Remove the temp directory in `afterEach`.

- [ ] **Step 4: Add Node CI**

```yaml
- uses: actions/setup-node@v4
  with:
    node-version: "20"
    cache: npm
    cache-dependency-path: npm/package-lock.json

- name: Test npm packages
  run: npm ci && npm test
  working-directory: npm
```

- [ ] **Step 5: Run integration and Python packaging tests**

Run: `cd npm && npm ci && npm test`
Expected: PASS without registry requests during the test command.

Run: `.venv/bin/python -m pytest tests/test_npm_packaging.py tests/test_packaging.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add npm .github/workflows/ci.yml
git commit -m "test: install npm launcher from packed artifacts"
```

### Task 4: Expand the binary build matrix

**Files:**
- Modify: `.github/workflows/release.yml`
- Create: `scripts/check-release-version.py`
- Modify: `tests/test_npm_packaging.py`

**Interfaces:**
- Consumes: Git tag, `pyproject.toml`, npm package metadata
- Produces: Linux x64/arm64, macOS x64/arm64, and experimental Windows x64
  artifacts plus npm package directories

- [ ] **Step 1: Write failing version-consistency tests**

```python
def test_all_release_versions_match():
    versions = release_versions(Path("."))
    assert set(versions.values()) == {shambles.__version__}

def test_tag_must_equal_package_version():
    assert validate_tag("v2.1.0", "2.1.0") is None
    with pytest.raises(ValueError, match="does not match"):
        validate_tag("v2.2.0", "2.1.0")
```

- [ ] **Step 2: Confirm the checker is missing**

Run: `.venv/bin/python -m pytest tests/test_npm_packaging.py -k version -v`
Expected: FAIL on missing release-version functions.

- [ ] **Step 3: Implement the version gate**

Read the Python version from `pyproject.toml`, launcher version from
`npm/shambles/package.json`, and exact optional dependency versions from the
launcher. Exit nonzero when any differ or the tag is not `v<version>`.

- [ ] **Step 4: Add release matrix entries**

Use GitHub-hosted x64 runners for Linux, Windows, and macOS x64. Use a native
arm64 macOS runner for Darwin arm64. Add Linux arm64 only on a native or
emulated runner that can execute the resulting binary; do not publish an
untested cross-compiled artifact.

Build console executables without `--windowed`, because the npm product is a
terminal app. Keep any GUI-specific Windows artifact as a separately named
release output.

- [ ] **Step 5: Add per-target smoke tests**

For every built binary run:

```text
shambles --version
shambles --help
shambles --home <synthetic-home> list --json
```

Run a headless TUI boot-and-quit smoke test using a pseudo-terminal on POSIX
and ConPTY on Windows. The job must fail if the process does not restore and
exit within 15 seconds.

- [ ] **Step 6: Validate workflow and tests**

Run: `.venv/bin/python -m pytest tests/test_npm_packaging.py tests/test_packaging.py -v && git diff --check`
Expected: PASS with no workflow whitespace errors.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/release.yml scripts/check-release-version.py tests/test_npm_packaging.py
git commit -m "build: produce npm release targets"
```

### Task 5: Publish ordering and release documentation

**Files:**
- Modify: `.github/workflows/release.yml`
- Modify: `README.md`
- Modify: `SECURITY.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: tested npm package directories and `NPM_TOKEN` or npm trusted
  publishing configuration
- Produces: platform packages, launcher package, checksums, and documented
  explicit update flow

- [ ] **Step 1: Add a workflow-structure test**

```python
def test_launcher_publish_depends_on_platform_publish():
    workflow = Path(".github/workflows/release.yml").read_text()
    launcher = workflow.split("  publish-npm-launcher:", 1)[1]
    launcher = launcher.split("\n  ", 1)[0]
    assert "needs: [publish-npm-platforms]" in launcher
```

- [ ] **Step 2: Confirm the publish jobs do not exist**

Run: `.venv/bin/python -m pytest tests/test_npm_packaging.py -k publish -v`
Expected: FAIL because `publish-npm-launcher` is absent.

- [ ] **Step 3: Implement ordered publication**

Create `publish-npm-platforms` after every build and smoke-test job. Publish
each package with provenance and the intended access setting. Create
`publish-npm-launcher` with:

```yaml
needs: [publish-npm-platforms]
if: startsWith(github.ref, 'refs/tags/v')
```

Run `npm pack --dry-run` immediately before each publish and reject any
unexpected file, lifecycle script, or mismatched version. Publish the launcher
last so `latest` never points at missing platform packages.

- [ ] **Step 4: Generate checksums and publish the GitHub release**

Generate SHA-256 checksums for every executable and npm tarball. Upload the
checksums and artifacts only after npm publication succeeds. Keep the
experimental Windows label in release notes until live validation is recorded.

- [ ] **Step 5: Document install, update, and privacy**

Document:

```bash
npm install --global shambles
npm install --global shambles@latest
```

State that Shambles performs no update checks and npm contacts the registry
only when invoked. Explain npm, pipx, and direct binaries as equal supported
routes, subject to the platform table.

- [ ] **Step 6: Run final release verification**

Run: `cd npm && npm ci && npm test && npm pack --dry-run`
Expected: tests pass and the tarball contains only the launcher, platform
mapping, README, license, and package metadata.

Run: `.venv/bin/python -m pytest && git diff --check`
Expected: all Python tests pass and no whitespace errors.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/release.yml README.md SECURITY.md CHANGELOG.md tests/test_npm_packaging.py
git commit -m "build: publish Shambles through npm"
```
