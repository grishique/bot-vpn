"""FSM state definitions for administrator flows."""

from aiogram.fsm.state import State, StatesGroup


class AddServerState(StatesGroup):
    """Wizard for adding a VPN server."""

    name = State()
    panel_url = State()
    panel_username = State()
    panel_password = State()
    inbound_id = State()
    host = State()
    port = State()
    public_key = State()
    sni = State()
    short_id = State()
    advanced = State()
