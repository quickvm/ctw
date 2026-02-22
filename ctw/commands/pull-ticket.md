Load a ticket into an isolated worktree and start working on it immediately.

## Usage

```
/pull-ticket ENG-456
/pull-ticket jdoss/quickvm#42
/pull-ticket ENG-456 --tracker work
/pull-ticket ENG-456 --no-worktree
```

## Behavior

1. Parse `--tracker <profile>` and `--no-worktree` flags first, then the ticket ID.
   - If no ticket ID: print error and stop:
     ```
     Error: Usage: /pull-ticket ENG-456 [--tracker <profile>] [--no-worktree]
     ```

2. Run `ctw context <TICKET_ID> [--tracker <profile>] -o TASK.md`

3. Unless `--no-worktree`:
   - Run `ctw slug <TICKET_ID> [--tracker <profile>]` to get branch name
   - Run `wt list | grep <branch-name>` to check existence
   - If exists: `wt switch <branch-name>`
   - If not: `wt switch --create <branch-name> --yes`

4. Read `TASK.md` fully.

5. Run `git log --oneline -5` and `git status`

6. If commits exist beyond main: run `git diff main...HEAD`

7. Output this exact briefing:
   ```
   ## <identifier>: <title>

   **Tracker:** <profile name used>
   **Provider:** <Linear | GitHub>
   **What:** <1-2 sentence problem summary>
   **Where:** <likely relevant files/directories inferred from ticket description>
   **State:** <"No prior work" | "X commits ahead of main: <one-line summary>">

   Starting with: <one sentence describing your first action>
   ```

8. **Begin work immediately** after the briefing. No confirmation prompt. Never say "shall I
   proceed" or "let me know if you want me to start."

## Hard constraints

- **Never** ask clarifying questions before starting — TASK.md is the source of truth.
- If `ctw` or `wt` is not on PATH: fail immediately naming what is missing and where to get it.
- The briefing is for situational awareness only — do not wait for the user to confirm direction.
