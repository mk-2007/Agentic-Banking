"""Simulated banking APIs (customer, account, transaction, case) and seed data.

Why: Stands in for a real bank behind the same interface, so production can swap it for a
    gateway (PRD section 17).

Where it sits: Layer 1. Only tools may call it; agents never do.
"""
