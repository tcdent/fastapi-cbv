from __future__ import annotations
from enum import Enum
from typing import Any, Callable, Sequence
from warnings import warn
import logging

from fastapi import APIRouter as _APIRouter
from fastapi.params import Depends
from fastapi.routing import BaseRoute

from .views import BaseView

T = type[BaseView]


logger = logging.getLogger(__name__)


class APIRouter(_APIRouter):
    """
    Extended FastAPI router with support for class-based views.

    Example:
        router = APIRouter(prefix="/api")
        router.add_view("/items/{item_id}", ItemView, tags=["items"])
        app.include_router(router)
    """

    def add_view(
        self,
        path: str,
        view: type[BaseView],
        *,
        methods: list[str] | None = None,
        name_prefix: str | None = None,
        tags: list[str | Enum] | None = None,
        dependencies: Sequence[Depends] | None = None,
        responses: dict[int | str, dict[str, Any]] | None = None,
        deprecated: bool = False,
        include_in_schema: bool = True,
        callbacks: list[BaseRoute] | None = None,
        openapi_extra: dict[str, Any] | None = None,
    ) -> None:
        """
        Register a class-based view at the given path.

        Args:
            path: URL path for the view
            view: BaseView subclass to register
            methods: HTTP methods to register (default: auto-detect from view)
            name_prefix: Prefix for route names (default: view.name or class name)
            tags: OpenAPI tags for all methods
            dependencies: Dependencies applied to all methods
            responses: Additional OpenAPI responses for all methods
            deprecated: Mark all methods as deprecated
            include_in_schema: Include in OpenAPI schema
            callbacks: OpenAPI callbacks
            openapi_extra: Additional OpenAPI metadata
        """
        if not issubclass(view, BaseView):
            raise TypeError(f"{view} is not a subclass of BaseView")

        if not view._meta.configs:
            warn(
                f"No route methods found in view {view.__name__}. "
                "Did you forget to define an HTTP verb (get, post, etc.) method?",
                UserWarning,
            )
            return

        methods_filter = {m.lower() for m in methods} if methods else None
        prefix = name_prefix or getattr(view, "name", None) or view.__name__

        for config in view._meta.configs:
            if methods_filter and config.method_name not in methods_filter:
                logger.debug(f"Methods filter excludes {config.method_name}.")
                continue

            self.add_api_route(
                path=path,
                endpoint=config.endpoint,
                methods=[config.method_name.upper()],
                name=f"{prefix}_{config.method_name}",
                status_code=config.status_code,
                tags=tags,
                dependencies=dependencies,
                responses=responses,
                deprecated=deprecated,
                include_in_schema=include_in_schema,
                callbacks=callbacks,
                openapi_extra=openapi_extra,
            )

    def view(
        self,
        path: str,
        *,
        methods: list[str] | None = None,
        name_prefix: str | None = None,
        tags: list[str | Enum] | None = None,
        dependencies: Sequence[Depends] | None = None,
        responses: dict[int | str, dict[str, Any]] | None = None,
        deprecated: bool = False,
        include_in_schema: bool = True,
        callbacks: list[BaseRoute] | None = None,
        openapi_extra: dict[str, Any] | None = None,
    ) -> Callable[[T], T]:
        """
        Decorator to register a class-based view at the given path.

        Example:
            @router.view("/items/{item_id}", tags=["items"])
            class ItemView(BaseView):
                async def get(self) -> dict:
                    return {"item_id": self.item_id}

        Args:
            path: URL path for the view
            methods: HTTP methods to register (default: auto-detect from view)
            name_prefix: Prefix for route names (default: class name)
            tags: OpenAPI tags for all methods
            dependencies: Dependencies applied to all methods
            responses: Additional OpenAPI responses for all methods
            deprecated: Mark all methods as deprecated
            include_in_schema: Include in OpenAPI schema
            callbacks: OpenAPI callbacks
            openapi_extra: Additional OpenAPI metadata

        Returns:
            Decorator that registers the view and returns the class unchanged.
        """

        def decorator(view: T) -> T:
            self.add_view(
                path,
                view,
                methods=methods,
                name_prefix=name_prefix,
                tags=tags,
                dependencies=dependencies,
                responses=responses,
                deprecated=deprecated,
                include_in_schema=include_in_schema,
                callbacks=callbacks,
                openapi_extra=openapi_extra,
            )
            return view

        return decorator
