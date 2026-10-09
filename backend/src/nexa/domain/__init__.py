"""Pure data models and enums shared by every layer.

Why: Single source of truth for what a Case, Decision, Action or Evidence *is*. Contains no
    I/O and imports nothing else from nexa, so any layer can depend on it safely.

Where it sits: Layer 0 (bottom). Everything may import it; it imports nothing.
"""
