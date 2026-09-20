<!-- sourced from: addyosmani/agent-skills (security-and-hardening), heavily trimmed. Web/auth/CORS/rate-limiting/LLM-app sections dropped as not applicable to a local geometry pipeline; kept: input validation at real boundaries, secrets, dependency supply chain. -->
---
name: security-and-hardening
description: >
  Applies where this take-home actually has a trust boundary: reading
  untrusted capture files (photos, video, point clouds) from disk or an
  upload, and managing dependencies. Use when handling any external input
  file or adding a dependency.
---

# Security and Hardening

Most of a full web-app security checklist doesn't apply to a local geometry
pipeline with no auth, no server, no user accounts. What still applies:

## Untrusted input files

A photo, video, or point-cloud file from an unknown capture source is
untrusted input the moment it's read.

- Validate file size and format before parsing (reject absurd dimensions,
  absurd point counts, corrupt headers) rather than letting a parser hang or
  OOM on a malformed file.
- Never construct a filesystem path by concatenating an untrusted filename
  into a directory without checking it resolves inside the expected
  directory (path traversal via `../` in a filename).
- If this ever grows an upload endpoint, treat the uploaded bytes exactly
  the same way, don't trust the client-declared MIME type, check actual
  file content.

## Secrets

No API keys or secrets are expected in this pipeline. If one shows up (a
cloud storage credential, a device pairing token): never in source, never
logged, `.env` for local config and `.env` stays gitignored.

## Dependency hygiene

Before adding a package: does numpy/scipy/opencv/open3d already cover it,
is it maintained, does `uv` report any known vulnerability. One dependency
change per commit. Review `uv.lock` diffs, don't hand-edit the lockfile.

## Not applicable here

Authentication, authorization, CORS, session cookies, XSS/CSRF, SQL
injection, rate limiting, SSRF, LLM prompt injection, PII/GDPR. Skip these
unless the take-home scope grows an actual API or user-facing service, at
which point revisit.
