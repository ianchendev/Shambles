# Shambles Terminal UI Delivery Roadmap

The approved design is implemented through three plans. Execute them in order:

1. [Application Service Plan](2026-09-06-application-service.md) — creates the
   typed boundary shared by every interface and migrates the existing CLI.
2. [Textual TUI Plan](2026-09-06-textual-tui.md) — builds the responsive
   dashboard, workflows, branding, and same-terminal vendor launch.
3. [Platform Store Hardening Plan](2026-09-06-platform-store-hardening.md) —
   validates macOS Keychain and Windows Credential Manager behavior on real
   vendor installations without exposing credentials.
4. [npm Distribution Plan](2026-09-06-npm-distribution.md) — builds and tests
   platform packages, explicit updates, and the release publication order.

Each plan ends in independently usable software. Do not begin a later plan
until the earlier plan's full verification command passes.
