"""
discord_relay.py — Discord question relay.

C4 of the Hermes orchestrator. Connects to Discord via bot token,
relays halted-session questions to zeke via DM, deduplicates across
sessions, receives answers (reaction emoji or text), and writes
hermes-resolve.json.

Gracefully degrades if discord.py is not installed.
"""

from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hermes.schema import write_resolve_json, ResolveAnswer
from hermes.config import HermesConfig

try:
    import discord
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False


# ---------------------------------------------------------------------------
# In-flight question tracking (for dedup)
# ---------------------------------------------------------------------------

class InFlightQuestion:
    """Tracks a question sent to the user, awaiting answer."""
    
    def __init__(self, message_id: int, halt_reason: str, halt_description: str):
        self.message_id = message_id
        self.halt_reason = halt_reason
        self.halt_description = halt_description
        self.workstreams: list[str] = []
        self.answer: Optional[str] = None
        self.answered = asyncio.Event()


# In-memory store (single process, single user)
_inflight: dict[str, InFlightQuestion] = {}  # keyed by dedup key


def _dedup_key(reason: str, description: str) -> str:
    """Generate dedup key from halt reason + description."""
    return f"{reason}::{description}"

def is_so_prefix(content: str) -> bool:
    stripped = content.lstrip().lower()
    return stripped == "so" or stripped.startswith("so ")


def so_entry_prompt(raw_message: str) -> str:
    return (
        "User wants to orchestrate an agent session from Discord. "
        "Parse the host, project, task, and optional z-command naturally, "
        "then call the Hermes so MCP tools directly. Raw message: "
        f"{raw_message}"
    )


def _id_allowed(value: str, allowed_values: set[str]) -> bool:
    return not allowed_values or value in allowed_values






# ---------------------------------------------------------------------------
# Discord client (T001)
# ---------------------------------------------------------------------------

class HermesDiscordClient(discord.Client if DISCORD_AVAILABLE else object):
    """Discord bot client for Hermes question relay."""
    
    def __init__(self, config: HermesConfig):
        if not DISCORD_AVAILABLE:
            raise RuntimeError("discord.py not installed")
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        super().__init__(intents=intents)
        self.config = config
        self.target_user: Optional[discord.User] = None
        self._ready = asyncio.Event()
        self.so_sessions_by_thread: dict[str, tuple[str, str]] = {}
        self._so_signal_task: Optional[asyncio.Task] = None
    
    async def on_ready(self):
        """Fetch target user on connect."""
        print(f"  Discord: connected as {self.user}")
        try:
            user_id = int(self.config.discord.user_id)
            self.target_user = await self.fetch_user(user_id)
            print(f"  Discord: target user {self.target_user.name}")
        except Exception as e:
            print(f"  Discord: WARNING — could not fetch user: {e}")
        if self._so_signal_task is None or self._so_signal_task.done():
            self._so_signal_task = asyncio.create_task(self._poll_so_signals())
        self._ready.set()
    
    async def close(self):
        if self._so_signal_task is not None:
            self._so_signal_task.cancel()
        await super().close()
    
    async def _poll_so_signals(self):
        """Route MCP session signals back into Discord without pane polling."""
        from hermes.mcp_hermes_orchestrator import drain_signal_events

        while not self.is_closed():
            try:
                for event in drain_signal_events(self.config):
                    await self._route_so_signal(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"  Discord: WARNING — so signal routing failed: {exc}")
            await asyncio.sleep(10)
    
    async def _route_so_signal(self, event: dict):
        target = event.get("discord_thread_id") or event.get("discord_channel_id")
        if not target:
            return
        try:
            channel = await self.fetch_channel(int(target))
        except Exception as exc:
            print(f"  Discord: WARNING — could not fetch so target {target}: {exc}")
            return
        session_id = event.get("session_id", "unknown")
        text = str(event.get("text", "")).strip()
        if len(text) > 1800:
            text = text[-1800:]
        await channel.send(
            f"Hermes MCP session `{session_id}` needs attention.\n\n{text}"
        )
    
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        """Handle reaction-based answers."""
        if user.bot:
            return
        
        msg_id = reaction.message.id
        for key, q in _inflight.items():
            if q.message_id == msg_id and q.answer is None:
                # Map emoji to option index
                emoji_map = {"1️⃣": 0, "2️⃣": 1, "3️⃣": 2, "4️⃣": 3}
                idx = emoji_map.get(str(reaction.emoji))
                if idx is not None:
                    q.answer = str(idx + 1)  # 1-indexed options
                    q.answered.set()
                    print(f"  Discord: answer received for {key}: option {q.answer}")
    
    async def _route_so_entry(self, message: discord.Message, prompt: str):
        """Hook for the Hermes gateway to receive raw `so` text as an LLM prompt."""
        print(f"  Discord: so entry routed to Hermes LLM: {prompt}")


    def _so_authorized(self, message: discord.Message) -> bool:
        so_config = self.config.discord.so
        user_id = str(getattr(message.author, "id", ""))
        channel_id = str(getattr(message.channel, "id", ""))
        return _id_allowed(user_id, so_config.allowed_user_ids) and _id_allowed(
            channel_id,
            so_config.allowed_channel_ids,
        )


    async def on_message(self, message: discord.Message):
        """Detect `so` prefix and hand raw text to Hermes; never parse the task."""
        if getattr(message.author, "bot", False):
            return
        raw = str(getattr(message, "content", ""))
        if not is_so_prefix(raw):
            return
        if not self._so_authorized(message):
            try:
                await message.channel.send("Not authorized to use Hermes `so` here.")
            except Exception as exc:
                print(f"  Discord: WARNING — could not send so auth failure: {exc}")
            return
        await self._route_so_entry(message, so_entry_prompt(raw))
    
    async def wait_ready(self, timeout: float = 30):
        """Wait for client to be ready."""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            print("  Discord: WARNING — timed out waiting for ready")


# ---------------------------------------------------------------------------
# Connect / disconnect
# ---------------------------------------------------------------------------

_client: Optional[HermesDiscordClient] = None


async def connect(config: HermesConfig) -> None:
    """Connect Discord client. Call once at orchestrator start."""
    global _client
    
    if not DISCORD_AVAILABLE:
        print("  Discord: discord.py not installed — question relay disabled")
        return
    
    if not config.discord.bot_token:
        print("  Discord: no bot token configured — question relay disabled")
        return
    
    _client = HermesDiscordClient(config)
    # Start client in background
    asyncio.create_task(_client.start(config.discord.bot_token))
    await _client.wait_ready()


async def disconnect() -> None:
    """Disconnect Discord client."""
    global _client
    if _client and DISCORD_AVAILABLE:
        await _client.close()
        _client = None
        print("  Discord: disconnected")


# ---------------------------------------------------------------------------
# Question relay (T002 + T003)
# ---------------------------------------------------------------------------

async def relay_halt(
    ws_id: str,
    reason: str,
    description: str,
    timeout_minutes: int = 30,
) -> Optional[str]:
    """Relay a halted-session question via Discord with dedup.
    
    Returns the user's answer string, or None on timeout/error.
    """
    global _client, _inflight
    
    if not DISCORD_AVAILABLE or _client is None or _client.target_user is None:
        print(f"  [NO-DISCORD] Would relay halt for {ws_id}: {reason}")
        return None
    
    # Dedup check
    key = _dedup_key(reason, description)
    
    if key in _inflight and _inflight[key].answer is None:
        # Add this workstream to existing question
        _inflight[key].workstreams.append(ws_id)
        print(f"  Discord: dedup — added {ws_id} to existing question {key}")
        await _inflight[key].answered.wait()
        return _inflight[key].answer
    elif key in _inflight and _inflight[key].answer is not None:
        # Already answered — reuse
        return _inflight[key].answer
    
    # Format question
    ws_list = ", ".join([ws_id])
    embed = discord.Embed(
        title=f"🔴 Hermes: Session {ws_list} halted",
        description=description or "(no description)",
        color=0xFF0000,
    )
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Workstream", value=ws_id, inline=True)
    
    # Default options based on halt reason
    options = _default_options(reason)
    options_text = "\n".join(f"{i+1}️⃣ {opt}" for i, opt in enumerate(options))
    embed.add_field(name="Options", value=options_text, inline=False)
    
    # Send
    try:
        message = await _client.target_user.send(embed=embed)
        # Add reaction emojis
        emoji_map = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
        for i in range(len(options)):
            await message.add_reaction(emoji_map[i])
        
        # Track in-flight
        q = InFlightQuestion(message.id, reason, description)
        q.workstreams.append(ws_id)
        _inflight[key] = q
        
        print(f"  Discord: sent question for {ws_id} (msg_id={message.id})")
        
        # Wait for answer
        try:
            await asyncio.wait_for(q.answered.wait(), timeout=timeout_minutes * 60)
            answer = q.answer
            # Write hermes-resolve.json for all affected workstreams
            if answer:
                for wid in q.workstreams:
                    # resolve path is relative to worktree — caller handles writing
                    pass
            return answer
        except asyncio.TimeoutError:
            print(f"  Discord: timeout waiting for answer to {key}")
            # Re-send once
            await _client.target_user.send(
                f"⏰ Reminder: still waiting for your answer to the question above."
            )
            try:
                await asyncio.wait_for(q.answered.wait(), timeout=timeout_minutes * 60)
                return q.answer
            except asyncio.TimeoutError:
                print(f"  Discord: second timeout — aborting question {key}")
                return None
        finally:
            del _inflight[key]
    
    except Exception as e:
        print(f"  Discord: error sending question: {e}")
        return None


async def relay_merge_conflict(
    file: str,
    workstreams: list[str],
    diff: str,
) -> Optional[str]:
    """Relay a merge conflict via Discord.
    
    Returns the resolution strategy string, or None on error.
    """
    global _client
    
    if not DISCORD_AVAILABLE or _client is None or _client.target_user is None:
        print(f"  [NO-DISCORD] Would relay merge conflict: {file}")
        return None
    
    ws_list = ", ".join(workstreams)
    
    embed = discord.Embed(
        title=f"⚠️ Hermes: Merge conflict",
        description=f"**File:** `{file}`\n**Workstreams:** {ws_list}",
        color=0xFFA500,
    )
    
    # Truncate diff to fit Discord limits
    diff_preview = diff[:1800] + ("..." if len(diff) > 1800 else "")
    embed.add_field(
        name="Diff",
        value=f"```diff\n{diff_preview}\n```",
        inline=False,
    )
    
    options = [
        "Resolve manually",
        "Spawn resolution session",
        "Skip workstream",
        "Abort plan",
    ]
    options_text = "\n".join(f"{i+1}️⃣ {opt}" for i, opt in enumerate(options))
    embed.add_field(name="Options", value=options_text, inline=False)
    
    try:
        message = await _client.target_user.send(embed=embed)
        for i in range(len(options)):
            await message.add_reaction(["1️⃣", "2️⃣", "3️⃣", "4️⃣"][i])
        
        # Wait for answer
        q_key = f"merge::{file}"
        q = InFlightQuestion(message.id, "merge_conflict", file)
        q.workstreams = workstreams
        _inflight[q_key] = q
        
        try:
            await asyncio.wait_for(q.answered.wait(), timeout=3600)  # 1 hour for merge
            return q.answer
        except asyncio.TimeoutError:
            return None
        finally:
            del _inflight[q_key]
    
    except Exception as e:
        print(f"  Discord: error sending merge conflict: {e}")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_options(reason: str) -> list[str]:
    """Return default options based on halt reason."""
    if reason == "decision_needed":
        return ["Option A", "Option B", "Option C"]
    elif reason == "spec_problem":
        return ["Update SPEC.md", "Proceed anyway", "Skip this task"]
    elif reason == "needs_clarification":
        return ["Answer below", "Defer to later"]
    else:
        return ["Proceed", "Skip", "Abort"]
