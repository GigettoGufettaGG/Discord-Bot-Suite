import datetime as dt
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Modal, TextInput, View


class PartnershipRequestModal(Modal):
    def __init__(self, cog: "Partnership", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cog = cog

    server_name = TextInput(label="Nome del server", required=True, max_length=100)
    server_link = TextInput(label="Link del server", required=True, max_length=300)
    description = TextInput(label="Descrizione", required=True, style=discord.TextStyle.paragraph, max_length=1500)
    members = TextInput(label="Numero membri", required=True, max_length=50)
    tos = TextInput(label="Rispetta i ToS di Discord? (si/no)", required=True, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = self.cog.config.get(interaction.guild_id)
        if cfg is None:
            await interaction.response.send_message("Prima configura /setup-partnership.", ephemeral=True)
            return

        log_channel = interaction.guild.get_channel(cfg.get("log_channel_id"))
        if log_channel is None:
            await interaction.response.send_message("Canale log non trovato.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Richiesta partnership",
            description=(
                f"**Nome server:** {self.server_name.value}\n"
                f"**Link:** {self.server_link.value}\n"
                f"**Membri:** {self.members.value}\n"
                f"**ToS Discord:** {self.tos.value}\n\n"
                f"{self.description.value}"
            ),
            color=discord.Color.blurple(),
        )
        view = PartnerDecisionView(self.cog, interaction.user, self.server_name.value, self.server_link.value)
        message = await log_channel.send(embed=embed, view=view)
        self.cog.pending[interaction.guild_id].append({
            "message_id": message.id,
            "user_id": interaction.user.id,
            "server_name": self.server_name.value,
            "server_link": self.server_link.value,
            "description": self.description.value,
            "member_count": self.members.value,
            "tos_ok": self.tos.value,
            "created_at": dt.datetime.utcnow(),
        })

        if cfg.get("request_channel_id"):
            req_channel = interaction.guild.get_channel(cfg["request_channel_id"])
            if req_channel:
                await req_channel.send(f"{interaction.user.mention} ha inviato una richiesta partnership.")

        await interaction.response.send_message("Richiesta partnership inviata con successo.", ephemeral=True)


class PartnerDecisionView(View):
    def __init__(self, cog: "Partnership", requester: discord.Member, server_name: str, server_link: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.requester = requester
        self.server_name = server_name
        self.server_link = server_link

    @discord.ui.button(label="Approva partnership", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: Button):
        cfg = self.cog.config.get(interaction.guild_id)
        if cfg is None:
            await interaction.response.send_message("Configurazione non trovata.", ephemeral=True)
            return

        role = interaction.guild.get_role(cfg.get("partner_role_id"))
        if role:
            await self.requester.add_roles(role, reason="Partnership approvata")

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.title = "Partnership approvata"
        embed.description = f"{embed.description}\n\n✅ Approvata da {interaction.user.mention}"
        await interaction.message.edit(embed=embed, view=None)

        try:
            await self.requester.send(
                f"La tua richiesta partnership per **{self.server_name}** è stata approvata.\nLink: {self.server_link}"
            )
        except Exception:
            pass

        await interaction.response.send_message("Partnership approvata.", ephemeral=True)

    @discord.ui.button(label="Rifiuta partnership", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, button: Button):
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.title = "Partnership rifiutata"
        embed.description = f"{embed.description}\n\n❌ Rifiutata da {interaction.user.mention}"
        await interaction.message.edit(embed=embed, view=None)

        try:
            await self.requester.send(
                f"La tua richiesta partnership per **{self.server_name}** è stata rifiutata.\nLink: {self.server_link}"
            )
        except Exception:
            pass

        await interaction.response.send_message("Partnership rifiutata.", ephemeral=True)


class Partnership(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config: Dict[int, Dict[str, Any]] = {}
        self.blacklist: Dict[int, str] = {}
        self.chain_links: Dict[int, Dict[str, str]] = {}
        self.descriptions: Dict[int, str] = {}
        self.pending: Dict[int, List[Dict[str, Any]]] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        print("Partnership cog ready.")

    @app_commands.command(name="setup-partnership", description="Configura la sezione partnership")
    @app_commands.describe(
        request_channel="Canale dove arrivano le richieste",
        log_channel="Canale dove verranno inviati i log",
        partner_role="Ruolo da assegnare ai partner",
        manager="Manager del server",
        description="Descrizione standard",
        ping_role="Ping facoltativo",
        second_ping_role="Secondo ping facoltativo",
    )
    async def setup_partnership(
        self,
        interaction: discord.Interaction,
        request_channel: discord.TextChannel,
        log_channel: discord.TextChannel,
        partner_role: discord.Role,
        manager: discord.Member,
        description: str,
        ping_role: Optional[discord.Role] = None,
        second_ping_role: Optional[discord.Role] = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return

        self.config[interaction.guild_id] = {
            "request_channel_id": request_channel.id,
            "log_channel_id": log_channel.id,
            "partner_role_id": partner_role.id,
            "manager_id": manager.id,
            "description": description,
            "ping_role_id": ping_role.id if ping_role else None,
            "second_ping_role_id": second_ping_role.id if second_ping_role else None,
        }
        self.descriptions[interaction.guild_id] = description
        self.pending.setdefault(interaction.guild_id, [])

        text = (
            f"Configurazione salvata.\n"
            f"Canale richieste: {request_channel.mention}\n"
            f"Canale log: {log_channel.mention}\n"
            f"Ruolo partner: {partner_role.mention}\n"
            f"Manager: {manager.mention}\n"
            f"Descrizione: {description}"
        )
        if ping_role:
            text += f"\nPing: {ping_role.mention}"
        if second_ping_role:
            text += f"\nSecondo ping: {second_ping_role.mention}"

        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="blacklist-add", description="Aggiunge un server alla blacklist")
    @app_commands.describe(server_id="ID del server da bloccare")
    async def blacklist_add(self, interaction: discord.Interaction, server_id: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return
        self.blacklist[int(server_id)] = "blacklisted"
        await interaction.response.send_message(f"Server `{server_id}` aggiunto alla blacklist.", ephemeral=True)

    @app_commands.command(name="blacklist-remove", description="Rimuove un server dalla blacklist")
    @app_commands.describe(server_id="ID del server da sbloccare")
    async def blacklist_remove(self, interaction: discord.Interaction, server_id: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return
        self.blacklist.pop(int(server_id), None)
        await interaction.response.send_message(f"Server `{server_id}` rimosso dalla blacklist.", ephemeral=True)

    @app_commands.command(name="chain-add", description="Aggiunge una chain ad un server")
    @app_commands.describe(server_id="ID del server", link="Link del server")
    async def chain_add(self, interaction: discord.Interaction, server_id: str, link: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return
        self.chain_links.setdefault(interaction.guild_id, {})
        self.chain_links[interaction.guild_id][str(server_id)] = link
        await interaction.response.send_message(f"Chain aggiunta per `{server_id}`.", ephemeral=True)

    @app_commands.command(name="chain-remove", description="Rimuove una chain")
    @app_commands.describe(server_id="ID del server")
    async def chain_remove(self, interaction: discord.Interaction, server_id: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return
        guild_links = self.chain_links.get(interaction.guild_id, {})
        guild_links.pop(str(server_id), None)
        await interaction.response.send_message(f"Chain rimossa per `{server_id}`.", ephemeral=True)

    @app_commands.command(name="descrizione", description="Mostra la descrizione standard")
    async def descrizione(self, interaction: discord.Interaction):
        text = self.descriptions.get(interaction.guild_id, "Nessuna descrizione configurata.")
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="modifica-desc", description="Modifica la descrizione standard")
    @app_commands.describe(nuova_descrizione="Nuova descrizione")
    async def modifica_desc(self, interaction: discord.Interaction, nuova_descrizione: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return
        self.descriptions[interaction.guild_id] = nuova_descrizione
        await interaction.response.send_message(f"Descrizione aggiornata:\n\n{nuova_descrizione}", ephemeral=True)

    @app_commands.command(name="automazione", description="Imposta i canali per le richieste e i log partnership")
    @app_commands.describe(
        request_channel="Canale richieste",
        log_channel="Canale log",
        custom_message="Messaggio automatico da inviare",
    )
    async def automazione(
        self,
        interaction: discord.Interaction,
        request_channel: discord.TextChannel,
        log_channel: discord.TextChannel,
        custom_message: str,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("Non hai i permessi necessari.", ephemeral=True)
            return
        self.config.setdefault(interaction.guild_id, {})
        self.config[interaction.guild_id].update(
            {
                "request_channel_id": request_channel.id,
                "log_channel_id": log_channel.id,
                "custom_message": custom_message,
            }
        )
        await interaction.response.send_message(
            f"Automazione configurata.\nRichieste: {request_channel.mention}\nLog: {log_channel.mention}\nMessaggio: {custom_message}",
            ephemeral=True,
        )

    @app_commands.command(name="request-partner", description="Invia una richiesta partnership manuale")
    async def request_partner(self, interaction: discord.Interaction):
        cfg = self.config.get(interaction.guild_id)
        if cfg is None:
            await interaction.response.send_message("Prima configura /setup-partnership o /automazione.", ephemeral=True)
            return

        modal = PartnershipRequestModal(self, title="Richiesta partnership")
        await interaction.response.send_modal(modal)

    @app_commands.command(name="leaderboard-partnership", description="Mostra il leaderboard delle partnership")
    async def leaderboard_partnership(self, interaction: discord.Interaction):
        leaderboard = [
            ("Staff 1", 12),
            ("Staff 2", 9),
            ("Staff 3", 7),
        ]
        content = "\n".join(f"{name}: {count}" for name, count in leaderboard)
        await interaction.response.send_message(f"Leaderboard partnership:\n{content}", ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(Partnership(bot))
