# crawl4ai Upgrade Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exact-pin `crawl4ai`, document the upgrade checklist, and add Dependabot + required unit CI + optional live workflow.

**Architecture:** Change the declared dependency to `crawl4ai==0.9.5`; add a small unit test that the pin is exact; ship GitHub Dependabot/CI/live workflow YAML; add `docs/upgrading-crawl4ai.md` and link it from README/operations.

**Tech Stack:** Python packaging (`pyproject.toml`), GitHub Actions, Dependabot, pytest, existing Compose stack for live.

**Spec:** `docs/superpowers/specs/2026-11-08-crawl4ai-upgrade-policy-design.md`

## Global Constraints

- Exact pin only: `crawl4ai==0.9.5` initially (no `>=`)
- Dependabot PRs target `dev`; weekly pip
- Required CI: `pytest -q` on PR/push to `dev` / `master` / `feat/**`
- Live workflow optional; skip unless `vars.LIVE_CDP_AVAILABLE == 'true'`; not a required check
- CloakBrowser upgrades out of scope for this bot

## Review Focus

- Accidental reintroduction of `crawl4ai>=` — Task 1 pin test
- Dependabot opening noise PRs for every transitive dep — Task 2 allow/ignore config
- Live workflow failing the repo when no CDP — Task 3 skip path must exit 0
- Docs omit compat surface APIs — Task 4 checklist includes listed APIs from spec
- CI uses wrong Python / misses editable install — Task 2 workflow uses 3.12 + `pip install -e '.[dev]'`

---

## File structure

| File | Responsibility |
| --- | --- |
| Modify `pyproject.toml` | Exact crawl4ai pin |
| Create `tests/test_dependency_pins.py` | Assert pin is `==` and equals expected version string |
| Create `.github/dependabot.yml` | Weekly crawl4ai-focused updates → `dev` |
| Create `.github/workflows/ci.yml` | Required unit CI |
| Create `.github/workflows/live.yml` | Optional Compose live verify |
| Create `docs/upgrading-crawl4ai.md` | Human upgrade checklist |
| Modify `docs/operations.md` | Compatibility table |
| Modify `README.md` | Link to upgrading doc |

---

### Task 1: Exact pin + pin test

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/test_dependency_pins.py`

**Interfaces:**
- Produces: dependency line exactly `crawl4ai==0.9.5`
- Test helper may parse `pyproject.toml` via `tomllib` (stdlib 3.11+)

- [ ] **Step 1: Write failing test**

```python
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_crawl4ai_is_exact_pin():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    crawl = [d for d in deps if d.replace(" ", "").startswith("crawl4ai")]
    assert len(crawl) == 1
    assert crawl[0].replace(" ", "") == "crawl4ai==0.9.5"
```

- [ ] **Step 2: Run — expect FAIL** (current `crawl4ai>=0.9.0`)

Run: `.venv/bin/python -m pytest tests/test_dependency_pins.py -q`

- [ ] **Step 3: Set** `crawl4ai==0.9.5` in `pyproject.toml`

- [ ] **Step 4: Run — expect PASS**; also `.venv/bin/python -m pytest -q`

- [ ] **Step 5: Commit** `build: exact-pin crawl4ai==0.9.5`

---

### Task 2: Dependabot + required CI

**Files:**
- Create: `.github/dependabot.yml`
- Create: `.github/workflows/ci.yml`

**Interfaces / contents:**
- Dependabot: `version: 2`, `package-ecosystem: pip`, `directory: /`, `schedule.interval: weekly`, `target-branch: dev`, and an `allow` (or `ignore` list) such that crawl4ai updates are in scope; document intent in a comment
- CI workflow name `ci`; jobs on `ubuntu-latest`; Python `3.12`; `pip install -e '.[dev]'`; `pytest -q`

- [ ] **Step 1: Add** `.github/dependabot.yml` and `.github/workflows/ci.yml` as above

- [ ] **Step 2: Validate YAML** parses

Run: `python3 -c "import yaml,pathlib; yaml.safe_load(pathlib.Path('.github/dependabot.yml').read_text()); yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text()); print('ok')"`  
(If PyYAML missing in host, use ` .venv/bin/python`.)

- [ ] **Step 3: Commit** `ci: add Dependabot and unit test workflow`

---

### Task 3: Optional live workflow

**Files:**
- Create: `.github/workflows/live.yml`

**Behavior:**
- `on: workflow_dispatch` (and optional `schedule` weekly cron if desired)
- Job `live`:
  - If `vars.LIVE_CDP_AVAILABLE != 'true'`: echo skip and exit 0
  - Else: `docker compose up -d --build`, wait for MCP, run `python3 scripts/integration_verify.py`

- [ ] **Step 1: Write** `live.yml` with the skip gate first in the job

- [ ] **Step 2: Validate YAML** parses (same as Task 2)

- [ ] **Step 3: Commit** `ci: add optional live CDP workflow`

---

### Task 4: Upgrade docs + links

**Files:**
- Create: `docs/upgrading-crawl4ai.md`
- Modify: `docs/operations.md`
- Modify: `README.md`

**Doc must include:**
- Exact-pin rule
- Steps 1–5 from the spec (changelog scan → unit → Compose smokes → hold path)
- Compat API bullet list from the spec
- Note that live CI is optional / `LIVE_CDP_AVAILABLE`

- [ ] **Step 1: Write** `docs/upgrading-crawl4ai.md`

- [ ] **Step 2: Add Compatibility table** to `docs/operations.md` (crawl4ai `0.9.5`, CloakBrowser `0.6.5`)

- [ ] **Step 3: Link** from README (Tests or ops section) to `docs/upgrading-crawl4ai.md`

- [ ] **Step 4: Commit** `docs: add crawl4ai upgrade checklist`

- [ ] **Step 5: Push** `git push -u origin HEAD` (branch `dev` or feature branch per executor)

---

## Spec coverage (self-review)

| Spec item | Task |
| --- | --- |
| Exact pin `==0.9.5` | 1 |
| Dependabot → `dev` | 2 |
| Required unit CI | 2 |
| Optional live + skip | 3 |
| upgrading + ops + README | 4 |
| Cloak out of bot scope | respected |
