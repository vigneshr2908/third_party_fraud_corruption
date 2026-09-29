"""
Third-Party Fraud & Corruption Network Detection.

Associated Person (AP) risk ranking as a network problem, using graph analytics.
Built from the Second Line of Defence - Risk & Compliance Analytics.

The package version tracks the MODEL version in config/base.yaml. They are kept
in step deliberately: a code change that alters model output is a model version
change, and an independent validator is entitled to see the two move together.
A test enforces it.
"""
from __future__ import annotations

__version__ = "0.1.0"
__model_id__ = "APND-001"

__all__ = ["__model_id__", "__version__"]