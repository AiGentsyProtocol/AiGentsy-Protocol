# AiGentsy — Enterprise Security & Diligence: Public Architecture & Trust Core

> **This document consolidates evidence for diligence and does not define protocol or runtime behavior.** Canonical behavior is defined by the runtime/protocol source, the published packages, and the existing specifications this package links to.

## Purpose

A navigable, source-backed entry point for enterprise architecture, security, risk, compliance, and technical buyers evaluating AiGentsy. It maps what is shipped, where the authority and custody boundaries sit, and where to verify each claim independently.

## Product

**AiGentsy is the Consequence Layer for autonomous work: the acceptance gate and portable evidence spine between autonomous output and real-world consequence.** Customer systems perform the external consequence; AiGentsy governs authorization and evidence.

## Canonical lifecycle (one causal `deal_id` trail)

mandate & actor context → proposed consequence → policy & Acceptance → exact authorization → ProofPack → independent verification → **enterprise-owned execution** → performer-signed OutcomeReceipt → later reconciliation → Settlement Memory.

## Authority hierarchy

- **Acceptance** is the decision authority for whether work may proceed to a consequence.
- **PyPI** is the Python package-distribution authority.
- **Runtime / protocol contracts** are the behavioral authorities.
- **GitHub** provides public evidence and source visibility (a reviewed mirror, not the package authority — see [`../../sdk/MIRROR_PROVENANCE.md`](../../sdk/MIRROR_PROVENANCE.md)).

## Non-custody (summary)

AiGentsy **governs the consequence without owning or operating the underlying thing being governed** — it holds the trail, not the thing. It **retains** protocol evidence: mandate/actor references, policy inputs, Acceptance records, exact-authorization metadata, identifiers and hashes, signatures, the event chain, ProofPacks, OutcomeReceipts, reconciliation observations, and Settlement Memory projections. It takes **no custody or operational control** of customer funds, credentials, private keys, compute, documents, source artifacts, result payloads, execution environments, callbacks, target systems, accounts, or external settlement assets. Payment is one reference consequence adapter; model and agent providers are not the control authority. Full boundary treatment: [`01_ARCHITECTURE_AUTHORITY_NONCUSTODY.md`](01_ARCHITECTURE_AUTHORITY_NONCUSTODY.md).

## Verification boundary

Evidence is exported as a portable ProofPack and can be verified **independently** — in the browser or offline via the published `aigentsy-verify` package — without trusting AiGentsy's hosted service. Cryptographic verification proves record **integrity and provenance**; it does **not** prove real-world truth. See [`03_SECURITY_CONTROL_MATRIX.md`](03_SECURITY_CONTROL_MATRIX.md) and [`../gate_and_prove.md`](../gate_and_prove.md).

## Document navigation

| File | Contents |
|---|---|
| `00_EXECUTIVE_README.md` | this entry point |
| [`EVIDENCE_INDEX.md`](EVIDENCE_INDEX.md) | every claim → source repo/path/commit/URL + classification |
| [`01_ARCHITECTURE_AUTHORITY_NONCUSTODY.md`](01_ARCHITECTURE_AUTHORITY_NONCUSTODY.md) | control-plane placement, authority table, non-custody & trust boundaries |
| [`02_THREAT_MODEL.md`](02_THREAT_MODEL.md) | assets, trust boundaries, threats → controls |
| [`03_SECURITY_CONTROL_MATRIX.md`](03_SECURITY_CONTROL_MATRIX.md) | control → implementation + test evidence + classification |

Controlled standard-diligence documents (responsibility matrix, deployment/operations/incident, pilot security acceptance rubric) and the customer-specific annex are provided during a buyer engagement — this public core is the openly publishable subset.

## Evidence-classification legend

`LIVE` · `PACKAGE-PUBLISHED` · `SOURCE-PRESENT` · `TEST-PROVEN` · `PUBLICLY DOCUMENTED` · `CUSTOMER-CONFIGURED` · `CONTRACTUAL` · `REFERENCE` · `DEMO-FIXTURE` · `BENCHMARK` · `DEFAULT-OFF` · `OPTIONAL EXTENSION` · `ABSENT`.

## Current product / package versions (freshness checkpoint)

| Product | Version / identity |
|---|---|
| Python SDK `aigentsy` | 1.16.0 (PyPI) |
| `aigentsy-verify` | 1.5.0 (PyPI) |
| `aigentsy-mcp` | 1.4.0 (PyPI) |
| JavaScript SDK | 1.4.4 (npm) |
| Runtime (live `/build`) | commit `c05759b5eb34abad82ea530e85fa0a2e56dcd84b` |
| Public protocol repo | commit `4a0d54a9e4ec7473e8f2694f799bacee87f1d725` |
| Public SDK source mirror | manifest digest `5bdb5ee48ee0c9809c0a4811dd31f84bdcf1b8f61d03d6c549c220105fdd419b` |

Baseline checkpoint: runtime `c05759b5`, protocol `4a0d54a` (2026-07).

## What this package is not

Not a certification (no SOC 2 / ISO 27001 / PCI DSS / HIPAA / FedRAMP / GDPR certification is claimed — those are procurement-dependent, not currently claimed); not a second protocol specification; not a second authority model; not a marketing deck; not a source of product behavior.
