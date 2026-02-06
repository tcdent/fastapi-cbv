"""Unit tests for fastapi_cbv.views module."""

from __future__ import annotations

import inspect

import pytest
from fastapi import Depends
from pydantic import BaseModel

from fastcbv import BaseView, status_code
from fastcbv.views import (
    ViewConfig,
    ViewMetadata,
    _extract_class_params,
    _extract_func_params,
    _resolve_hints,
)


class ItemModel(BaseModel):
    """Non-builtin type defined at module level for annotation tests."""

    name: str
    price: float = 0.0


class TestViewMetadata:
    """Tests for ViewMetadata dataclass."""

    def test_default_configs_empty(self):
        meta = ViewMetadata()
        assert meta.configs == []

    def test_configs_list(self):
        meta = ViewMetadata()
        meta.configs.append(
            ViewConfig(endpoint=lambda: None, method_name="get")
        )
        assert len(meta.configs) == 1


class TestExtractClassParams:
    """Tests for _extract_class_params function."""

    def test_extracts_annotated_attrs(self):
        class MyView(BaseView):
            name: str
            count: int = 0

        params = _extract_class_params(MyView)
        param_names = {p.name for p in params}
        assert "name" in param_names
        assert "count" in param_names

    def test_excludes_underscore_prefix(self):
        class MyView(BaseView):
            _private: str = "hidden"
            public: str = "visible"

        params = _extract_class_params(MyView)
        param_names = {p.name for p in params}
        assert "_private" not in param_names
        assert "public" in param_names

    def test_includes_request(self):
        # request is included and passed as kwarg to __init__
        params = _extract_class_params(BaseView)
        param_names = {p.name for p in params}
        assert "request" in param_names

    def test_params_are_keyword_only(self):
        class MyView(BaseView):
            name: str

        params = _extract_class_params(MyView)
        for p in params:
            assert p.kind == inspect.Parameter.KEYWORD_ONLY


class TestExtractFuncParams:
    """Tests for _extract_func_params function."""

    def test_extracts_params(self):
        def func(self, a: int, b: str = "default"):
            pass

        params = _extract_func_params(func)
        param_names = {p.name for p in params}
        assert "a" in param_names
        assert "b" in param_names

    def test_excludes_self(self):
        def func(self, a: int):
            pass

        params = _extract_func_params(func)
        param_names = {p.name for p in params}
        assert "self" not in param_names

    def test_excludes_args_kwargs(self):
        def func(self, *args, **kwargs):
            pass

        params = _extract_func_params(func)
        param_names = {p.name for p in params}
        assert "args" not in param_names
        assert "kwargs" not in param_names

    def test_excludes_underscore_prefix(self):
        def func(self, _internal: int, public: str):
            pass

        params = _extract_func_params(func)
        param_names = {p.name for p in params}
        assert "_internal" not in param_names
        assert "public" in param_names

    def test_params_are_keyword_only(self):
        def func(self, a: int, b: str):
            pass

        params = _extract_func_params(func)
        for p in params:
            assert p.kind == inspect.Parameter.KEYWORD_ONLY


class TestBaseView:
    """Tests for BaseView class."""

    def test_has_meta(self):
        assert hasattr(BaseView, "_meta")
        assert isinstance(BaseView._meta, ViewMetadata)

    def test_base_view_has_no_configs(self):
        assert BaseView._meta.configs == []

    def test_subclass_inherits_meta(self):
        class MyView(BaseView):
            async def get(self):
                pass

        assert hasattr(MyView, "_meta")
        assert isinstance(MyView._meta, ViewMetadata)


class TestViewMethodDetection:
    """Tests for HTTP method detection in views."""

    def test_detects_get(self):
        class MyView(BaseView):
            async def get(self):
                return {}

        assert len(MyView._meta.configs) == 1
        assert MyView._meta.configs[0].method_name == "get"

    def test_detects_multiple_methods(self):
        class MyView(BaseView):
            async def get(self):
                pass

            async def post(self):
                pass

            async def delete(self):
                pass

        method_names = {c.method_name for c in MyView._meta.configs}
        assert method_names == {"get", "post", "delete"}

    def test_ignores_non_http_methods(self):
        class MyView(BaseView):
            async def get(self):
                pass

            async def helper(self):
                pass

        assert len(MyView._meta.configs) == 1
        assert MyView._meta.configs[0].method_name == "get"

    def test_all_http_methods(self):
        class MyView(BaseView):
            async def get(self): pass
            async def post(self): pass
            async def put(self): pass
            async def patch(self): pass
            async def delete(self): pass
            async def head(self): pass
            async def options(self): pass

        method_names = {c.method_name for c in MyView._meta.configs}
        assert method_names == {"get", "post", "put", "patch", "delete", "head", "options"}


class TestStatusCodeDecorator:
    """Tests for @status_code decorator."""

    def test_default_status_code_none(self):
        class MyView(BaseView):
            async def get(self):
                pass

        assert MyView._meta.configs[0].status_code is None

    def test_custom_status_code(self):
        class MyView(BaseView):
            @status_code(201)
            async def post(self):
                pass

        assert MyView._meta.configs[0].status_code == 201

    def test_multiple_status_codes(self):
        class MyView(BaseView):
            async def get(self):
                pass

            @status_code(201)
            async def post(self):
                pass

            @status_code(204)
            async def delete(self):
                pass

        configs = {c.method_name: c.status_code for c in MyView._meta.configs}
        assert configs["get"] is None
        assert configs["post"] == 201
        assert configs["delete"] == 204


class TestEndpointSignature:
    """Tests for generated endpoint signatures."""

    def test_includes_method_params(self):
        class MyView(BaseView):
            async def get(self, item_id: int):
                pass

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert "item_id" in sig.parameters

    def test_includes_class_params(self):
        def get_db():
            return {}

        class MyView(BaseView):
            db: dict = Depends(get_db)

            async def get(self):
                pass

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert "db" in sig.parameters

    def test_includes_prepare_params(self):
        class MyView(BaseView):
            async def __prepare__(self, item_id: int):
                pass

            async def get(self):
                pass

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert "item_id" in sig.parameters

    def test_combines_all_params(self):
        def get_db():
            return {}

        class MyView(BaseView):
            db: dict = Depends(get_db)

            async def __prepare__(self, resource_id: int):
                pass

            async def get(self, format: str = "json"):
                pass

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        param_names = set(sig.parameters.keys())
        assert "db" in param_names
        assert "resource_id" in param_names
        assert "format" in param_names

    def test_preserves_return_annotation(self):
        class MyView(BaseView):
            async def get(self) -> dict:
                return {}

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        # annotation is a string due to `from __future__ import annotations`
        assert sig.return_annotation in (dict, "dict")

    def test_params_ordered_required_first(self):
        def get_db():
            return {}

        class MyView(BaseView):
            db: dict = Depends(get_db)

            async def get(self, required_param: int):
                pass

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        params = list(sig.parameters.values())

        # Find positions
        required_idx = next(i for i, p in enumerate(params) if p.name == "required_param")
        optional_idx = next(i for i, p in enumerate(params) if p.name == "db")

        assert required_idx < optional_idx


class TestResolveHints:
    """Tests for _resolve_hints helper."""

    def test_resolves_class_hints(self):
        class MyView(BaseView):
            db: ItemModel

        hints = _resolve_hints(MyView)
        assert hints["db"] is ItemModel

    def test_resolves_function_hints(self):
        async def handler(self, item: ItemModel) -> ItemModel:
            return item

        hints = _resolve_hints(handler)
        assert hints["item"] is ItemModel
        assert hints["return"] is ItemModel

    def test_resolves_builtin_hints(self):
        async def handler(self, x: int, y: str) -> dict:
            return {}

        hints = _resolve_hints(handler)
        assert hints["x"] is int
        assert hints["y"] is str
        assert hints["return"] is dict


class TestFutureAnnotations:
    """Tests that non-builtin types work with ``from __future__ import annotations``.

    This module uses ``from __future__ import annotations``, so all type
    annotations are strings at runtime. The view machinery must resolve
    them back to real types before handing them to FastAPI.
    """

    def test_method_param_annotation_resolved(self):
        """Method parameters with non-builtin type annotations are resolved."""

        class MyView(BaseView):
            async def post(self, item: ItemModel) -> dict:
                return {}

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert sig.parameters["item"].annotation is ItemModel

    def test_return_annotation_resolved(self):
        """Return annotations with non-builtin types are resolved."""

        class MyView(BaseView):
            async def get(self) -> ItemModel:
                return ItemModel(name="test")

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert sig.return_annotation is ItemModel

    def test_return_annotation_generic_resolved(self):
        """Generic return annotations like list[Model] are resolved."""

        class MyView(BaseView):
            async def get(self) -> list[ItemModel]:
                return []

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        # list[ItemModel] should be resolved, not a string
        assert sig.return_annotation is not inspect.Signature.empty
        assert not isinstance(sig.return_annotation, str)

    def test_class_dependency_annotation_resolved(self):
        """Class-level dependencies with non-builtin types are resolved."""

        def get_item():
            return ItemModel(name="test")

        class MyView(BaseView):
            item: ItemModel = Depends(get_item)

            async def get(self) -> dict:
                return {}

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert sig.parameters["item"].annotation is ItemModel

    def test_prepare_param_annotation_resolved(self):
        """__prepare__ parameters with non-builtin types are resolved."""

        class MyView(BaseView):
            async def __prepare__(self, item: ItemModel):
                self.item = item

            async def get(self) -> dict:
                return {}

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert sig.parameters["item"].annotation is ItemModel

    def test_combined_annotations_all_resolved(self):
        """All parameter sources resolve non-builtin types together."""

        def get_item():
            return ItemModel(name="dep")

        class MyView(BaseView):
            dep: ItemModel = Depends(get_item)

            async def __prepare__(self, prep: ItemModel):
                pass

            async def post(self, body: ItemModel) -> ItemModel:
                return body

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert sig.parameters["dep"].annotation is ItemModel
        assert sig.parameters["prep"].annotation is ItemModel
        assert sig.parameters["body"].annotation is ItemModel
        assert sig.return_annotation is ItemModel
