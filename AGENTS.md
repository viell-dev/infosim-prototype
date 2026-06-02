# Agent Notes

Use this file only for repository-local workflow rules. Do not duplicate the
project design, architecture, or experiment history here.

When relevant, read:

- `README.md` for current project structure, run commands, validation notes,
  and the append-only observation log.
- `docs/blueprint.md` for the design intent and milestone framing.

Workflow:

- Stay on `main` unless the user explicitly asks for a branch or worktree.
- Treat real implementation, experiment, validation, and documentation tasks
  as commit-worthy by default. This is an experiment repo; more small,
  descriptive commits are better than leaving useful work unstored.
- Keep commits and the README observation log in sync. When behavior,
  structure, validation results, or experiment conclusions change, add a dated
  observation entry that is specific enough to reconstruct what changed and how
  it was checked, then commit the work.
- Small mechanical follow-ups that do not change behavior or conclusions may
  be committed without a new observation entry, but prefer recording context
  when in doubt.
- Follow the existing commit style: short imperative subject, detailed body
  when the change affects behavior or structure, and the established agent
  attribution trailer when committing on the user's behalf.
