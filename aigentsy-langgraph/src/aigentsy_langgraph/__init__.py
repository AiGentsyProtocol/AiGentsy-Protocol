"""AiGentsy Settlement Protocol — LangGraph nodes."""

# Version lockstep — keep in sync with pyproject.toml [project].version.
# The G2 deploy taught us why this matters: a string-vs-package version
# drift makes upgrades non-obvious. Bumped together at 0.3.0 (Tier-2
# parity: enroll_key, accept, reject, outcome_receipt).
__version__ = "0.4.0"

from .client import AsyncAiGentsyClient
from .keypair import (
    SigningKeypair,
    NON_CUSTODIAL_NOTICE,
    FORBIDDEN_PRIVATE_KEY_FIELDS,
)
from .nodes import (
    # 0.2.0 nodes — byte-unchanged surface
    register_node,
    proof_pack_node,
    auto_go_node,
    go_node,
    verify_node,
    settle_node,
    timeline_node,
    full_deal_node,
    settle_multi_node,
    attestation_node,
    proof_chain_node,
    # 0.3.0 Tier-2 parity nodes
    enroll_key_node,
    accept_node,
    reject_node,
    outcome_receipt_node,
)

__all__ = [
    "__version__",
    "AsyncAiGentsyClient",
    "SigningKeypair",
    "NON_CUSTODIAL_NOTICE",
    "FORBIDDEN_PRIVATE_KEY_FIELDS",
    # 0.2.0 surface (unchanged)
    "register_node",
    "proof_pack_node",
    "auto_go_node",
    "go_node",
    "verify_node",
    "settle_node",
    "timeline_node",
    "full_deal_node",
    "settle_multi_node",
    "attestation_node",
    "proof_chain_node",
    # 0.3.0 additions
    "enroll_key_node",
    "accept_node",
    "reject_node",
    "outcome_receipt_node",
]
