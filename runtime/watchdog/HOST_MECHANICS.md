# Host mechanics: codex, omp

Grounding for the watchdog's four-capability `HostAdapter` seam (context read,
input-injection gate, `needs_input` detection, handoff/clear command mapping)
against the two hosts session_orchestration (`scripts/hermes/mcp_hermes_orchestrator.py`)
already automates generically. Every claim below is backed by either a real
file:line in this repo or a real command/tmux-capture output produced while
authoring this doc (2026-07-10, macOS, codex-cli 0.142.5, omp v16.1.15). No
speculative claims about unobserved host versions are made without saying so.

Fixture diversity checklist for both hosts (nominal read, missing-usage case,
input-ready rendering) lives under `tests/fixtures/watchdog/codex/` and
`tests/fixtures/watchdog/omp/` — each file's `_provenance` field cites its
exact source (rollout path + line, or the tmux capture-pane invocation used).

**Durable command-output evidence:** every empirical (non-file:line) claim
below carries a bracketed tag — `[C-n]` for codex, `[O-n]` for omp — that
resolves to a verbatim, re-runnable command-output block in
`tests/fixtures/watchdog/codex/PROVENANCE_commands.txt` and
`tests/fixtures/watchdog/omp/PROVENANCE_commands.txt` respectively. Two live
keystroke observations (the `/new` clear on each host) were made during the
2026-07-10 grounding run and cannot be reproduced from a static artifact; they
are explicitly scoped as single-session observations and are corroborated
durably by the per-chat file-multiplicity evidence (`[C-2]`, `[O-3]`) rather
than asserted as re-runnable fact.

## Lifecycle notification delivery contract

Lifecycle state is committed independently of Discord delivery. The daemon may
attempt a notification after a daemon, intervention, rollover, child-outcome,
join, or coordinator-wake transition, but a disabled transport, timeout,
launch error, or non-zero transport exit never blocks or reverses that
transition. `runtime/watchdog/notify.py` returns an observable delivery status
(`delivered`, `disabled`, or `failed`) instead of raising.

Every lifecycle notification has a deterministic
`watchdog-notify:v1:<sha256>` event ID derived from its event family and the
caller's stable logical identity fields. Human-facing title/body text is not
part of the ID, so rerendering or retrying the same logical event retains its
identity. Callers must use durable IDs (for example daemon generation, outcome
ID, join ID, rollover ID, or wake outbox ID), not timestamps or attempt counts.

The delivery classes are intentionally distinct:

- `daemon`, `intervention`, `rollover`, and `join` are
  `best_effort_at_most_once`. A failed or disabled attempt remains observable,
  but the watchdog does not retry it and lifecycle processing continues.
- `child_outcome` and `coordinator_wake` are `retryable`. Each attempt reuses
  the same stable event
  ID. This describes notification delivery only: durable wake outbox delivery
  is at least once, while generation-fenced coordinator acknowledgement and
  deduplication provide exactly-once logical handling. The completed wake
  outbox record retains notification status and attempt count;
  failed, disabled, or crash-interrupted (`pending`) attempts are retried by a
  later daemon poll under that same action/event ID.

Action-backed delivery attempts also emit `lifecycle_notification_delivery`
records to `signals.jsonl`. Intervention markers durably claim their single
best-effort attempt before transport invocation, so replaying an already
completed action marker cannot redeliver it. A crash after that claim may lose
the best-effort notification, which is the deliberate at-most-once tradeoff;
it never rolls back the completed action.

The existing shell transport exits zero both after a successful post and when
Discord configuration is absent. The lifecycle primitive therefore resolves
`notify.discord_webhook_url` before invoking the default shell transport; an
empty value yields the observable `disabled` result without invoking it.

Current production hooks use authoritative durable boundaries: daemon
start/stop after lock/heartbeat confirmation, intervention after a completed
action marker, child outcome after its authorized terminal commit, and join /
coordinator wake after a sealed epoch atomically creates the stable join and
outbox records, and coordinator rollover after its second fresh locked commit.
Rollover writes canonical atomic `handoff.json` between its prepared and
committed stages, retains one logical coordinator/session, and moves only the
active host target to a strictly newer incarnation. Its stable `rollover_id`
keys one fail-open, at-most-once event; a stale writer or target is rejected
before authoritative state changes. Legacy handoff transitions and other
provisional pre-commit paths must not emit lifecycle events.

## Sealed fanout join protocol

Fanout allocation admits deterministic child IDs into one locked, open epoch
identified by `group:v1:<sha256(coordinator_session_id)>`. `seal-group`
explicitly closes epoch 1; exact replay is idempotent, while a new child
admission after sealing fails without persisting the child. An unsealed group
never joins, even if all current children are terminal.

Authorized terminal outcomes evaluate sealed readiness under the same registry
flock. A provisional lease-reaper outcome cannot materialize the join before
its resolution deadline; an authorized explicit report can replace it during
that window. The final outcome creates exactly one content-derived `join:v1:`
record and one `wake:v1:` outbox record containing the terminal summary,
coordinator target, persisted monotonic generation, and deterministic
`watchdog_ack` metadata (`outbox_id` plus `coordinator_generation`). Failed
children are terminal and therefore do not deadlock the join.

The daemon retries the stable outbox payload on every poll/restart until
`ack-join` succeeds. Delivery is deliberately at least once and may repeat;
the acknowledgement must present the outbox's coordinator generation, and an
exact acknowledgement replay returns success without handling the join twice.
A stale generation is rejected, leaving the outbox durable for the current
coordinator authority. A prepared marker means the host effect is ambiguous;
every later attempt for that coordinator generation pauses until the ambiguity
is resolved instead of creating a new marker.

Standing-daemon readiness writes a fresh `wd-<uuid>` incarnation ID into the
heartbeat file immediately while holding the stable daemon flock, before
startup reconciliation or polling, and reuses it for every heartbeat from that
process. Publication failure releases the flock. Managed `ensure`, direct
standing `run`, and `stop` share a lifecycle-operation sidecar; the managed
child explicitly delegates that sidecar to its waiting parent to avoid
self-deadlock. `run --once` performs work without publishing standing readiness.
Start and stop event
keys use that persisted incarnation plus the transition name, rather than the
PID, so PID reuse cannot alias distinct daemon lifecycles and the paired events
remain correlatable.

The daemon flock pathname is never removed during release. Keeping one inode
at the stable path prevents an unlock-then-unlink race in which old and new
openers could each hold a flock on a different inode. A serialized `stop`
captures the current PID and incarnation, waits for that captured ownership to
release, and makes at most one best-effort notification attempt before releasing
the operation sidecar. Thus a concurrent stop becomes a no-op and a replacement
cannot publish readiness during the captured stop transition. This is not a
crash-recoverable exact-once notification store: a crash can lose the attempt.

The watchdog state directory and the active daemon/lifecycle-operation lock
pathnames are trusted cooperative infrastructure. Deliberate unlink or
replacement of an active lockfile by another same-user process is unsupported;
that actor can also rewrite watchdog state or executable code and is outside
this concurrency contract. Ordinary invocation inputs remain untrusted: public
CLI flags, environment values, and substituted numeric FDs cannot bypass lock
ownership validation. Once a managed child accepts its parent's inherited
lifecycle-operation FD, it immediately marks that descriptor non-inheritable
before configuration resolution, lifecycle acquisition, reconciliation, or
polling. Failure to apply that descriptor-local boundary closes the accepted FD
and hard-fails startup rather than falling back to sidecar acquisition.

## Shared actuation mechanics (host-agnostic; already in-repo)

Both hosts are driven the same way as `claude` in the existing so-MCP
reference code — this part needs no new per-host mechanics:

- Session spawn: `tmux new-session -d -s <name> <host-command>`
  (`scripts/hermes/mcp_hermes_orchestrator.py:835`).
- TUI-ready wait before the first prompt: poll `tmux capture-pane -p` until
  non-empty (`scripts/hermes/mcp_hermes_orchestrator.py:448-474`,
  `_await_tui_ready`).
- Prompt submission: literal `tmux send-keys -t <session> -l "<prompt>"`,
  then a settle sleep (`_SUBMIT_SETTLE_SECONDS`, 0.2s), then a **separate**
  `tmux send-keys -t <session> Enter` — sending prompt+Enter in one call
  races the composer's bracketed-paste and can swallow the Enter
  (`scripts/hermes/mcp_hermes_orchestrator.py:837-856`, comment at 839-842).
  Confirmed empirically for T001: both `codex` and `omp` accept this same
  literal-text + settle + separate-Enter pattern for ordinary prompts AND
  for slash commands (`/new`, `/model`, etc. — see below).
- Liveness check: `tmux has-session -t <session>`
  (`scripts/hermes/mcp_hermes_orchestrator.py:502-518`).

## codex

### Transcript / session-state file location

- Path: `~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-timestamp>-<session-id>.jsonl`
  — confirmed via `find ~/.codex/sessions -type f -iname "*.jsonl"`; the exact
  three-path sample and the derived naming shape are captured verbatim in
  evidence block **[C-1]**.
- One file per **chat**, not per tmux session or per CLI invocation. The
  DURABLE evidence is **[C-2]**: a single date-sharded directory
  (`2026/07/10/`) holds many same-day rollout files, one per chat/session id.
  The keystroke that triggers rotation — issuing `/new` inside a running
  `codex` TUI, which lazily creates a brand-new rollout file (new session id)
  on the next turn rather than appending — was observed live once during the
  2026-07-10 grounding run (`codex` then printed `To continue this session,
  run codex resume 019f4ceb-21f8-7863-8445-afc91454d99b` and a fresh
  `rollout-2026-07-10T09-45-06-019f4ceb-...jsonl` appeared with a new
  `session_meta` line). That single keystroke observation is **not**
  re-runnable from a checked-in artifact and is scoped as such; **[C-2]** is
  the durable corroboration.
  **Watchdog implication:** a byte-offset read pointer (D2) is only valid
  within one rollout file. After a `/new` (or `codex resume`), the daemon
  must re-discover the newest file under the session's date-sharded
  directory rather than continuing to tail the old offset.
- Other adjacent state (not the transcript), listed verbatim in **[C-3]**:
  `~/.codex/session_index.jsonl` (an index of session metadata, not
  turn-by-turn content) and `~/.codex/history.jsonl` (a separate global
  prompt history, not per-session).

### Token-usage field: available, but per-turn absence is real and must be tolerated

- Each turn emits an `event_msg` of `payload.type == "token_count"` carrying
  `payload.info.total_token_usage.total_tokens` and
  `payload.info.model_context_window` in the SAME event — a self-contained
  usage-pct read (`total_tokens / model_context_window`). Real captured
  example: `tests/fixtures/watchdog/codex/token_count_nominal.json`
  (22,331 / 258,400 tokens → 8.6% used); independently re-verified against a
  second live rollout in evidence block **[C-4]** (line 12 of that file:
  `total_tokens=19837`, `model_context_window=353400`).
- **However**, a turn can complete (`event_msg:task_complete`) with **zero**
  preceding `token_count` events in the whole file — observed in two
  independent real cases, both recorded in
  `tests/fixtures/watchdog/codex/task_complete_missing_usage.json`:
  1. A turn that errors before any billed tokens exist (e.g. an invalid
     model id was selected) — `task_complete.last_agent_message` is `null`,
     `duration_ms` is small, and no `token_count` line exists between
     `task_started` and `task_complete`.
  2. An entire 8-line `codex_exec`-originated session (`originator:
     "codex_exec"`, used by e.g. the mr-reviewer's `codex exec -` path,
     see `scripts/log-phase.sh:17`) that completed a full review turn with
     `last_agent_message: null` and **no `token_count` event anywhere in
     the file**.
- **Fallback estimator (for when the newest `token_count` predates the
  watchdog's staleness tolerance, or none exists yet in the file):**
  transcript byte-length heuristic — `bytes_since_session_start /
  (model_context_window * average_bytes_per_token)`, using a conservative
  `average_bytes_per_token` (~4 for English text/code) as a coarse proxy
  until a real `token_count` event appears. **This is a degraded heuristic,
  not a safe one: it may UNDER-report actual context usage** (token-dense
  content — long identifiers, base64, CJK — packs more tokens per byte than
  ~4, so a byte-length estimate reads lower than reality). An under-report
  is the dangerous direction: it overstates remaining headroom and can
  **suppress or delay a real context-threshold handoff trigger**. The
  adapter must therefore treat a byte-length estimate as low-confidence:
  (a) log a `context_estimate_degraded` event whenever it is used so the
  under-report is visible, (b) apply a conservative correction (e.g. round
  the estimate up, or use a smaller assumed bytes-per-token) so the
  estimate biases toward *over*-reporting usage rather than under-reporting
  it, and (c) never treat a byte-length reading as equivalent to a real
  `token_count`. Document this as a known estimator weakness, not a silent
  parity claim.
- `model_context_window` is present on `task_started` too
  (`{"type":"task_started",...,"model_context_window":258400,...}`), so a
  context ceiling is knowable even before the first `token_count` arrives —
  re-verified in evidence block **[C-5]** (same live file as [C-4]:
  `task_started.model_context_window=353400`).

### Prompt-glyph(s) for input-ready detection

- Idle, ready-for-input composer: a line beginning with `›` (U+203A single
  guillemet), e.g. `› Write tests for @filename` (the placeholder text
  changes; the leading `›` glyph and the footer line `<model> <effort> ·
  <cwd>` are the stable markers). Captured verbatim in
  `tests/fixtures/watchdog/codex/prompt_ready_pane.txt` (STATE 1).
- Busy/thinking: composer glyph disappears; the harness's own
  `_needs_input()` last-3-lines check
  (`scripts/hermes/mcp_hermes_orchestrator.py:534-563`) would correctly
  return `False` during this window since no line ends in `›`/`>`.
- **Divergence from the existing generic detector:** an interactive
  selection menu (e.g. `/model`) also uses a leading `›` on the highlighted
  row, but its footer reads `Press enter to confirm or esc to go back` —
  this does **not** match the omp-tuned substrings
  `"enter select"` / `"esc cancel"` hard-coded at
  `scripts/hermes/mcp_hermes_orchestrator.py:561`. A codex-specific
  `needs_input` matcher must add this footer phrase (or detect the `›  N.
  <option>` numbered-list shape) rather than reusing the omp constants
  unmodified. Captured verbatim in `prompt_ready_pane.txt` (STATE 2).

### Handoff-equivalent / clear-equivalent

- Handoff-equivalent: none needed at the host level — `/z-handoff` is a
  z-harness skill invoked the same way as any other prompt (literal
  `send-keys` + Enter); it is host-agnostic by construction.
- Clear-equivalent: **`/new`** — "start a new chat during a conversation".
  The autocomplete text, the no-confirmation-dialog behavior, and the
  token-usage + `codex resume` output below were all observed live once
  during the 2026-07-10 grounding run (typing `/` then `new` surfaced exactly
  one autocomplete row `/new  start a new chat during a conversation`;
  executing it via literal `send-keys -l "/new"` + settle + `Enter` fired
  immediately with no confirmation and reset the composer). **This is a
  live-keystroke observation, not re-runnable from a static artifact** — its
  durable corroboration is the per-chat file rotation shown in **[C-2]** (a
  fresh rollout file appears per new chat). Real captured output from that
  grounding run:
  ```
  Token usage: total=11,373 input=11,358 (+ 4,992 cached) output=15 (reasoning 8)
  To continue this session, run codex resume 019f4ceb-21f8-7863-8445-afc91454d99b
  ```
  This is a plain-text keystroke sequence — no Esc/Ctrl-C — consistent with
  the INTENT's "no control-key interventions" constraint.
- `/compact` also exists ("summarize conversation to prevent hitting the
  context limit") as a lighter-weight alternative to a full `/new`, but v1
  behavior-1 (context-threshold handoff) uses `/z-handoff` + `/new`, not
  `/compact` — `/compact` is out of scope for this task, noted only because
  it surfaced during grounding.

### Byte-offset / append semantics (D2)

- Confirmed append-only within one rollout file. Durable evidence: **[C-4]**
  is a check-in of a real multi-turn rollout whose `token_count` events'
  `total_token_usage.total_tokens` strictly increase down the file (an
  in-place-mutation model could not produce monotonically-growing later
  lines while earlier lines are unchanged). This was also seen live during
  grounding (a session file grew 11 → 17 lines across two turns with no
  earlier-line rewrites).
- **Not** append-only across a whole tmux-session lifetime — see the `/new`
  finding above: a new rollout file starts per chat. A watchdog must track
  "current transcript file for this tmux session" as a value that can
  change out from under a held byte offset, not just a byte offset into a
  fixed path.

## omp

### Transcript / session-state file location

- Path: `${PI_CODING_AGENT_DIR:-~/.omp/agent}/sessions/<cwd-slug>/<ISO-
  timestamp>_<session-id>.jsonl`, where `<cwd-slug>` is the launch cwd with
  `/` replaced by `-` (e.g. `/private/tmp/.../scratchpad` →
  `--private-tmp-...-scratchpad--`). The env-var/default is quoted verbatim
  from `omp --help` in **[O-2]** (`omp/16.1.15`, **[O-1]**); the cwd-slug
  directory shape is shown verbatim in **[O-3]**.
- Also JSONL, also one file per chat. Durable evidence: **[O-3]** shows the
  per-cwd shard directories, each accumulating one file per chat. The
  keystroke behavior — `/new` printing `New session started`, resetting the
  footer baseline, and starting a fresh `.jsonl` rather than appending — was
  observed live once during the 2026-07-10 grounding run; **it is not
  re-runnable from a static artifact** and is scoped as a single-session
  observation, corroborated durably by the per-chat file multiplicity in
  **[O-3]** (matches codex's lazy per-chat file creation, [C-2]).
- **Hazard, not a transcript source:** `${PI_CODING_AGENT_DIR}/models.yml`
  contains live provider API keys in plaintext (verified by reading this
  machine's own `models.yml`, which has an `apiKey: nvapi-...` entry for an
  NVIDIA NIM provider). A watchdog implementation must only ever read
  files under `sessions/`, never `models.yml` / `config.yml` / `*.db`, to
  avoid ever touching credentials (STYLE.md P-003). The presence of these
  non-transcript files alongside `sessions/` is listed verbatim in **[O-4]**.
- Non-transcript state also lives in SQLite (`agent.db`, `history.db`,
  `models.db`, see **[O-4]**) — these are omp's own indices, not something
  the watchdog should read.

### Token-usage field: available per-message, but the model's context-window ceiling is NOT co-located

- Each assistant `message` event carries a `message.usage` object:
  `{input, output, cacheRead, cacheWrite, totalTokens, reasoningTokens,
  cost: {...}}`, plus a `message.contextSnapshot` object:
  `{promptTokens, nonMessageTokens}`. Real captured example:
  `tests/fixtures/watchdog/omp/usage_nominal.json` (`totalTokens: 31119`,
  `contextSnapshot.promptTokens: 31059`); re-verified against the live source
  file in **[O-6]** (lines 6/8/10: `totalTokens` 28854 → 30984 → 31119, each
  with `contextSnapshot` present).
- **Gap vs. codex:** neither `usage` nor `contextSnapshot` carries the
  model's max context window. That number must be cross-referenced
  separately by model id — via `omp models` or the local `models.db`. The
  `omp models` action semantics (`ls`/`find`/`refresh`/`canonical`, plus a
  `--json` machine-readable flag) and the actual context column
  (`gpt-5.5-* │ 200K`) are captured verbatim in **[O-5]**. This means a
  self-contained "read context, get a
  percentage" call is **not** possible from the transcript file alone for
  omp; the adapter needs a second, session-independent lookup (a static
  model→context-window map refreshed periodically via `omp models`, since
  spawning `omp models` on every poll is unnecessary subprocess overhead
  for a value that rarely changes). **This is evidence the four-capability
  `HostAdapter.read_context()` contract should explicitly allow a
  multi-source implementation (transcript + a cached model registry) for
  omp**, rather than assuming a single self-contained read as codex allows.
- **Missing/degraded case:** on an error-terminated turn
  (`message.stopReason == "error"`), `usage` is present but **every numeric
  field is zero** and `contextSnapshot` is **entirely absent** from the
  message. Two real examples (a rate-limit error and a context-length-
  exceeded error) are recorded in
  `tests/fixtures/watchdog/omp/usage_missing_or_degraded.json`, and the shape
  is re-verified against the live corpus in **[O-7]** (`totalTokens=0`,
  `contextSnapshot` ABSENT, `errorMessage` = usage-limit-reached). A naive
  reader that takes the last message's `usage.totalTokens` at face value
  would report a false 0%, which could suppress or delay a real handoff
  trigger — a real host-specific correctness risk. **Fallback:** on
  `stopReason == "error"` or `contextSnapshot` absent, skip that message
  and use the previous message's snapshot (or the same byte-length
  estimator described for codex) rather than trusting the zeroed usage.

### Prompt-glyph(s) for input-ready detection

- **Contradicts the existing generic detector's assumption.** The comment
  at `scripts/hermes/mcp_hermes_orchestrator.py:538-539` states "omp's TUI
  shows `❯` as the input prompt when it is waiting." On this machine's
  installed `omp v16.1.15`, the **default idle composer shows no printable
  prompt glyph at all** — confirmed with both `tmux capture-pane -p` and
  `tmux capture-pane -p -e` (escape-sequence-preserving capture): the
  composer's content line is pure whitespace inside the bordered box, no
  `❯`/`>` character present. Captured verbatim in
  `tests/fixtures/watchdog/omp/prompt_ready_pane.txt` (STATE 1).
  - **Reliable substitute — but the percentage footer ALONE is NOT a ready
    signal.** The footer bar renders a context-usage percentage
    (`<pct>%/<window>`) in BOTH the idle and the busy state — the spinner
    does **not** replace the footer. Confirmed by the fixture: STATE 2
    (busy) shows `⠼ Working…` on one line while the very next footer line
    still reads `10.1%/272K`
    (`tests/fixtures/watchdog/omp/prompt_ready_pane.txt:29` and `:31`).
    Using "percentage present" as the ready gate would therefore send
    input while omp is busy. The correct injection/ready gate is a
    **conjunction**: `<pct>%/<window>` footer present **AND** no busy
    marker anywhere in the captured pane (no `Working…`, no spinner glyph
    from the braille-dot set `⠁⠂⠄⡀⢀⠠⠐⠈`/`⠹⠸⠼…`, no `⟨esc⟩` interrupt hint).
    The percentage is used only to confirm the composer has finished
    rendering; the busy-marker check is what actually distinguishes idle
    from working.
  - Busy/thinking state shows a spinner glyph + `Working…` + `⟨esc⟩` hint
    (STATE 2 in the same fixture) **alongside** a still-valid footer
    percentage — the presence of any of these busy markers must gate
    `needs_input`/injection to `False` regardless of the footer reading.
  - A `›`/`>` glyph DOES appear, but only as the **filter input line** of
    full-screen overlays (e.g. `/model`'s picker), not as the normal
    composer's idle marker (STATE 3). A `needs_input` matcher for omp must
    not key off `>` alone; it should key off the live-footer's absence of
    a `<pct>%/<window>` reading plus presence of a rendered option list.
  - This divergence was only exercised for the specific installed version
    (16.1.15) and launch mode (`omp --allow-home`, default TUI, no
    `--mode json/rpc`); it is not verified across omp's other `--mode`
    values or older/newer versions — flagged as an assumption boundary,
    not asserted as universal.

### Handoff-equivalent / clear-equivalent

- Handoff-equivalent: same as codex — `/z-handoff` is host-agnostic.
- Clear-equivalent: **`/new`** — "Start a new session" (same command name
  as codex). The multiple fuzzy-matched autocomplete rows (`new`,
  `skill:qt-bot-new-feature`, `plan-review`, `branch`, `fork` with `new`
  top/highlighted), the single-`Enter` no-confirmation execution, the
  `New session started` print, and the footer-baseline reset were all
  observed live once during the 2026-07-10 grounding run. **These are
  live-keystroke observations, not re-runnable from a static artifact** —
  their durable corroboration is the per-chat file rotation in **[O-3]**.
  Because omp's autocomplete can surface
  multiple fuzzy matches (unlike codex's single-match case for `/new`),
  the watchdog's actuator must confirm the top row is actually `new`
  before sending Enter — or send an unambiguous longer token (`/new` plus
  a differentiating keystroke) to avoid accidentally invoking `/new
  feature`-style skills. This is a real, observed risk specific to omp's
  fuzzier command palette, not present in codex's exact-prefix matching.

### Byte-offset / append semantics (D2)

- Confirmed append-only within one chat's `.jsonl`. Durable evidence:
  **[O-6]** shows a real multi-turn session whose per-message `totalTokens`
  grow monotonically down the file (28854 → 30984 → 31119) with earlier
  lines unchanged — inconsistent with in-place rewriting. (Also seen live
  during grounding: a file grew from 5 to 24 lines with no earlier-line
  rewrites.)
- Same per-chat file boundary as codex: `/new` starts a fresh file lazily
  on next turn, so a held byte offset must be re-anchored to the newest
  file in the cwd-slug directory after a clear, exactly as documented for
  codex above.

## Summary: is the four-capability interface sufficient?

Both hosts fit the four capabilities (context read, injection gate,
`needs_input` detection, handoff/clear mapping) — no fifth capability is
needed. But two per-host adapter requirements are not obvious from the
interface name alone, and should be captured in the adapter implementation
(T005 and its follow-ons), not left as an implicit assumption:

1. **codex** needs a documented fallback path for `read_context()` when the
   newest `token_count` is stale or entirely absent — the byte-length
   estimator (see above), which is a *degraded* heuristic that may
   under-report usage and must therefore be treated as low-confidence
   (log `context_estimate_degraded`, bias the estimate upward). codex is not
   lacking a usage source outright, so this is an adapter robustness
   requirement, not a `/z-amend` decision.
2. **omp** needs a second data source (a periodically-refreshed model→
   context-window map, since `omp models` output must be parsed once and
   cached) composed with the transcript read — flagged here as worth an
   explicit `/z-amend` note if the adapter design assumed a single-source
   read; the same degraded byte-length estimator (with the same
   conservative/upward-biased handling) is the last-resort fallback if the
   model id can't be resolved against the cached registry (e.g. a custom
   provider model not in `omp models`' default output).

Neither host lacks a context-usage source outright, so full codex/omp
parity for behavior-1 (context-threshold handoff) remains achievable in
v1 as scoped — but only if the adapter honors the fallbacks and per-host
glyph/footer differences documented above rather than reusing the
so-MCP `_needs_input()` constants unmodified.
