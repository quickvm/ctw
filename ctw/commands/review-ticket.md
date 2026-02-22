Review completed agent work for a ticket and prepare to submit or iterate.

## Usage

```
/review-ticket ENG-456
/review-ticket jdoss/quickvm#42
/review-ticket ENG-456 --tracker work
```

## Behavior

1. Parse `--tracker <profile>` flag if present, then the ticket ID.
   - If no ticket ID: print error and stop:
     ```
     Error: Usage: /review-ticket ENG-456 [--tracker <profile>]
     ```

2. Run `ctw slug <TICKET_ID> [--tracker <profile>]`
   Save the output as `<branch-name>`.

3. Run `wt list | grep <branch-name>`
   - If not found: print error and stop:
     ```
     Error: No worktree found for <branch-name>. Did the agent finish?
     Run: ctw spawn <TICKET_ID> to start one.
     ```

4. Run `wt switch <branch-name>`

5. Read `TASK.md` in full.

6. Run `git log main..HEAD --oneline`

7. Run `git diff main..HEAD --stat`

8. Run `git diff main..HEAD`

9. Run the project's test command (from CLAUDE.md or the standard runner for the detected stack).

10. Output a review briefing with exactly these sections:
    ```
    ## <identifier>: <title>

    **Agent commits** (<N> commits):
    - <commit list from git log>

    **Files changed:**
    <from --stat output>

    **Agent notes:** <content of "## Agent Notes" section from TASK.md, or "None">

    **Tests:** Pass | Fail
    <failure summary if failing>

    **Suggested action:** <one of:>
    - "Tests pass, no assumptions flagged — ready to submit PR"
    - "Tests pass but agent flagged assumptions — review notes before submitting"
    - "Tests failing — needs fixes before submitting"
    ```

11. Begin interactive review. Ask targeted questions about the diff if anything is unclear.
    Offer to:
    - Make specific changes and commit them
    - Re-spawn the agent with a follow-up: `ctw spawn <TICKET_ID> --prompt "..."`
    - Draft and submit a PR: `gh pr create --draft ...`

## Hard constraints

- Always switch to the worktree (step 4) before reading any files.
- Never create or modify files before confirming the user wants changes.
- If `ctw` or `wt` is not on PATH: fail immediately naming what is missing and where to get it.
- If `wt list` shows the branch but `wt switch` fails: report the error verbatim and stop.
