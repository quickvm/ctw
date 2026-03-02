Capture the current tangential issue as a ticket without switching context.

## Usage

```
/push-ticket
/push-ticket the logout button throws 500 when session is expired
/push-ticket --tracker personal
/push-ticket the logout bug --tracker quickvm
```

## Behavior

1. Parse `--tracker <profile>` from the invocation first, before anything else. Use it for all
   `ctw` calls in this session.

2. Strip the `--tracker` flag and its value from the input. The remainder is the inline
   description (may be empty).

3. If no description provided: ask **exactly one question** — one sentence description or type
   `summarize`.
   - If `summarize`: infer title and description entirely from session context — recent file
     edits, tool calls, error messages, what the user was working on. Do **not** ask follow-up
     questions.

4. Derive a concise title (≤60 chars) from the description.

5. Run:
   ```
   ctw create-issue "<title>" "<description>" [--tracker <profile>]
   ```

6. After ticket is created, ask **one yes/no**: "Create a background worktree now? [y/N]"
   - If yes: run `ctw slug <TICKET_ID> [--tracker <profile>]` → `wt switch --create <branch-name> --yes`
   - Do **NOT** switch into the new worktree.

7. Output exactly one summary line then stop:
   ```
   ✓ ENG-456 "Fix auth middleware null check" [work] → branch eng-456-fix-auth-middleware (worktree created)
   Resume what you were doing.
   ```
   Omit `(worktree created)` if worktree was declined. The `[work]` token is the tracker profile used.

## Hard constraints

- **Always** run `ctw create-issue` when invoked — no exceptions. Do not check session
  history. Do not say "already filed." Do not deduplicate. If the user runs `/push-ticket`,
  run `ctw create-issue`. The user is responsible for deciding whether a ticket already exists.
- **Never** switch worktrees or modify any files in the current session.
- **Never** ask more than one clarifying question total.
- Ticket description must be fully self-contained: what the problem is, file paths if known,
  expected vs actual behavior, relevant error messages or snippets from current session context.
  A fresh Claude Code session with zero prior context must be able to action it without
  additional input.
- If `ctw` is not on PATH, fail immediately with:
  ```
  Error: ctw not found. Install with: cd /home/jdoss/src/quickvm/ctw && uv tool install -e .
  ```
