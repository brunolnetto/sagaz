# Versioning Strategy Decision Document

**Date**: April 11, 2026  
**Status**: ⚠️ DECISION REQUIRED  
**Issue**: Version gap from 1.1.2 → 1.5.0 with skipped intermediate versions

---

## Current State

### Actual Releases

```
v1.0.0  (Dec 25, 2025)
v1.0.1  (Dec 26, 2025)
v1.0.2  (Dec 26, 2025)
v1.0.3  (Dec 27, 2025)
v1.1.0  (Feb 24, 2026)
v1.1.1  (Feb 24, 2026)
v1.1.2  (Feb 24, 2026) ← CURRENT
```

### Features That Were Built But Never Tagged

Per ROADMAP, these features are **✅ Done** but lack git tags:

| Version | Features | Status | Code Location | PRs Implementing |
|---------|----------|--------|----------------|-----------------|
| **v1.2.0** | Unified Storage Layer, Compensation Result Passing | ✅ Complete | `sagaz/storage/` | Merged in v1.1.x |
| **v1.3.0** | Pivot Steps, Event Triggers, Dry-Run Mode, CLI v1.0, Framework Integration | ✅ Complete | `sagaz/cli/`, various core changes | Merged in v1.1.x |
| **v1.4.0** | Context Streaming, 24 Industry Examples | ✅ Complete | `examples/` directory | Merged in v1.1.x |
| **v2.1.0** | Saga Replay & Time-Travel | ✅ Complete | `sagaz/versioning/` (partially) | Merged in v1.1.x |

### Planned Releases (No PRs Merged Yet)

```
v1.5.0: Governance & Ops (Wave 0)
├─ #61: AlertManager rules
├─ #60: DLQ support
└─ Goal: Release governance docs

v1.6.0: Storage Extensions (Wave 1)
├─ #62: SQLite storage
├─ #63: Storage migration
└─ #60: DLQ support

v2.0.0: Analytics & Chaos (Wave 2)
├─ #79: ChaosMonkey
├─ #74: sqldim analytics
├─ #71: Visualization dashboard
└─ #67: Fluss + Iceberg tiering

v2.1.0: CLI v2 + CDC + Tenancy (Wave 3)
├─ #81: Saga versioning
├─ #64: CLI v1.0
├─ #65: CLI v2.0
├─ #68: Multi-tenancy
└─ #66: Debezium CDC

v2.2.0: Choreography (Wave 4)
└─ #69: Saga choreography (blocked on #115)

v2.3.0: Core Extensions (Wave 5) - BLOCKED
├─ #70: Event sourcing
└─ #72: Multi-region coordination
```

---

## The Problem: Three Decision Points

### **Decision 1: Should we backfill v1.2.0-v1.4.0?**

**Option A: YES - Backfill (RECOMMENDED)**
- ✅ Creates honest version history matching what code does
- ✅ Clear progression v1.0 → v1.1 → v1.2 → v1.3 → v1.4 → v1.5
- ✅ External users can track which version has which features
- ❌ Creates "older" releases after current v1.1.2
- ❌ Confusing if users have already installed v1.1.2
- **Action**: 
  - Add release notes for v1.2.0-v1.4.0 retrospectively
  - Create git tags pointing to commits where features were merged
  - Tag dates ~1 week intervals simulating weekly releases

**Option B: NO - Accept gap, move to v1.5.0**
- ✅ Simpler, no confusion about versioning
- ❌ Gap is unexplained in version history
- ❌ Users don't know when features landed
- **Action**: Document in release notes that v1.2-1.4 features are in v1.1.2

---

### **Decision 2: Is v2.0.0 the right version for Analytics & Chaos?**

Per Semantic Versioning, **v2.0.0 requires breaking API changes**. Analytics and ChaosMonkey are:
- New features, not API-breaking
- Additive capabilities ✅
- Backwards compatible ✅

**Option A: Keep v2.0.0 (as planned)**
- ✅ Emphasizes wave importance
- ❌ Violates SemVer - should be v1.7.0
- ❌ Confuses downstream consumers
- **Implication**: Next breaking change (if any) would need v3.0.0

**Option B: Use v1.7.0, save v2.0.0 for actual breaking changes**
- ✅ Follows SemVer strictly
- ✅ More predictable versioning
- ❌ Wave structure changes to:
  ```
  v1.5.0: Governance
  v1.6.0: Storage Extensions
  v1.7.0: Analytics & Chaos (was v2.0!)
  v1.8.0: CLI v2 + CDC (was v2.1!)
  v1.9.0: Choreography (was v2.2!)
  v1.10.0: Core Extensions (was v2.3!)
  v2.0.0: Reserved for actual breaking changes
  ```

**Option C: Use calendar or wave versioning**
```
v2026.Q2: Q2 2026 releases (April-June 2026) includes Waves 0-1
v2026.Q3: Q3 2026 releases (July-Sept 2026) includes Waves 2-3
v2026.Q4: Q4 2026 releases (Oct-Dec 2026) includes Waves 4-5

OR

v1.5.0-wave0: Governance
v1.6.0-wave1: Storage
v2.0.0-wave2: Analytics (explicit major feature release)
```

---

### **Decision 3: How to prevent future versioning drift?**

**Current Problem**: Features developed → merged → but version tags lag behind

**Option A: Automate (RECOMMENDED)**
Setup GitHub Actions workflow:
```yaml
on:
  milestone:
    types: [closed]
jobs:
  release:
    - Update pyproject.toml to milestone version
    - Create git tag
    - Generate release notes from PRs
    - Publish to PyPI
    - Create GitHub release
```

**Option B: Use Release GitHub Action**
- Use `actions/create-release` on milestone close
- Require version update in pyproject.toml before merge
- Enforce via branch protection rule

**Option C: Manual process with checklist**
- When milestone closes: PR to update version
- Requires explicit approval
- Document in RELEASE_PROCESS.md

---

## Running the Numbers

### Immediate Impact of Each Decision

#### Scenario A: Backfill v1.2-1.4, Keep v2.0 as-is
```
Next releases:
v1.2.0-rc1 → v1.3.0-rc1 → v1.4.0-rc1  (retrospective tags)
           ↓

v1.5.0     (April 2026)     - Governance & Ops
v1.6.0     (May 2026)       - Storage Extensions  
v2.0.0     (June 2026)      - Analytics & Chaos   [BREAKS SemVer]
v2.1.0     (July 2026)      - CLI v2 + CDC
v2.2.0     (Aug 2026)       - Choreography
v2.3.0     (Sept 2026)      - Core Extensions
```
**Pro**: Users understand features came in v1.2-1.4  
**Con**: v2.0 jump violates SemVer

#### Scenario B: Backfill + Fix to v1.7 = v2.0 (SemVer Strict)
```
v1.2.0-rc1 → v1.3.0-rc1 → v1.4.0-rc1  (retrospective tags)
           ↓

v1.5.0     (April 2026)     - Governance & Ops
v1.6.0     (May 2026)       - Storage Extensions
v1.7.0     (June 2026)      - Analytics & Chaos   [SEMVER COMPLIANT]
v1.8.0     (July 2026)      - CLI v2 + CDC
v1.9.0     (Aug 2026)       - Choreography
v1.10.0    (Sept 2026)      - Core Extensions
v2.0.0     (When actual breaking change happens)
```
**Pro**: SemVer compliant, clear signal when breaking changes occur  
**Con**: No "v2.0" prestige, continues v1.x for longer

#### Scenario C: No Backfill, Jump to v1.5.0 (Accept Gap)
```
v1.1.2 (Feb 2026) - CURRENT
  ↓ [features from 1.2-1.4 are in this version but undocumented]
  
v1.5.0 (April 2026) - Governance & Ops
v1.6.0 (May 2026)   - Storage Extensions
v2.0.0 (June 2026)  - Analytics & Chaos  [BREAKS SemVer]
```
**Pro**: Simpler, no retrospective tagging  
**Con**: Gap unexplained, users confused about v1.2-1.4 features

---

## Recommendation

### For This Week (IMMEDIATE)

**Choose Option A (Backfill) + Option B (SemVer):**

1. **Backfill releases v1.2.0, v1.3.0, v1.4.0**
   - Identify commit where each feature merged
   - Create tags with dates (±1 week) simulating weekly releases
   - Write retrospective release notes
   - This is honest history and helps users understand feature timeline

2. **Change v2.0.0 → v1.7.0** in milestones
   - Update PR #79, #74, #71, #67 milestone from v2.0.0 to v1.7.0
   - Reserve v2.0.0 for actual breaking API changes
   - This follows SemVer strictly

3. **Setup automation**
   - Create GitHub Actions workflow to tag/release on milestone close
   - Add to `.github/workflows/release.yml`
   - Prevent future drift

### Next Release (v1.5.0 - April 2026)

When PRs #60-61 are ready to merge:
```bash
# 1. Update version
sed -i 's/version = "1.1.2"/version = "1.5.0"/' pyproject.toml

# 2. Commit & tag
git tag -a v1.5.0 -m "v1.5.0: Governance & Ops..."

# 3. Push & publish  
git push --tags
python -m build && twine upload dist/*
```

---

## Questions for You

1. **Backfill v1.2-1.4?** (Recommended: YES)
2. **Keep v2.0 or change to v1.7.0?** (Recommended: Change to v1.7.0 for SemVer)
3. **Setup automation now or manual releases?** (Recommended: Automation)
4. **Timeline for v1.5.0 release?** (Proposed: After PRs #60-61 merge)

---

## Related Issues and PRs

- #60 (DLQ) → v1.5.0 or v1.6.0?
- #61 (AlertManager) → v1.5.0
- #62 (SQLite) → v1.6.0
- #79-81 (Analytics, ChaosMonkey) → v1.7.0 (not v2.0)
- PR #161 (quality improvements) → v1.5.0 or maintenance release?

---

## Implementation Steps

- [ ] User decision: Backfill or skip?
- [ ] User decision: v2.0 or v1.7.0?
- [ ] Update milestones in GitHub
- [ ] Create backfill tags (if chosen)
- [ ] Create release.yml GitHub Action
- [ ] Document in RELEASE_PROCESS.md
- [ ] Update ROADMAP.md with corrected versions
