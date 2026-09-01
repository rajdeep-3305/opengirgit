# OpenGirGit

An open-source, local-first interview copilot: a discreet always-on-top overlay
that transcribes the conversation, reads screen-shared questions and drafts
answers — with no telemetry, no subscription and no vendor lock-in.

> **Work in progress.** The API server and the overlay client are being built
> up in the open; expect rapid change.

## Why

The commercial "GirGit AI" overlay shows what is possible in this space, but it
is closed source, Windows-only and billed by the minute. OpenGirGit is a
clean-room re-implementation with the opposite defaults: MIT licensed, fully
auditable, and designed to work entirely offline.

## Status

- [x] API server (FastAPI): auth, chat streaming, resume parsing
- [ ] Desktop overlay: screenshots, hotkeys, speech-to-text
- [ ] Packaging and translations

## License

MIT — see [LICENSE](LICENSE). This project is not affiliated with or endorsed by
the authors of GirGit AI.
