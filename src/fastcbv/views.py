from __future__ import annotations
from types import FunctionType
from typing import Any, Callable, get_type_hints
import inspect
import logging
import re
from dataclasses import dataclass, field

from fastapi import Request

from .decorators import _get_status_code


logger = logging.getLogger(__name__)

HTTP_METHODS: tuple[str, ...] = (
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
)


@dataclass
class ViewConfig:
    """Configuration for a single route generated from a view method."""

    endpoint: Callable[..., Any]
    method_name: str
    status_code: int | None = None


@dataclass
class ViewMetadata:
    """Metadata computed at class definition time for a view."""

    configs: list[ViewConfig] = field(default_factory=list)


def _extract_class_params(
    cls: type,
    exclude: set[str] = {"^return$", "^_"},
) -> list[inspect.Parameter]:
    """Extract class-level parameters from type hints."""
    return [
        inspect.Parameter(
            name,
            inspect.Parameter.KEYWORD_ONLY,
            default=getattr(cls, name, inspect.Parameter.empty),
            annotation=annotation,
        )
        for name, annotation in get_type_hints(cls).items()
        if not any(re.match(e, name) for e in exclude)
    ]


def _extract_func_params(
    func: Callable,
    exclude: set[str] = {"^self$", "^args$", "^kwargs$", "^_"},
) -> list[inspect.Parameter]:
    """Get parameters from a function, excluding matches."""
    return [
        p.replace(kind=inspect.Parameter.KEYWORD_ONLY)
        for p in inspect.signature(func).parameters.values()
        if not any(re.match(e, p.name) for e in exclude)
    ]


class ViewMeta(type):
    """
    Metaclass for BaseView that performs introspection at class definition time.

    Computes and caches metadata in `cls.meta`:
    - configs: List of ViewConfig for each HTTP method
    - class_params: Set of class-level parameter names
    - prepare_params: Set of __prepare__ parameter names

    This avoids repeated introspection at request time and keeps the
    introspection logic associated with the view class itself.
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> ViewMeta:
        cls = super().__new__(mcs, name, bases, namespace)

        cls._meta = ViewMetadata()

        # Skip introspection for BaseView itself
        if not bases:
            return cls

        class_params = _extract_class_params(cls)
        prepare_params = _extract_func_params(cls.__prepare__)

        for method_name in HTTP_METHODS:
            if not hasattr(cls, method_name):
                continue

            def make_endpoint(
                func: Callable[..., Any],
                params: list[inspect.Parameter],
            ) -> FunctionType:
                async def endpoint(**kwargs: Any) -> Any:
                    instance = cls(
                        **{p.name: kwargs[p.name] for p in class_params},
                    )
                    await instance.__prepare__(
                        **{p.name: kwargs[p.name] for p in prepare_params},
                    )
                    return await func(
                        instance,
                        **{p.name: kwargs[p.name] for p in params},
                    )

                return endpoint

            method_func = getattr(cls, method_name)
            method_params = _extract_func_params(method_func)
            endpoint = make_endpoint(method_func, method_params)

            params = [*class_params, *prepare_params, *method_params]
            params.sort(key=lambda p: p.default is not inspect.Parameter.empty)
            endpoint.__signature__ = inspect.Signature(  # type: ignore[unresolved-attribute]
                parameters=params,
                return_annotation=inspect.signature(method_func).return_annotation,
            )
            endpoint.__name__ = method_func.__name__
            endpoint.__doc__ = method_func.__doc__

            logger.debug(
                f"{cls.__name__} initialized HTTP {method_name.upper()} handler with signature:\n"
                f"\t{endpoint.__signature__}"  # type: ignore[unresolved-attribute]
            )

            cls._meta.configs.append(
                ViewConfig(
                    endpoint=endpoint,
                    method_name=method_name,
                    status_code=_get_status_code(method_func),
                )
            )

        return cls


class BaseView(metaclass=ViewMeta):
    """
    Base class for class-based views.

    Provides access to the request object and serves as the foundation
    for building view hierarchies with shared dependencies and behavior.

    Example:
        class ItemView(BaseView):
            db: Session = Depends(get_db)

            async def get(self, item_id: int) -> Item:
                return await self.db.query(Item).get(item_id)

    The metaclass automatically detects HTTP methods and class-level
    dependencies at class definition time, storing them in `meta`.
    """

    _meta: ViewMetadata
    request: Request

    def __init__(self, request: Request, **kwargs: Any) -> None:
        """
        Initialize the view with request and class-level parameters.

        Args:
            request: The FastAPI request object
            **kwargs: Resolved class-level parameters
        """
        self.request = request
        for key, value in kwargs.items():
            setattr(self, key, value)

    async def __prepare__(self, *args: Any, **kwargs: Any) -> None:
        """
        Preparation hook called before each request method.

        Can be overridden to perform setup tasks like loading resources
        or validating permissions.
        """
        pass
