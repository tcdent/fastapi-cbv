from __future__ import annotations

from typing import Any, Callable, TypeVar

T = TypeVar("T", bound=Callable[..., Any])

STATUS_CODE_ATTR: str = "_fastapi_cbv_status_code"


def status_code(code: int) -> Callable[[T], T]:
    """
    Decorator to set the HTTP status code for a view method.

    Example:
        class ItemView(BaseView):
            @status_code(201)
            async def post(self, body: ItemCreate) -> Item:
                return await Item.create(body)

            @status_code(204)
            async def delete(self, item_id: int) -> None:
                await Item.delete(item_id)
    """

    def decorator(func: T) -> T:
        setattr(func, STATUS_CODE_ATTR, code)
        return func

    return decorator


def _get_status_code(func: Callable) -> int | None:
    """Get the custom status code for a method."""
    return getattr(func, STATUS_CODE_ATTR, None)
