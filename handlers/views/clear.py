"""Подтверждение очистки всех маяков."""

from __future__ import annotations

from datetime import datetime

import discord
from discord.ui import Button, View

from services import database as db
from utils.formatting import get_user_info
from utils.logging_setup import action_logger, error_logger


class ConfirmClearView(View):
    """Кнопки подтверждения удаления всех маяков."""

    def __init__(
        self,
        original_user: discord.abc.User,
        original_interaction: discord.Interaction,
        *,
        yes_label: str = "Да, удалить всё",
        no_label: str = "Нет, отмена",
    ) -> None:
        super().__init__(timeout=30)
        self.original_user = original_user
        self.original_interaction = original_interaction

        yes = Button(label=yes_label, style=discord.ButtonStyle.danger, emoji="✅")
        yes.callback = self._confirm
        self.add_item(yes)

        no = Button(label=no_label, style=discord.ButtonStyle.secondary, emoji="❌")
        no.callback = self._cancel
        self.add_item(no)

    async def _confirm(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message(
                "Вы не можете подтвердить чужую команду!",
                ephemeral=True,
            )
            return

        try:
            beacon_list = db.clear_all_beacons()
            count_before = len(beacon_list)

            if count_before > 0:
                action_logger.info(
                    f"{get_user_info(interaction)} cleared ALL beacons | "
                    f"Deleted: {count_before} beacons: {', '.join(beacon_list)}"
                )

            embed = discord.Embed(
                title="🧹 Очистка всех маяков",
                description=f"**Удалено маяков: {count_before}**",
                color=discord.Color.red(),
                timestamp=datetime.now(),
            )
            if count_before > 0:
                preview = ", ".join(beacon_list[:10])
                if len(beacon_list) > 10:
                    preview += f" и еще {len(beacon_list) - 10}"
                embed.add_field(
                    name="📋 Список удаленных маяков",
                    value=preview,
                    inline=False,
                )
            embed.add_field(
                name="",
                value=f"Очистил: {interaction.user.mention}",
                inline=False,
            )

            if interaction.channel:
                await interaction.channel.send(embed=embed)

            await interaction.response.edit_message(
                content=f"✅ Все маяки ({count_before}) успешно удалены!",
                embed=None,
                view=None,
            )
        except Exception as exc:
            error_logger.error(
                f"{get_user_info(interaction)} Ошибка при очистке всех маяков: {exc}",
                exc_info=True,
            )
            await interaction.response.edit_message(
                content=f"❌ Ошибка при удалении: {exc}",
                embed=None,
                view=None,
            )

    async def _cancel(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message(
                "Вы не можете отменить чужую команду!",
                ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            content="❌ Очистка маяков отменена.",
            embed=None,
            view=None,
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]
        try:
            await self.original_interaction.edit_original_response(
                content="⌛ Время подтверждения истекло. Очистка отменена.",
                embed=None,
                view=self,
            )
        except discord.HTTPException:
            pass
