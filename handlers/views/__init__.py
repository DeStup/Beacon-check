"""UI-компоненты handlers."""

from handlers.views.clear import ConfirmClearView
from handlers.views.menu import BeaconMenuView
from handlers.views.modals import DeleteBeaconModal, EditBeaconModal, RefuelModal
from handlers.views.select import BeaconSelectView
from handlers.views.status import show_all_beacons_status, show_beacon_status

__all__ = [
    "BeaconMenuView",
    "BeaconSelectView",
    "ConfirmClearView",
    "DeleteBeaconModal",
    "EditBeaconModal",
    "RefuelModal",
    "show_all_beacons_status",
    "show_beacon_status",
]
