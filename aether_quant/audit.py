"""The tamper-evident hash chain (formally verified in formal/AetherFormal/HashChain.lean); not the Redis / Postgres
workers."""

from audit.hash_chain import GENESIS_HASH, canonical_timestamp, compute_entry_hash, verify_chain

__all__ = ["GENESIS_HASH", "canonical_timestamp", "compute_entry_hash", "verify_chain"]
