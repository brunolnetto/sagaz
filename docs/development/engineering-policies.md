# Engineering Policies

This document defines the engineering policies that govern how Sagaz is designed,
implemented, and evolved.

These policies are **operative constraints** enforced as part of the development process,
not aspirational guidelines.

---

## Overview

| Category | Practices |
|----------|-----------|
| **Process methodologies** | BDD, TDD |
| **Design principles** | SOLID, DRY, KISS, YAGNI |
| **Data invariants** | ACID |
| **Architectural constraints** | Clean Architecture, Separation of Concerns |

---

## 1. BDD — Behaviour-Driven Development

Express requirements as concrete examples of observable system behaviour.

### Operative rules

- Acceptance criteria in GitHub Issues must use **Given / When / Then** scenarios.
- Integration and end-to-end tests must map to acceptance scenarios.
- Tests must use domain language, not implementation details.

### Example

```
Given a saga with three steps where step 2 raises an exception
When the saga executes
Then compensations for step 1 run in reverse order
And the saga reaches state ROLLED_BACK
```

### Violation signals

- Acceptance criteria described only as implementation steps
- Tests asserting internals instead of observable behaviour
- Technical terms leaking into domain-layer tests

---

## 2. TDD — Test-Driven Development

All production code must be written following **red-green-refactor**:

1. **Red** — Write a failing test that describes the desired behaviour.
2. **Green** — Write the minimal code to make the test pass.
3. **Refactor** — Clean up without changing observable behaviour.

Never write implementation code before a failing test exists.

---

## 3. SOLID Principles

| Principle | Rule |
|-----------|------|
| **SRP** | Each component has one reason to change |
| **OCP** | Extend behaviour without modifying stable code |
| **LSP** | Subtypes must preserve behaviour contracts |
| **ISP** | Prefer small, focused interfaces |
| **DIP** | Depend on abstractions, not concrete implementations |

---

## 4. DRY — Don't Repeat Yourself

Each piece of knowledge must have a single authoritative representation.

**Violation signals**: repeated validation logic, magic values in multiple places, copy-pasted code blocks.

---

## 5. KISS — Keep It Simple

Prefer the simplest solution that correctly solves the problem.

**Violation signals**: over-engineered designs, deep abstraction layers without need, hard-to-read logic.

---

## 6. YAGNI — You Aren't Gonna Need It

Do not implement features before they are required.

### Operative rules

- No implementation without a related issue
- Avoid speculative abstractions
- Remove unused code

**Violation signals**: dead code, unused configuration, features without use cases.

---

## 7. ACID — Data Invariants

All state mutations must respect Atomicity, Consistency, Isolation, and Durability.

### Operative rules

- Use transactions for writes
- Ensure idempotent operations
- Never leave partial state

**Violation signals**: partial writes, silent failures, non-idempotent operations.

---

## 8. Separation of Concerns

Different responsibilities must be isolated in distinct layers.

### Operative rules

- Separate input, logic, and output
- Keep domain independent of serialisation
- Avoid mixing layers

---

## 9. Fail Fast

Detect and signal errors as early as possible.

### Operative rules

- Validate at system boundaries
- Raise explicit errors — never swallow exceptions silently
- Never allow invalid state to propagate

---

## Enforcement

| Mechanism | Scope |
|-----------|-------|
| PR review | Design and behaviour validation |
| CI checks | Code quality (ruff, mypy, coverage ≥ 95%) |
| Integration tests | Behaviour validation via BDD scenarios |
| Architecture docs | Domain consistency (ADRs) |

Reviewers must flag policy violations before approving a PR.

---

## See Also

- [Contributing Guide](contributing.md)
- [Branch Naming](branch-naming.md)
- [Testing Guide](testing.md)
- [Architecture Overview](../architecture/overview.md)
