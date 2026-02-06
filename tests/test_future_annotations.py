"""Tests for ``from __future__ import annotations`` support.

This file **must** keep the future-annotations import at the top.
With it active, every type annotation in this module is a string at
runtime.  The library must resolve those strings back to real types
before handing them to FastAPI — otherwise non-builtin types
(Pydantic models, custom classes, etc.) break.
"""

from __future__ import annotations

import inspect
from typing import Annotated

from fastapi import Depends, FastAPI, Path, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fastcbv import APIRouter, BaseView, status_code
from fastcbv.views import (
    _extract_class_params,
    _extract_func_params,
    _resolve_hints,
)


# ── Module-level types used in annotations ──────────────────────────
# These MUST be at module scope so that `get_type_hints()` can resolve
# the stringified annotations produced by `from __future__ import annotations`.


class ItemModel(BaseModel):
    name: str
    price: float = 0.0


class ItemSchema(BaseModel):
    id: int
    name: str


class FilterParams(BaseModel):
    limit: int = 10
    offset: int = 0


security = HTTPBearer()


def get_item_model() -> ItemModel:
    return ItemModel(name="test")


def get_item_db() -> dict:
    return {"items": [ItemSchema(id=1, name="Test")]}


# ── Unit tests ──────────────────────────────────────────────────────


class TestResolveHints:
    """Tests for the _resolve_hints helper."""

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


class TestAnnotationResolution:
    """Verify that annotations on the generated endpoint are real types,
    not leftover strings from ``from __future__ import annotations``.
    """

    def test_method_param_annotation_resolved(self):
        class MyView(BaseView):
            async def post(self, item: ItemModel) -> dict:
                return {}

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert sig.parameters["item"].annotation is ItemModel

    def test_return_annotation_resolved(self):
        class MyView(BaseView):
            async def get(self) -> ItemModel:
                return ItemModel(name="test")

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert sig.return_annotation is ItemModel

    def test_return_annotation_generic_resolved(self):
        class MyView(BaseView):
            async def get(self) -> list[ItemModel]:
                return []

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert sig.return_annotation is not inspect.Signature.empty
        assert not isinstance(sig.return_annotation, str)

    def test_class_dependency_annotation_resolved(self):
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
        class MyView(BaseView):
            async def __prepare__(self, item: ItemModel):
                self.item = item

            async def get(self) -> dict:
                return {}

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        assert sig.parameters["item"].annotation is ItemModel

    def test_combined_annotations_all_resolved(self):
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

    def test_annotated_class_dependency_resolved(self):
        class MyView(BaseView):
            item: Annotated[ItemModel, Depends(get_item_model)]

            async def get(self) -> dict:
                return {}

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        annotation = sig.parameters["item"].annotation
        # Should be Annotated[ItemModel, Depends(...)], not a string
        assert not isinstance(annotation, str)
        assert hasattr(annotation, "__metadata__")  # Annotated marker

    def test_annotated_method_param_resolved(self):
        class MyView(BaseView):
            async def get(self, limit: Annotated[int, Query(ge=1)]) -> dict:
                return {}

        config = MyView._meta.configs[0]
        sig = inspect.signature(config.endpoint)
        annotation = sig.parameters["limit"].annotation
        assert not isinstance(annotation, str)
        assert hasattr(annotation, "__metadata__")


# ── Integration tests ───────────────────────────────────────────────


class TestFutureAnnotationsIntegration:
    """End-to-end tests with actual HTTP requests proving that
    non-builtin types survive ``from __future__ import annotations``.
    """

    def test_pydantic_return_type(self):
        class ItemView(BaseView):
            async def get(self) -> ItemSchema:
                return ItemSchema(id=1, name="Test")

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        assert response.status_code == 200
        assert response.json() == {"id": 1, "name": "Test"}

    def test_pydantic_list_return_type(self):
        class ItemView(BaseView):
            async def get(self) -> list[ItemSchema]:
                return [ItemSchema(id=1, name="A"), ItemSchema(id=2, name="B")]

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_pydantic_body_param(self):
        class ItemView(BaseView):
            async def post(self, item: ItemSchema) -> ItemSchema:
                return item

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.post("/items", json={"id": 1, "name": "Created"})
        assert response.status_code == 200
        assert response.json() == {"id": 1, "name": "Created"}

    def test_pydantic_dependency_param(self):
        class ItemView(BaseView):
            async def get(self, params: FilterParams = Depends()) -> dict:
                return {"limit": params.limit, "offset": params.offset}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items?limit=5&offset=2")
        assert response.status_code == 200
        assert response.json() == {"limit": 5, "offset": 2}

    def test_class_dependency_with_custom_type(self):
        class Database(BaseModel):
            connection: str = "active"

        def get_database() -> Database:
            return Database()

        class ItemView(BaseView):
            db: Database = Depends(get_database)

            async def get(self) -> dict:
                return {"status": self.db.connection}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        assert response.status_code == 200
        assert response.json() == {"status": "active"}

    def test_prepare_with_custom_return_type(self):
        class ItemView(BaseView):
            async def __prepare__(self, item_id: int):
                self.item = ItemSchema(id=item_id, name=f"Item {item_id}")

            async def get(self) -> ItemSchema:
                return self.item

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items/42")
        assert response.status_code == 200
        assert response.json() == {"id": 42, "name": "Item 42"}

    def test_combined_custom_types(self):
        def get_db():
            return {"items": {1: ItemSchema(id=1, name="Test")}}

        class ItemView(BaseView):
            db: dict = Depends(get_db)

            async def __prepare__(self, item_id: int):
                self.item = self.db["items"].get(item_id)

            async def get(self) -> ItemSchema | None:
                return self.item

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items/1")
        assert response.status_code == 200
        assert response.json() == {"id": 1, "name": "Test"}

    def test_annotated_class_dependency(self):
        """Class-level dependency using Annotated syntax works."""

        class ItemView(BaseView):
            db: Annotated[dict, Depends(get_item_db)]

            async def get(self) -> list[ItemSchema]:
                return self.db["items"]

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        assert response.status_code == 200
        assert response.json() == [{"id": 1, "name": "Test"}]

    def test_annotated_method_query_param(self):
        """Method parameter using Annotated with Query works."""

        class ItemView(BaseView):
            async def get(
                self,
                limit: Annotated[int, Query(ge=1, le=100)] = 10,
            ) -> list[ItemSchema]:
                return [ItemSchema(id=i, name=f"Item {i}") for i in range(limit)]

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items?limit=2")
        assert response.status_code == 200
        assert len(response.json()) == 2

        # Query validation still works
        response = client.get("/items?limit=0")
        assert response.status_code == 422

    def test_annotated_method_depends(self):
        """Method parameter using Annotated with Depends works."""

        class ItemView(BaseView):
            async def get(self, params: Annotated[FilterParams, Depends()]) -> dict:
                return {"limit": params.limit, "offset": params.offset}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items?limit=5&offset=2")
        assert response.status_code == 200
        assert response.json() == {"limit": 5, "offset": 2}

    def test_annotated_prepare_path_param(self):
        """Annotated[int, Path()] in __prepare__ works."""

        class ItemView(BaseView):
            async def __prepare__(self, item_id: Annotated[int, Path(ge=1)]):
                self.item = ItemSchema(id=item_id, name=f"Item {item_id}")

            async def get(self) -> ItemSchema:
                return self.item

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items/5")
        assert response.status_code == 200
        assert response.json() == {"id": 5, "name": "Item 5"}

        # Path validation rejects invalid values
        response = client.get("/items/0")
        assert response.status_code == 422

    def test_security_scheme_class_dependency(self):
        """HTTPBearer security scheme as Annotated class-level dep works."""

        class ProtectedView(BaseView):
            credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]

            async def get(self) -> dict:
                return {"token": self.credentials.credentials}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/protected", ProtectedView)
        app.include_router(router)

        client = TestClient(app)

        # Missing auth is rejected
        response = client.get("/protected")
        assert response.status_code in (401, 403)

        # Valid bearer token works
        response = client.get(
            "/protected",
            headers={"Authorization": "Bearer my-secret-token"},
        )
        assert response.status_code == 200
        assert response.json() == {"token": "my-secret-token"}

    def test_security_scheme_with_prepare(self):
        """Security dep + __prepare__ with path param work together."""

        class ProtectedItemView(BaseView):
            credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]

            async def __prepare__(self, item_id: int):
                self.item_id = item_id

            async def get(self) -> dict:
                return {
                    "item_id": self.item_id,
                    "token": self.credentials.credentials,
                }

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ProtectedItemView)
        app.include_router(router)

        client = TestClient(app)

        response = client.get("/items/42")
        assert response.status_code in (401, 403)

        response = client.get(
            "/items/42",
            headers={"Authorization": "Bearer tok123"},
        )
        assert response.status_code == 200
        assert response.json() == {"item_id": 42, "token": "tok123"}
