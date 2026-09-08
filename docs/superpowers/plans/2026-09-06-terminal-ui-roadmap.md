# Shambles Terminal UI Delivery Roadmap

The approved design is implemented through the plans below. Execute them in
order:

1. [Application Service Plan](2026-09-06-application-service.md) — creates the
   typed boundary shared by every interface and migrates the existing CLI.
2. [Textual TUI Plan](2026-09-06-textual-tui.md) — builds the responsive
   dashboard, workflows, branding, and same-terminal vendor launch.
3. [Install Scripts and Opt-in Update Notice Plan](2026-09-08-install-and-update-notice.md)
   — names Release artifacts per OS and architecture, adds the curl and irm
   installers that fetch them, and adds the opt-in update check. It comes
   before npm because it gives every platform a working install route that
   does not depend on npm publication, and after the TUI because the notice
   surfaces in it.
4. [Platform Store Hardening Plan](2026-09-06-platform-store-hardening.md) —
   validates macOS Keychain and Windows Credential Manager behavior on real
   vendor installations without exposing credentials.
5. [npm Distribution Plan](2026-09-06-npm-distribution.md) — builds and tests
   platform packages, explicit updates, and the release publication order.
   **npm publishing stays blocked on plan 4.** Publishing a one-line install
   to macOS and Windows advertises switching support that has not been
   confirmed on either, so nothing goes to npm until the credential-store
   behavior there is validated.

Each plan ends in independently usable software. Do not begin a later plan
until the earlier plan's full verification command passes.
