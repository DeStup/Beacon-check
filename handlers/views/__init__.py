"""UI-компоненты handlers."""

from handlers.views.clear import ConfirmClearView
from handlers.views.menu import BeaconPanelView
from handlers.views.modals import DeleteBeaconModal, EditBeaconModal
from handlers.views.select import BeaconSelectView

__all__ = [
    "BeaconPanelView",
    "BeaconSelectView",
    "ConfirmClearView",
    "DeleteBeaconModal",
    "EditBeaconModal",
]
