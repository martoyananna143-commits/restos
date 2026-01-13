"""Import all routers and add them to routers_list."""

from .start import start_router

routers_list = [
    start_router,
]

__all__ = [
    "routers_list",
]
