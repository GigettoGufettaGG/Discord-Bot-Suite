import asyncio
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Modal, TextInput, View


class TicketRequestModal(Modal):
    def __init__(self, cog: "Tickets", role_id: int, role_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cog = cog
        self.role_id = role_id
        self.role_name = role_name

    async def on_submit(self, interaction: discord.Interaction):
        answers = "\n".join(f"{child.label}: {child.value}" for child in self.children)
        guild_cfg = self.cog.config.get(interaction.guild_id)
        if guild_cfg is None:
            await interaction.response.send_message("Prima configura /setup-ticket.", ephemeral=True)
            return

        category = interaction.guild.get_channel(guild_cfg.get("category_id")) if guild_cfg.get("category_id") else None
        if category is None:
            category = interaction.channel

        role = interaction.guild.get_role(self.role_id)
        ticket_channel = await interaction.guild.create_text_channel(
            name=f"ticket-{interaction.user.name.lower()}",
            category=category,
            reason=f"Ticket aperto da {interaction.user.display_name}",
        )

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        await ticket_channel.edit(overwrites=overwrites)
        await ticket_channel.send(f"{interaction.user.mention} {role.mention if role else ''}\n\n{answers}")

        self.cog.open_tickets.setdefault(interaction.guild_id, {})
        self.cog.open_tickets[interaction.guild_id][ticket_channel.id] = {
            "user_id": interaction.user.id,
            "staff_role_id": self.role_id,
            "created_at": __import__('datetime').datetime.utcnow(),
            "claimed_by": None,
        }

        transcript_channel = interaction.guild.get_channel(guild_cfg.get("transcript_channel_id")) if guild_cfg.get("transcript_channel_id") else None
        if transcript_channel:
            await transcript_channel.send(f"Nuovo ticket: {ticket_channel.mention} aperto da {interaction.user.mention} ({self.role_name})")

        await interaction.response.send_message(f"Ticket creato: {ticket_channel.mention}", ephemeral=True)


class TicketButton(Button):
    def __init__(self, cog: "Tickets", label: str, role_id: int, questions: List[str]):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.cog = cog
        self.role_id = role_id
        self.questions = questions

    async def callback(self, interaction: discord.Interaction):
        modal = TicketRequestModal(self.cog, self.role_id, self.label, title=f"Compila: {self.label}")
        for question in self.questions:
            modal.add_item(TextInput(label=question, required=True, style=discord.TextStyle.short))
        await interaction.response.send_modal(modal)


class CloseTicketView(View):
    def __init__(self, cog: "Tickets", channel: discord.TextChannel, reason: str, requester: discord.Member):
        super().__init__(timeout=None)
        self.cog = cog
        self.channel = channel
        self.reason = reason
        self.requester = requester

    @discord.ui.button(label="Chiudi", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: Button):
        transcript_channel = self.cog.config.get(interaction.guild_id, {}).get("transcript_channel_id")
        if transcript_channel:
            transcript = interaction.guild.get_channel(transcript_channel)
            if transcript:
                await transcript.send(f"Ticket chiuso: {self.channel.mention}\nMotivo: {self.reason}\nRichiesto da {self.requester.mention}")
        await self.channel.send(f"Ticket chiuso per motivo: {self.reason}")
        await interaction.response.send_message("Ticket chiuso.", ephemeral=True)

    @discord.ui.button(label="Non chiudere", style=discord.ButtonStyle.secondary)
    async def keep_open(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("Ticket mantenuto aperto.", ephemeral=True)


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config: Dict[int, Dict[str, Any]] = {}
        self.open_tickets: Dict[int, Dict[int, Dict[str, Any]]] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        print("Tickets cog ready.")

    @app_commands.command(name="setup-ticket", description="Configura il sistema ticket")
    @app_commands.describe(
        message="Messaggio principale del sistema",
        category="Categoria dove creare i ticket",
        transcript_channel="Canale transcript",
    )
    async def setup_ticket(
        self,
        interaction: discord.Interaction,
        message: str,
        category: Optional[discord.CategoryChannel] = None,
        transcript_channel: Optional[discord.TextChannel] = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return

        self.config[interaction.guild_id] = {
            "message": message,
            "category_id": category.id if category else None,
            "transcript_channel_id": transcript_channel.id if transcript_channel else None,
            "button_roles": {},
            "button_message_id": None,
        }
        await interaction.response.send_message(f"Sistema ticket configurato.\nMessaggio: {message}", ephemeral=True)

    @app_commands.command(name="ticket-role", description="Collega un ruolo a un bottone ticket")
    @app_commands.describe(
        button_name="Nome del bottone",
        role="Ruolo staff",
        questions="Domande separate da |",
    )
    async def ticket_role(self, interaction: discord.Interaction, button_name: str, role: discord.Role, questions: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return

        guild_cfg = self.config.setdefault(interaction.guild_id, {
            "message": "Ticket aperto",
            "category_id": None,
            "transcript_channel_id": None,
            "button_roles": {},
            "button_message_id": None,
        })
        guild_cfg["button_roles"][button_name] = {
            "role_id": role.id,
            "questions": [q.strip() for q in questions.split("|") if q.strip()],
        }
        await interaction.response.send_message(f"Bottone `{button_name}` collegato al ruolo {role.mention}.", ephemeral=True)

    @app_commands.command(name="ticket-send", description="Pubblica il messaggio con i bottoni ticket")
    @app_commands.describe(channel="Canale dove inviare il messaggio")
    async def ticket_send(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return

        guild_cfg = self.config.get(interaction.guild_id)
        if guild_cfg is None:
            await interaction.response.send_message("Prima configuri /setup-ticket.", ephemeral=True)
            return

        view = View(timeout=None)
        for name, data in guild_cfg["button_roles"].items():
            view.add_item(TicketButton(self, name, data["role_id"], data["questions"]))

        message = await channel.send(guild_cfg["message"], view=view)
        guild_cfg["button_message_id"] = message.id
        await interaction.response.send_message(f"Messaggio ticket inviato in {channel.mention}.", ephemeral=True)

    @app_commands.command(name="claim-ticket", description="Reclama un ticket")
    @app_commands.describe(channel="Canale del ticket")
    async def claim_ticket(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return
        self.open_tickets.setdefault(interaction.guild_id, {})
        ticket = self.open_tickets[interaction.guild_id].get(channel.id)
        if not ticket:
            await interaction.response.send_message("Ticket non trovato.", ephemeral=True)
            return
        ticket["claimed_by"] = interaction.user.id
        await interaction.response.send_message(f"Ticket {channel.mention} reclamato da {interaction.user.mention}.", ephemeral=True)

    @app_commands.command(name="transfer-ticket", description="Trasferisce un ticket ad un altro staff")
    @app_commands.describe(channel="Canale del ticket", member="Staff destinatario")
    async def transfer_ticket(self, interaction: discord.Interaction, channel: discord.TextChannel, member: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return
        self.open_tickets.setdefault(interaction.guild_id, {})
        ticket = self.open_tickets[interaction.guild_id].get(channel.id)
        if not ticket:
            await interaction.response.send_message("Ticket non trovato.", ephemeral=True)
            return
        ticket["claimed_by"] = member.id
        await interaction.response.send_message(f"Ticket trasferito a {member.mention}.", ephemeral=True)

    @app_commands.command(name="close-ticket", description="Chiude un ticket con motivo")
    @app_commands.describe(channel="Canale del ticket", reason="Motivo della chiusura")
    async def close_ticket(self, interaction: discord.Interaction, channel: discord.TextChannel, reason: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return
        view = CloseTicketView(self, channel, reason, interaction.user)
        await interaction.response.send_message(f"Conferma la chiusura del ticket {channel.mention}?", view=view, ephemeral=True)

    @app_commands.command(name="ticket-inactive", description="Marca un ticket come inattivo")
    @app_commands.describe(channel="Canale del ticket")
    async def ticket_inactive(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return

        async def auto_close_after_delay():
            await asyncio.sleep(60 * 60 * 24)
            await channel.send(f"Ticket {channel.mention} chiuso automaticamente per inattività.")

        asyncio.create_task(auto_close_after_delay())
        await interaction.response.send_message(f"Controllo inattività avviato per {channel.mention}.", ephemeral=True)

    @app_commands.command(name="temp-role", description="Crea un ruolo temporaneo per un utente")
    @app_commands.describe(member="Utente", name="Nome ruolo", duration_minutes="Durata in minuti", color="Colore esadecimale")
    async def temp_role(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        name: str,
        duration_minutes: int = 60,
        color: str = "00FF00",
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return

        role = await interaction.guild.create_role(name=name, colour=discord.Colour(int(color, 16)))
        await member.add_roles(role)

        async def remove_role():
            await asyncio.sleep(duration_minutes * 60)
            if role in member.roles:
                await member.remove_roles(role)
                await interaction.channel.send(f"Ruolo temporaneo `{name}` rimosso da {member.mention}.")

        asyncio.create_task(remove_role())
        await interaction.response.send_message(f"Ruolo temporaneo `{name}` assegnato a {member.mention} per {duration_minutes} minuti.", ephemeral=True)

    @app_commands.command(name="temp-channel", description="Crea un canale temporaneo")
    @app_commands.describe(name="Nome del canale", duration_minutes="Durata in minuti")
    async def temp_channel(self, interaction: discord.Interaction, name: str, duration_minutes: int = 60):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return

        channel = await interaction.guild.create_text_channel(name=name)

        async def delete_channel():
            await asyncio.sleep(duration_minutes * 60)
            await channel.delete(reason="Canale temporaneo scaduto")

        asyncio.create_task(delete_channel())
        await interaction.response.send_message(f"Canale temporaneo creato: {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
