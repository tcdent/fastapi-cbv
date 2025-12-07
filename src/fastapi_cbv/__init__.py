from __future__ import annotations
import os
import logging

from .views import BaseView, ViewConfig, ViewMetadata
from .routing import APIRouter
from .decorators import status_code

__all__ = [
    "BaseView",
    "ViewConfig",
    "ViewMetadata",
    "APIRouter",
    "status_code",
]


logging.basicConfig(level=os.getenv("LOGLEVEL", "INFO"))
