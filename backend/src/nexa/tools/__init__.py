"""The controlled tool layer between agents and the bank.

Why: Every tool declares schema, risk level and required role, and enforces permissions +
    audit itself (PRD section 14).

Where it sits: Layer 2. The only door from agents to bank_sim and rag.
"""
