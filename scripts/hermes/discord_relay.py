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
from dataclasses import dataclass
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hermes.schema import write_resolve_json, ResolveAnswer
from hermes.config import DiscordProjectAlias, HermesConfig

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

# ---------------------------------------------------------------------------
# Discord `so` command parsing (Hermes session orchestration)
# ---------------------------------------------------------------------------

_Z_COMMAND_RE = re.compile(r"^(?P<task>.+)\s+using\s+(?P<z_command>[A-Za-z0-9._/-]+)$")


@dataclass(frozen=True)
class SoCommand:
    host: str
    project: str
    project_alias: DiscordProjectAlias
    task: str
    z_command: Optional[str]
    requester_user_id: str
    discord_channel_id: str
    discord_message_id: str
    discord_thread_id: str = ""


class SoCommandError(ValueError):
    """Discord-visible command intake error."""


def parse_so_command(
    content: str,
    *,
    requester_user_id: str,
    channel_id: str,
    message_id: str,
    config: HermesConfig,
    thread_id: str = "",
) -> SoCommand:
    """Parse and authorize `so <host> <project> <task...> [using <z-command>]`."""
    parts = content.strip().split(maxsplit=3)
    if len(parts) < 4 or parts[0] != "so":
        raise SoCommandError(
            "Usage: so <host> <project> <task...> [using <z-command>]"
        )

    requester_user_id = str(requester_user_id)
    channel_id = str(channel_id)
    message_id = str(message_id)
    thread_id = str(thread_id or "")
    so_config = config.discord.so

    allowed_users = set(so_config.allowed_user_ids)
    if config.discord.user_id:
        allowed_users.add(str(config.discord.user_id))
    if requester_user_id not in allowed_users:
        raise SoCommandError("You are not authorized to start Hermes sessions.")

    if so_config.allowed_channel_ids and channel_id not in so_config.allowed_channel_ids:
        raise SoCommandError("This Discord channel is not authorized for Hermes sessions.")

    _, host, project, task_part = parts
    if so_config.allowed_hosts and host not in so_config.allowed_hosts:
        raise SoCommandError(f"Unknown Hermes host: {host}")
    if project not in so_config.project_aliases:
        raise SoCommandError(f"Unknown Hermes project: {project}")

    task_text = task_part.strip()
    z_command: Optional[str] = None
    match = _Z_COMMAND_RE.match(task_text)
    if match:
        task_text = match.group("task").strip()
        z_command = match.group("z_command")
    if not task_text:
        raise SoCommandError("Task text is required.")

    return SoCommand(
        host=host,
        project=project,
        project_alias=so_config.project_aliases[project],
        task=task_text,
        z_command=z_command,
        requester_user_id=requester_user_id,
        discord_channel_id=channel_id,
        discord_message_id=message_id,
        discord_thread_id=thread_id,
    )

def launch_accepted_so_command(command: SoCommand, config: HermesConfig):
    """Launch an accepted Discord `so` command through the MCP orchestrator."""
    from hermes.mcp_hermes_orchestrator import start_so_session

    return start_so_session(command, config)


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
    
    async def on_ready(self):
        """Fetch target user on connect."""
        print(f"  Discord: connected as {self.user}")
        try:
            user_id = int(self.config.discord.user_id)
            self.target_user = await self.fetch_user(user_id)
            print(f"  Discord: target user {self.target_user.name}")
        except Exception as e:
            print(f"  Discord: WARNING — could not fetch user: {e}")
        self._ready.set()
    
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
    
    async def on_message(self, message: discord.Message):
        """Handle text answers and inbound `so` commands."""
        if message.author.bot:
            return

        if message.content.strip().startswith("so "):
            try:
                command = parse_so_command(
                    message.content,
                    requester_user_id=str(message.author.id),
                    channel_id=str(message.channel.id),
                    message_id=str(message.id),
                    config=self.config,
                )
            except SoCommandError as exc:
                await message.channel.send(str(exc))
                return
            try:
                session = launch_accepted_so_command(command, self.config)
            except Exception as exc:
                await message.channel.send(
                    f"Failed to launch Hermes session: {exc}"
                )
                return
            key = str(command.discord_thread_id or command.discord_channel_id)
            self.so_sessions_by_thread[key] = (
                session.session_id,
                command.requester_user_id,
            )
            await message.channel.send(
                f"Started Hermes MCP session `{session.session_id}` "
                f"for `{command.project}`: {command.task}"
            )
            return
        
        key = str(message.channel.id)
        session_info = self.so_sessions_by_thread.get(key)
        if session_info and session_info[1] == str(message.author.id):
            from hermes.mcp_hermes_orchestrator import send_to_so_session

            session_id = session_info[0]
            try:
                response = send_to_so_session(
                    session_id,
                    message.content.strip(),
                    self.config,
                )
            except Exception as exc:
                await message.channel.send(f"Failed to send to `{session_id}`: {exc}")
                return
            await message.channel.send(
                f"Sent to Hermes MCP session `{response.session_id}`."
            )
            return

        # Check if this is a DM reply to a question
        # We don't track reply chains explicitly; accept any DM from target
        if (isinstance(message.channel, discord.DMChannel) and 
            str(message.author.id) == self.config.discord.user_id):
            # Find an unanswered question and accept this as the answer
            for key, q in _inflight.items():
                if q.answer is None:
                    q.answer = message.content.strip()
                    q.answered.set()
                    print(f"  Discord: text answer for {key}: {q.answer}")
                    break
    
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
