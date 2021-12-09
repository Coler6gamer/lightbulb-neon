import asyncio
import dataclasses
import inspect
import typing as t

import hikari
import lightbulb
from hikari.interactions.component_interactions import ComponentInteraction


@dataclasses.dataclass
class Button:
    callback: t.Callable
    label: str
    custom_id: str
    style: t.Union[int, hikari.ButtonStyle]
    emoji: t.Union[hikari.Snowflakeish, hikari.Emoji, str, None]
    is_disabled: bool


@dataclasses.dataclass
class SelectMenuOption:
    label: str
    custom_id: str
    description: str
    emoji: t.Union[hikari.Snowflakeish, hikari.Emoji, str, None]
    is_default: bool


@dataclasses.dataclass
class SelectMenu:
    callback: t.Callable
    custom_id: str
    placeholder: str
    is_disabled: bool
    min_values: int = 1
    max_values: int = 1

    options: t.MutableMapping[str, SelectMenuOption] = dataclasses.field(
        default_factory=dict
    )


@dataclasses.dataclass
class ButtonGroup:
    callback: t.Callable

    buttons: t.List[Button] = dataclasses.field(default_factory=list)

    def __hash__(self):
        return hash(self.callback.__name__)


@dataclasses.dataclass
class TimeoutFunc:
    callback: t.Callable
    disable_components: bool


class ComponentMenu:
    def __init__(
        self, context: lightbulb.Context, timeout: float = 60, author_only: bool = True
    ) -> None:
        self.ctx = context
        self.timeout_length = timeout
        self.author_only = author_only

        self.buttons: t.MutableMapping[str, Button] = {}
        self.button_groups: t.MutableMapping[ButtonGroup, t.List[Button]] = {}
        self.select_menus: t.MutableMapping[str, SelectMenu] = {}
        self.timeout_func: t.Union[TimeoutFunc, None] = None

        self.msg: t.Union[hikari.Message, None] = None
        self.inter: t.Union[ComponentInteraction, None] = None

    def build(self) -> hikari.api.ActionRowBuilder:
        for val in self.__class__.__dict__.values():
            if isinstance(val, Button):
                val.callback = val.callback.__get__(self)
                self.buttons[val.custom_id] = val

            if isinstance(val, SelectMenu):
                val.callback = val.callback.__get__(self)
                self.select_menus[val.custom_id] = val

            if isinstance(val, ButtonGroup):
                val.callback = val.callback.__get__(self)
                self.button_groups[val] = val.buttons

            if isinstance(val, TimeoutFunc):
                val.callback = val.callback.__get__(self)
                self.timeout_func = val

        return self.build_components()

    async def edit_msg(self, *args, **kwargs) -> None:
        if self.inter is not None:
            try:
                await self.inter.create_initial_response(
                    hikari.ResponseType.MESSAGE_UPDATE,
                    *args,
                    **kwargs,
                )
            except hikari.NotFoundError:
                await self.inter.edit_initial_response(
                    *args,
                    **kwargs,
                )
        else:
            await self.msg.edit(*args, **kwargs)

    async def run(self, msg: lightbulb.ResponseProxy) -> None:
        self.msg = await msg.message()
        while True:
            try:
                assert self.msg is not None
                event = await self.ctx.bot.wait_for(
                    hikari.InteractionCreateEvent,
                    timeout=self.timeout_length,
                    predicate=lambda e: isinstance(
                        e.interaction, hikari.ComponentInteraction
                    )
                    and e.interaction.message.id == self.msg.id,
                )
            except asyncio.TimeoutError:
                await self.timeout_job(self.timeout_func)
                break
            else:
                self.inter = event.interaction

                if self.author_only and self.inter.user.id != self.ctx.user.id:
                    return

                cid = self.inter.custom_id

                if self.inter.component_type == hikari.ComponentType.BUTTON:
                    if cid in self.buttons.keys():
                        button = self.buttons[cid]
                        if len(inspect.signature(button.callback).parameters) >= 1:
                            await button.callback(button)
                        else:
                            await button.callback()

                    for group, buttons in self.button_groups.items():
                        for button in buttons:
                            if cid == button.custom_id:
                                await group.callback(button)
                                break

                elif self.inter.component_type == hikari.ComponentType.SELECT_MENU:
                    menu = self.select_menus[cid]
                    await menu.callback(self.inter.values)

    async def timeout_job(self, timeout_func: TimeoutFunc):
        if timeout_func is not None:
            await timeout_func.callback()
            if timeout_func.disable_components == True:
                components = self.build_components(disabled=True)
                await self.edit_msg(components=components)

        else:
            components = self.build_components(disabled=True)
            await self.edit_msg(components=components)

    def build_components(
        self, *, disabled: t.Optional[bool] = False
    ) -> t.List[hikari.api.ActionRowBuilder]:
        rows = []

        if len(self.buttons) > 0:
            row = self.ctx.bot.rest.build_action_row()

            for button in self.buttons.values():
                b = row.add_button(button.style, button.custom_id)
                b.set_label(button.label)
                if button.emoji is not None:
                    b.set_emoji(button.emoji)
                b.set_is_disabled(disabled if disabled is True else button.is_disabled)
                b.add_to_container()

            rows.append(row)

        if len(self.button_groups) > 0:
            for buttons in self.button_groups.values():
                row = self.ctx.bot.rest.build_action_row()
                for button in buttons:
                    b = row.add_button(button.style, button.custom_id)
                    b.set_label(button.label)
                    if button.emoji is not None:
                        b.set_emoji(button.emoji)
                    b.set_is_disabled(
                        disabled if disabled is True else button.is_disabled
                    )
                    b.add_to_container()

                rows.append(row)

        if len(self.select_menus) > 0:
            for menu in self.select_menus.values():
                row = self.ctx.bot.rest.build_action_row()

                m = row.add_select_menu(menu.custom_id)
                m.set_placeholder(menu.placeholder)
                m.set_min_values(menu.min_values)
                m.set_max_values(menu.max_values)
                m.set_is_disabled(disabled if disabled is True else menu.is_disabled)

                for opt in menu.options.values():
                    o = m.add_option(opt.label, opt.custom_id)
                    o.set_description(opt.description)
                    if opt.emoji is not None:
                        o.set_emoji(opt.emoji)
                    o.set_is_default(opt.is_default)
                    o.add_to_menu()

                m.add_to_container()

                rows.append(row)

        return rows


def button(
    label: str,
    url_or_custom_id: str,
    style: t.Union[int, hikari.ButtonStyle],
    *,
    emoji: t.Union[hikari.Snowflakeish, hikari.Emoji, str, None] = None,
    is_disabled: bool = False,
) -> t.Any:
    def decorate(func) -> t.Any:
        if isinstance(func, ButtonGroup):
            func.buttons.append(
                Button(
                    func.callback, label, url_or_custom_id, style, emoji, is_disabled
                )
            )
            return func
        return Button(func, label, url_or_custom_id, style, emoji, is_disabled)

    return decorate


def button_group():
    def decorate(func):
        return ButtonGroup(func)

    return decorate


def select_menu(
    custom_id: str,
    placeholder: str,
    *,
    is_disabled: bool = False,
    min_values: int = 1,
    max_values: int = 1,
) -> t.Any:
    def decorate(func) -> t.Any:
        return SelectMenu(
            func, custom_id, placeholder, is_disabled, min_values, max_values
        )

    return decorate


def option(
    label: str,
    custom_id: str,
    description: str = "",
    *,
    emoji: t.Union[hikari.Snowflakeish, hikari.Emoji, str, None] = None,
    is_default: bool = False,
):
    def decorate(menu: SelectMenu):
        menu.options[custom_id] = SelectMenuOption(
            label, custom_id, description, emoji, is_default
        )
        return menu

    return decorate


def on_timeout(*, disable_components: bool = True):
    def decorate(func):
        return TimeoutFunc(func, disable_components)

    return decorate
