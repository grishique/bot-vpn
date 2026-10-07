"""FSM state definitions for customer purchase flows."""

from aiogram.fsm.state import State, StatesGroup


class PurchaseState(StatesGroup):
    """State group for purchase-related interactions."""

    waiting_promocode = State()
    waiting_topup_amount = State()
