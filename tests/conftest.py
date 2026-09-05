"""Pytest fixtures and the outbound-call guard.

The test isolation guard (public/recorded/memory defaults, cleared inherited
credential variables, and blocked Requests network operations, real DNS
lookups, Gemini client construction, and Snowflake connection creation) is
established in Phase 1 (P1.5), before any service tests are written.
"""
