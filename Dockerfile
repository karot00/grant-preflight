# Grant Preflight application image.
#
# Implemented in Phase 6 (P6.1) using the exact digest-qualified base:
# docker.io/library/python:3.12.14-slim-bookworm@sha256:9c47360a2a0355e2da18516d0b1c2126ec22c195d2185e97347c9d98398c5bef
#
# Non-root UID/GID 10001, runtime lock only (hashed, wheels-only install),
# no operator secrets or development dependencies in the image.
