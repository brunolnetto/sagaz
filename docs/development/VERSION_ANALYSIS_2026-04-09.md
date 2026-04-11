# Versioning Analysis Report - April 9, 2026

**Issue**: Version jump from 1.1.2 → 1.5.0 with skipped intermediate versions (1.2, 1.3, 1.4)

**Status**: ⚠️ Critical - Requires immediate clarification

**Date**: 2026-04-09

---

## Executive Summary

You're absolutely right to question the version jumps. The project has **three overlapping versioning issues**:

1. **Git tag/pyproject.toml mismatch** - Tags claim features that pyproject.toml doesn't reflect
2. **Missing intermediate versions** - v1.2.0, v1.3.0, v1.4.0 mentioned in ROADMAP but never tagged
3. **Unclear version strategy** - Why does v1.5.0 exist? Why jump to v2.0.0? What's the SemVer policy?

---

## Problem 1: Git Tags Don't Match pyproject.toml

### Evidence

```bash
$ git show v1.1.2:pyproject.toml | grep version
version = "1.0.3"  ❌ MISMATCH!

$ git show v1.1.1:pyproject.toml | grep version
version = "1.0.3"  ❌ MISMATCH!

$ git show v1.1.0:pyproject.toml | grep version
version = "1.0.3"  ❌ MISMATCH!

$ head pyproject.toml
version = "1.1.2"  ✅ Current develop
```

### Impact
- Version claims are broken: Tags v1.1.0-1.1.2 all say "1.0.3" internally
- Downstream packages can't rely on version tags
- PyPI distribution is misleading
- CI/CD automation fails to detect current version

---

## Problem 2: The Missing v1.2-1.4 Versions

### Current Situation

```
Timeline:
├─ v1.0.0 (2024-12-23) - Core features released
├─ v1.0.3 (2024-12-26) - SagaConfig system
│
├─ Many features added but NO TAGS:
│  ├─ 2025-12-26: outbox module
│  ├─ 2026-01-07: integrations/
│  ├─ 2026-01-08: cli/ and visualization/
│  ├─ 2026-01-15: ...other features...
│  └─ 2026-02-24: v1.1.2 tag created (but points to old 1.0.3 version!)
│
└─ Next planned: v1.5.0 (Wave 0 - Governance & Ops)
   └─ SKIPS 1.2, 1.3, 1.4!
```

### What the ROADMAP Claims Were "Completed in Q1 2026"

But these versions never got git tags:

| Version | ADR | Features | In Code? | Tagged? |
|---------|-----|----------|----------|---------|
| v1.2.0 | ADR-016, ADR-022 | Unified Storage, Compensation Result Passing | ✅ Yes | ❌ No |
| v1.3.0 | ADR-023, ADR-019, ADR-027, ADR-028 | Pivot Steps, Dry-Run, CLI, Framework Integration | ✅ Yes | ❌ No |
| v1.4.0 | ADR-021, ADR-026 | Context Streaming, 24 Industry Examples | ✅ Yes | ❌ No |
| v2.1.0 | ADR-024 | Saga Replay & Time-Travel | ✅ Yes | ❌ No |

**The features definitely exist in `/sagaz/` subdirectories:**

```bash
✅ sagaz/storage/       (Unified Storage - belongs in v1.2.0)
✅ sagaz/cli/           (Project CLI - belongs in v1.3.0)
✅ sagaz/visualization/ (Visualization - belongs in v1.3.0 or v2.x)
✅ sagaz/integrations/  (Framework Integration - belongs in v1.3.0)
✅ sagaz/choreography/  (Choreography - added 2026-04-07, AFTER v1.1.2!)
✅ examples/            (Industry Examples - belongs in v1.4.0)
✅ sagaz/versioning/    (Saga Versioning - related to ADR-018)
```

---

## Problem 3: Confusing Version Semantics

### Current Milestone Plan

```
v1.5.0 (Wave 0)  ← 5 minor versions above 1.0!
  ├─ Dead Letter Queue (#60)
  └─ AlertManager Rules (#61)

v1.6.0 (Wave 1)
  ├─ SQLite Backend (#62)
  └─ Storage Migration (#63)

v2.0.0 (Wave 2)  ← MAJOR version jump! Why?
  ├─ Analytics (sqldim, Fluss+Iceberg)
  ├─ ChaosMonkey
  └─ Visualization UI

v2.1.0 (Wave 3)
  ├─ CLI v2.0
  ├─ CDC/Debezium
  └─ Multi-tenancy

v2.2.0 (Wave 4)
  └─ Choreography Pattern

v2.3.0 (Wave 5)  ← BLOCKED
  ├─ Event Sourcing
  └─ Region Affinity
```

### Issues with This Plan

1. **Minor version compression** - Why 1.5 and 1.6? Why not 1.2-1.4?
2. **Unclear major version bump** - What breaking changes make v1.6 → v2.0 necessary?
3. **Wave vs. Release confusion** - Are milestones waves or releases?
4. **Feature bloat** - v2.0.0 has 5+ disparate features (analytics, chaos, visualization)
5. **No SemVer policy** - When does something warrant a major bump?

According to Semantic Versioning (https://semver.org/):
> **MAJOR version** when you make incompatible API changes
> **MINOR version** when you add functionality in a backwards-compatible manner
> **PATCH version** when you make backwards-compatible bug fixes

---

## Root Cause: Aspirational vs. Actual Roadmap

### What Happened

1. **ROADMAP.md written aspirationally** - "We will ship v1.2.0, v1.3.0, v1.4.0"
2. **Features shipped ahead of schedule** - CLI, integrations added in Jan 2026
3. **Tagging never caught up** - No intermediate tags created
4. **Planning decoupled from tags** - Milestones created without updating tags
5. **Choreography (v2.2) partially implemented** - But v2.0 planned first!

### Timeline of Confusion

```
2024-12-23: v1.0.0 released                         (v1.0.0 tag + pyproject.toml)
2024-12-25: v1.0.1 released                         (v1.0.1 tag + pyproject.toml)
2024-12-26: v1.0.3 released                         (v1.0.3 tag + pyproject.toml)

2025-12-26: Outbox module added                     (no tag)
2026-01-07: Integrations module added               (no tag)
2026-01-08: CLI module added                        (no tag)
2026-01-08: Visualization module added              (no tag)

2026-02-24: v1.1.0, v1.1.1, v1.1.2 tags created    ← But pyproject.toml still "1.0.3"!

2026-04-07: Choreography module added               (after v1.1.2)
2026-04-08: ROADMAP written claiming v1.2-1.4 "completed"
2026-04-09: You notice "wait, we're jumping from 1.1.2 to 1.5.0?" 👈 HERE
```

---

## Decisions Needed

### Question 1: Should We Backfill v1.2-1.4?

**Option A (Recommended)**: YES, backfill for clarity
- Pros: Honest version history, matches what code does, clear progression
- Cons: Confusing for users who installed v1.1.2, seems like going backwards
- Action: Create retroactive tags dated to when features landed

**Option B**: NO, accept gap and move forward
- Pros: Simpler, no confusion about "which version should I use?"
- Cons: Gap is unexplained, messy history
- Action: Next release jumps to v1.5.0 as planned

### Question 2: What's the Versioning Strategy?

**Option A (SemVer strict)**: Minor bumps only for new features, Major only for breaking changes
```
v1.5.0: Wave 0 (governance)
v1.6.0: Wave 1 (storage)
v1.7.0: Wave 2 (analytics)     [NOT v2.0!]
v1.8.0: Wave 3 (CLI v2)        [NOT v2.1!]
v2.0.0: When we actually break API compatibility
```

**Option B (Wave-based)**: Each wave is a major feature push
```
v1.5.0: Waves 0-1 together
v2.0.0: Waves 2-3 together (choreography, analytics, multi-tenancy)
v3.0.0: Waves 4-5 (CLI v2, CDC, extensions)
```

**Option C (Calendar versioning)**: Align with quarterly releases
```
v2026.Q2.1: April-June 2026 releases  (replaces v1.5.0)
v2026.Q3.1: July-September 2026 releases (replaces v1.6-v2.0)
v2026.Q4.1: Oct-December 2026 releases
```

### Question 3: Prevent Future Drift?

**Option A (Recommended)**: Automate via GitHub Actions
- When milestone closes → create git tag → update pyproject.toml → create release notes

**Option B**: Document process and rely on manual compliance
- Create `docs/development/release-process.md`
- Enforce in code reviews
- Rely on release manager diligence

---

## What Should Happen Now

### Immediate Actions This Week

1. **Accept current state** - v1.1.2 exists with tag/version mismatches
2. **Create VERSIONING_POLICY.md** - Document when to bump MAJOR/MINOR/PATCH
3. **Assign target versions** to open PRs (#60, #61, #62, #69, #74, etc.)

### For Next Release (v1.5.0)

When #60 and #61 are merged:
```bash
# Update file: pyproject.toml
version = "1.5.0"

# Create git tag
git tag -a v1.5.0 -m "Release v1.5.0: Governance & Ops (DLQ, AlertManager, docs)"

# Create release notes summarizing changes
```

### For Planning

1. Decide: Backfill v1.2-1.4 or skip ahead?
2. Decide: Use SemVer strict, wave-based, or calendar versioning?
3. Setup: GitHub Actions to auto-tag milestone closures

---

## Recommended Action Plan

### MUST DO (Blocking next release)

- [ ] Update pyproject.toml version to match what v1.1.2 tag claims
- [ ] Decide backfill strategy for v1.2-1.4
- [ ] Create versioning policy document
- [ ] Add version target labels to all open PRs

### SHOULD DO (Before v1.5.0 ships)

- [ ] Setup GitHub Actions for automatic tagging
- [ ] Update CHANGELOG.md with v1.2-1.4 entries (if backfilling)
- [ ] Document release process
- [ ] Setup automated release notes generation

### NICE TO HAVE

- [ ] Migrate to calendar versioning or clarify SemVer policy
- [ ] Auto-publish release notes to website
- [ ] Track feature→version mapping in PRs

---

## Summary Table

| Aspect | Current State | Recommendation |
|--------|---|---|
| **Git tags** | Mismatch with pyproject.toml | Fix in release process |
| **Missing v1.2-1.4** | Features exist but not tagged | Decide: backfill or skip |
| **Next version** | v1.5.0 planned | ✅ Keep - release PRs #60, #61 |
| **v2.0.0 timing** | Wave 2 (analytics) | Reconsider - analytics doesn't mandate major bump |
| **Version policy** | None documented | Create versioning-policy.md |
| **Automation** | Manual tagging | Setup GitHub Actions tagging |

EOF
