import re
import discord
from discord.ext import commands
from discord import app_commands

HARDCODED_SECONDARY_HEADER = "List of active wisps"

DEFAULT_ROLE_EMOJIS = [
    "1️⃣",
    "2️⃣",
    "3️⃣",
    "4️⃣",
    "5️⃣",
    "6️⃣",
    "7️⃣",
    "8️⃣",
    "9️⃣",
    "🔟",
]

watching_sessions = {}


def build_secondary_content(guild: discord.Guild, session: dict) -> str:
    """creates the list for active roles n stuff"""
    sections = []
    if HARDCODED_SECONDARY_HEADER:
      sections.append(HARDCODED_SECONDARY_HEADER)

    for emoji, role_id in session["emoji_to_role_id"].items():
      role = guild.get_role(role_id)
      role_label = role.name if role else f"Role ({role_id})"
      active_users = session["role_lists"].get(role_id, {})

      lines = [f"list of currently active {role_label}:"]
      if active_users:
        for username in active_users.values():
          lines.append(f"- {username}")
      else:
        lines.append("- None")

      sections.append("\n".join(lines))

    return "\n\n".join(sections)

class Client(commands.Bot):
    async def on_ready(self):
      print(f'Logged on as {self.user}!')

      try:
        guild = discord.Object(id=)
        synced = await self.tree.sync(guild=guild)
        print(f'Synced {len(synced)} commands to guild {guild.id}')

      except Exception as e:
          print(f'Error syncing commands: {e}')

    async def on_message(self, message):
     if message.author == self.user:
       return
     await self.process_commands(message)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
      if payload.user_id == self.user.id:
        return

      session = watching_sessions.get(payload.message_id)
      if not session:
       return

      emoji_str = str(payload.emoji)
      role_id = session["emoji_to_role_id"].get(emoji_str)
      if not role_id:
        return

      guild = self.get_guild(payload.guild_id)
      if not guild:
        return

      role = guild.get_role(role_id)
      member = guild.get_member(payload.user_id)
      if not member:
        try:
          member = await guild.fetch_member(payload.user_id)
        except discord.HTTPException:
          return

      if role and member:
        try:
          await member.add_roles(role, reason="Reacted on /startwatching board")
        except discord.Forbidden:
          print(
            "Missing permissions or role hierarchy issue adding role"
            f" {role.name}"
        )

      if member:
        user_map = session["role_lists"].setdefault(role_id, {})
        user_map[payload.user_id] = member.display_name

      sec_channel = guild.get_channel(session["secondary_channel_id"])
      if sec_channel:
        try:
          sec_msg = await sec_channel.fetch_message(session["secondary_msg_id"])
          await sec_msg.edit(content=build_secondary_content(guild, session))
        except discord.HTTPException as e:
          print(f"Failed to edit secondary message: {e}")

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
      if payload.user_id == self.user.id:
        return

      session = watching_sessions.get(payload.message_id)
      if not session:
        return

      emoji_str = str(payload.emoji)
      role_id = session["emoji_to_role_id"].get(emoji_str)
      if not role_id:
        return

      guild = self.get_guild(payload.guild_id)
      if not guild:
        return

      role = guild.get_role(role_id)
      member = guild.get_member(payload.user_id)
      if not member:
        try:
          member = await guild.fetch_member(payload.user_id)
        except discord.HTTPException:
          member = None

      if role and member:
        try:
         await member.remove_roles(
            role, reason="Removed reaction on /startwatching board"
        )
        except discord.Forbidden:
          print(
            "Missing permissions or role hierarchy issue removing role"
            f" {role.name}"
          )

      user_map = session["role_lists"].get(role_id, {})
      user_map.pop(payload.user_id, None)

      sec_channel = guild.get_channel(session["secondary_channel_id"])
      if sec_channel:
        try:
          sec_msg = await sec_channel.fetch_message(session["secondary_msg_id"])
          await sec_msg.edit(content=build_secondary_content(guild, session))
        except discord.HTTPException as e:
          print(f"Failed to edit secondary message: {e}")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True
client = Client(command_prefix="!", intents=intents)

GUILD_ID = discord.Object(id=)

@client.tree.command(
    name="startwatching",
    description=(
        "Post a primary signup message and a live secondary role list"
    ),
    guild=GUILD_ID,
)
@app_commands.describe(
    primary_channel="Channel where the reaction message will be posted",
    secondary_channel="Channel where the live bulleted role lists will appear",
    primary_message="Message content for the primary channel",
    roles="Comma-separated @roles, e.g. @RoleA, @RoleB, @RoleC",
)
async def startwatching(
    interaction: discord.Interaction,
    primary_channel: discord.TextChannel,
    secondary_channel: discord.TextChannel,
    primary_message: str,
    roles: str,
):
  if not interaction.guild:
    await interaction.response.send_message(
        "This command can only be used in a server.", ephemeral=True
    )
    return


  raw_parts = [part.strip() for part in roles.split(",") if part.strip()]
  parsed_roles: list[discord.Role] = []

  for part in raw_parts:
    match = re.fullmatch(r"<@&(\d+)>", part)
    if not match:
      await interaction.response.send_message(
          f"Could not parse `{part}` as a role mention. Separate @roles with"
          " commas, like `@Role1, @Role2`.",
          ephemeral=True,
      )
      return
    role = interaction.guild.get_role(int(match.group(1)))
    if not role:
      await interaction.response.send_message(
          f"Role with ID `{match.group(1)}` wasn't found in this server.",
          ephemeral=True,
      )
      return
    parsed_roles.append(role)

  if not parsed_roles:
    await interaction.response.send_message(
        "Please provide at least one `@role`.", ephemeral=True
    )
    return

  if len(parsed_roles) > len(DEFAULT_ROLE_EMOJIS):
    await interaction.response.send_message(
        f"You can pass up to {len(DEFAULT_ROLE_EMOJIS)} roles at a time.",
        ephemeral=True,
    )
    return

  await interaction.response.defer(ephemeral=True)

  emoji_to_role_id: dict[str, int] = {}
  role_lists: dict[int, dict[int, str]] = {}
  legend_lines = []

  for idx, role in enumerate(parsed_roles):
    emoji = DEFAULT_ROLE_EMOJIS[idx]
    emoji_to_role_id[emoji] = role.id
    role_lists[role.id] = {}
    legend_lines.append(f"{emoji} → {role.mention}")

  full_primary_text = f"{primary_message}\n\n" + "\n".join(legend_lines)

  session_stub = {
      "primary_channel_id": primary_channel.id,
      "secondary_channel_id": secondary_channel.id,
      "secondary_msg_id": 0,
      "emoji_to_role_id": emoji_to_role_id,
      "role_lists": role_lists,
  }

  secondary_msg = await secondary_channel.send(
      build_secondary_content(interaction.guild, session_stub)
  )
  primary_msg = await primary_channel.send(full_primary_text)

  for emoji in emoji_to_role_id:
    await primary_msg.add_reaction(emoji)

  session_stub["secondary_msg_id"] = secondary_msg.id
  watching_sessions[primary_msg.id] = session_stub

  await interaction.followup.send(
      f"Started watching in {primary_channel.mention} and updating"
      f" {secondary_channel.mention}.",
      ephemeral=True,
  )


@client.tree.command(name="print", description="Say words you want but from me instead", guild=GUILD_ID)
async def printer(interaction: discord.Interaction, printer: str):
  await interaction.response.send_message(printer)




client.run('')