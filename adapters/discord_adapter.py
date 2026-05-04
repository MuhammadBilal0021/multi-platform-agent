# =============================================================================
# adapters/discord_adapter.py  —  Discord Platform Adapter
# Translates Discord messages → AgentState → brain → Discord reply
# =============================================================================

import os
import sys
import time
import asyncio
import logging
import discord
from discord import app_commands
from dotenv import load_dotenv
from collections import defaultdict

# Add project root to path so 'core' module is found
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import run_brain
from core.state import AgentState
from core.memory import clear_history

load_dotenv()
TOKEN = os.environ.get("DISCORD_BOT_TOKEN")

if not TOKEN:
    print("ERROR: DISCORD_BOT_TOKEN is missing in .env")
    exit(1)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("omniagent.discord")

# Discord 2000 character hard limit per message
DISCORD_MAX_CHARS = 1990

# Rate limiting — max messages per user per window
RATE_LIMIT_MAX = 5          # max requests
RATE_LIMIT_WINDOW = 60      # per 60 seconds
user_rate_tracker: dict[str, list[float]] = defaultdict(list)


# =============================================================================
# HELPER — RATE LIMITER
# Prevents a single user from spamming the bot
# =============================================================================
def is_rate_limited(user_id: str) -> bool:
    """Check if a user has exceeded the rate limit."""
    now = time.time()
    # Remove timestamps outside the window
    user_rate_tracker[user_id] = [
        t for t in user_rate_tracker[user_id]
        if now - t < RATE_LIMIT_WINDOW
    ]
    # Check if they've hit the limit
    if len(user_rate_tracker[user_id]) >= RATE_LIMIT_MAX:
        return True
    # Record this request
    user_rate_tracker[user_id].append(now)
    return False


# =============================================================================
# HELPER — CHUNK LONG RESPONSES
# Discord rejects messages over 2000 chars with a silent 400 error
# This splits the response into multiple messages if needed
# =============================================================================
def chunk_message(text: str) -> list[str]:
    """Split text into Discord-safe chunks of max 1990 chars."""
    if len(text) <= DISCORD_MAX_CHARS:
        return [text]

    chunks = []
    while text:
        if len(text) <= DISCORD_MAX_CHARS:
            chunks.append(text)
            break
        # Try to break at a newline to avoid cutting mid-sentence
        split_at = text.rfind("\n", 0, DISCORD_MAX_CHARS)
        if split_at == -1:
            # No newline found — break at last space
            split_at = text.rfind(" ", 0, DISCORD_MAX_CHARS)
        if split_at == -1:
            # No space either — hard cut
            split_at = DISCORD_MAX_CHARS
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()

    return chunks


# =============================================================================
# HELPER — BUILD EMBED RESPONSE
# Rich, visually appealing Discord embeds instead of plain text
# =============================================================================
def build_response_embed(response_text: str, username: str) -> discord.Embed:
    """Create a polished Discord embed for the agent's response."""
    embed = discord.Embed(
        description=response_text[:4096],  # Embed description limit
        color=0x5865F2,  # Discord blurple
    )
    embed.set_footer(text=f"🧠 OmniAgent • Replying to {username}")
    return embed


# =============================================================================
# HELPER — INVOKE THE BRAIN
# Builds AgentState and calls run_brain() in a thread so Discord doesn't freeze
# =============================================================================
async def invoke_brain(
    user_id: str,
    username: str,
    message_text: str,
    metadata: dict,
) -> str:
    """Build AgentState, run brain in thread pool, return response text."""
    state: AgentState = {
        "channel":      "discord",
        "user_id":      user_id,
        "username":     username,
        "message":      message_text,
        "history":      [],   # run_brain() loads this from SQLite automatically
        "tool_results": [],
        "response":     "",
        "metadata":     metadata,
    }
    # Run synchronous brain in a thread pool — never block the event loop
    result = await asyncio.to_thread(run_brain, state)
    return result.get("response", "Sorry, I could not generate a response.")


# =============================================================================
# BOT SETUP — use commands.Bot so slash commands work
# =============================================================================
intents = discord.Intents.default()
intents.message_content = True

# CommandTree lets us register /reset and other slash commands
client = discord.Client(intents=intents)
tree   = app_commands.CommandTree(client)


# =============================================================================
# EVENT — ON READY
# =============================================================================
@client.event
async def on_ready():
    await tree.sync()  # register slash commands with Discord
    logger.info("Discord adapter online — logged in as %s (ID: %s)", client.user.name, client.user.id)
    logger.info("Serving in %d guilds", len(client.guilds))


# =============================================================================
# EVENT — ON MESSAGE
# Handles both server mentions and direct messages
# =============================================================================
@client.event
async def on_message(message: discord.Message):
    # Ignore the bot's own messages
    if message.author == client.user:
        return

    is_dm      = isinstance(message.channel, discord.DMChannel)
    is_mention = client.user.mentioned_in(message)

    # Respond in DMs (no mention needed) or when mentioned in a server
    if not (is_dm or is_mention):
        return

    # Strip the bot mention from the message text
    clean = message.clean_content.replace(f"@{client.user.name}", "").strip()
    if not clean:
        await message.reply("Hi! Mention me with a question and I'll help. Try `/help` to see what I can do.")
        return

    # Rate limiting check
    user_id = str(message.author.id)
    if is_rate_limited(user_id):
        logger.warning("Rate limited user %s (%s)", message.author.name, user_id)
        await message.reply(
            "⏳ You're sending messages too fast! Please wait a moment before trying again.",
            delete_after=10,  # auto-delete after 10 seconds
        )
        return

    logger.info("[%s] %s: %s", "DM" if is_dm else "Server", message.author.name, clean[:100])

    # Pass platform-specific extras into metadata
    metadata = {
        "guild_id":   str(message.guild.id) if message.guild else "dm",
        "channel_id": str(message.channel.id),
        "message_id": str(message.id),
        "is_dm":      is_dm,
    }

    async with message.channel.typing():
        try:
            response_text = await invoke_brain(
                user_id=user_id,
                username=message.author.name,
                message_text=clean,
                metadata=metadata,
            )
        except Exception as e:
            logger.error("Brain error for %s: %s", message.author.name, e)
            response_text = "⚠️ Something went wrong while processing your request. Please try again."

    # Use embeds for server messages, plain text for DMs (more natural)
    if is_dm:
        chunks = chunk_message(response_text)
        for i, chunk in enumerate(chunks):
            if i == 0:
                await message.reply(chunk)
            else:
                await message.channel.send(chunk)
    else:
        # Server messages get rich embeds
        if len(response_text) <= 4096:
            embed = build_response_embed(response_text, message.author.name)
            await message.reply(embed=embed)
        else:
            # Too long for a single embed — fall back to chunked text
            chunks = chunk_message(response_text)
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await message.reply(chunk)
                else:
                    await message.channel.send(chunk)

    logger.info("Replied to %s (%d chars)", message.author.name, len(response_text))


# =============================================================================
# SLASH COMMAND — /help
# Shows what the bot can do
# =============================================================================
@tree.command(name="help", description="See what OmniAgent can do")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🧠 OmniAgent — Help",
        description="I'm your AI assistant powered by LangGraph. Here's what I can do:",
        color=0x5865F2,
    )
    embed.add_field(
        name="💬 Chat",
        value="Mention me or DM me with any question and I'll respond.",
        inline=False,
    )
    embed.add_field(
        name="🔍 Web Search",
        value="Ask me about recent news, events, or anything I need to look up online.",
        inline=False,
    )
    embed.add_field(
        name="🕐 Time & Date",
        value="Ask me what time it is in any timezone (e.g., 'What time is it in Tokyo?').",
        inline=False,
    )
    embed.add_field(
        name="🔗 Summarize Links",
        value="Share a URL and ask me to summarize it.",
        inline=False,
    )
    embed.add_field(
        name="🗑️ Commands",
        value="`/reset` — Clear our conversation memory\n`/help` — Show this message",
        inline=False,
    )
    embed.set_footer(text="OmniAgent v1.0 • Powered by LangGraph + OpenRouter")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =============================================================================
# SLASH COMMAND — /reset
# Clears the user's conversation memory for Discord
# =============================================================================
@tree.command(name="reset", description="Clear your conversation memory with the bot")
async def reset_command(interaction: discord.Interaction):
    clear_history(
        user_id=str(interaction.user.id),
        channel="discord",
    )
    await interaction.response.send_message(
        "✅ Memory cleared. I've forgotten our previous conversation — let's start fresh!",
        ephemeral=True,   # only visible to the user who ran /reset
    )
    logger.info("Memory cleared for %s", interaction.user.name)


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    logger.info("Booting Discord adapter...")
    client.run(TOKEN)