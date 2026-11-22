# Third-party components

This repository ships configuration, integration scripts and source patches, not
the third-party binaries or user data. Builds fetch the official upstream sources.

* Codex CLI: OpenAI, Apache-2.0, https://github.com/openai/codex.
  `codex-image-preview.patch` modifies the 0.169.0 TUI. Keep the upstream license
  and notices when distributing a resulting binary. Official support files retain
  their packaged notices.
* tmux: https://github.com/tmux/tmux, ISC/BSD licenses as listed in upstream
  `COPYING`. The private install includes that file.
* Broot, its configuration/skin templates and icon font:
  https://github.com/Canop/broot, MIT; retain the upstream LICENSE. Broot patches
  are for this independent setup, not an upstream PR.
* `broot-input-events.rs` includes adapted Crossterm event-reading code. Its MIT
  notice is preserved in `broot-input-events.LICENSE` and installed with Broot.
* Catppuccin themes: https://github.com/catppuccin, MIT. Ghostty/Starship supply
  the referenced themes; the source preview palette uses their Mocha colors.

No license for another project's code is replaced by the license for this setup.
