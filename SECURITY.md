# Security policy

## Reporting a vulnerability

Please report security issues privately — do not open a public issue.

Use [GitHub private vulnerability reporting][advisory] or email
**rajdeepbiswas3305@gmail.com**.

Include the affected commit or release, your platform, and a reproduction if
you can. You can expect an initial response within a few days.

[advisory]: https://github.com/rajdeep-3305/opengirgit/security/advisories/new

## Supported versions

Only the latest `main` and the newest tagged release receive security fixes.

## Threat model and hardening defaults

OpenGirGit is a local-first desktop application; the bundled API server is not
meant to be exposed to the internet. The defaults reflect that:

- The server binds to `127.0.0.1` unless `HOST` says otherwise. A
  non-loopback bind refuses to start while the placeholder `JWT_SECRET` (or
  any key shorter than 32 characters) is in use, or while the development OTP
  echo is enabled without SMTP delivery configured.
- Cross-origin requests are only allowed when `CORS_ORIGINS` is set
  explicitly; there is no wildcard default.
- OTPs are stored HMAC-hashed, compared with `compare_digest`, and rate-limited
  per email; JWT claims are validated.
- Client stores (`credentials.json`, `context.json`, `conversations.json`,
  `resume_cache.json`) are written with owner-only permissions (`0600`).
- No telemetry. Provider keys (LLM, SMTP, Deepgram) stay on your machine and
  are only sent to the provider you configured.

In scope: vulnerabilities in this repository's code (auth bypass, injection,
privilege issues in the install scripts, problems in the packaged bundle).

Out of scope: vulnerabilities in third-party dependencies (report those
upstream — see [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)) and
anything that requires an attacker to already control your machine or your
provider account.
