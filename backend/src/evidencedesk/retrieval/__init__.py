"""Ranking and model adapters; repositories enforce ACL before returning candidates."""

from .ranking import Candidate, RankedEvidence, RetrievalScope, fuse_rankings, select_context

__all__ = ["Candidate", "RetrievalScope", "RankedEvidence", "fuse_rankings", "select_context"]
