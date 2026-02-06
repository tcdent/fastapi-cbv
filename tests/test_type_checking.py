"""Tests for ``TYPE_CHECKING``-guarded imports on class-level dependencies.

This file uses both ``from __future__ import annotations`` and
``if TYPE_CHECKING:`` to guard dependency type annotations.  At runtime
the guarded names do not exist, so ``get_type_hints()`` cannot resolve
them.  The library must fall back gracefully and still let FastAPI
handle the ``Depends`` default values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fastcbv import APIRouter, BaseView

if TYPE_CHECKING:
    from pydantic import BaseModel


# ── Dependency factories (runtime) ──────────────────────────────────


class FakeDB:
    """Stands in for a real database session at runtime."""

    def __init__(self, items: dict | None = None):
        self.items = items or {
            1: {"id": 1, "name": "Test Item"},
            2: {"id": 2, "name": "Another Item"},
        }

    def get(self, item_id: int) -> dict | None:
        return self.items.get(item_id)

    def all(self) -> list[dict]:
        return list(self.items.values())


def get_db() -> FakeDB:
    return FakeDB()


class FakeCache:
    """Stands in for a cache backend."""

    def __init__(self):
        self.store: dict = {}

    def set(self, key: str, value: str) -> None:
        self.store[key] = value

    def get(self, key: str) -> str | None:
        return self.store.get(key)


def get_cache() -> FakeCache:
    return FakeCache()


# ── Tests ───────────────────────────────────────────────────────────


class TestTypeCheckingClassDeps:
    """Class-level dependencies whose type annotations are only
    available under ``TYPE_CHECKING`` still work at runtime.
    """

    def test_single_dep(self):
        class ItemView(BaseView):
            db: BaseModel = Depends(get_db)

            async def get(self) -> dict:
                return {"items": self.db.all()}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        assert response.status_code == 200
        assert len(response.json()["items"]) == 2

    def test_dep_used_in_prepare(self):
        class ItemView(BaseView):
            db: BaseModel = Depends(get_db)

            async def __prepare__(self, item_id: int):
                self.item = self.db.get(item_id)

            async def get(self) -> dict:
                if self.item is None:
                    return {"error": "not found"}
                return self.item

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items/1")
        assert response.status_code == 200
        assert response.json() == {"id": 1, "name": "Test Item"}

    def test_multiple_deps(self):
        class ItemView(BaseView):
            db: BaseModel = Depends(get_db)
            cache: BaseModel = Depends(get_cache)

            async def get(self, item_id: int) -> dict:
                cached = self.cache.get(f"item:{item_id}")
                if cached:
                    return {"source": "cache", "name": cached}
                item = self.db.get(item_id)
                if item:
                    self.cache.set(f"item:{item_id}", item["name"])
                    return {"source": "db", "name": item["name"]}
                return {"error": "not found"}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items/1")
        assert response.status_code == 200
        assert response.json() == {"source": "db", "name": "Test Item"}

    def test_inherited_dep(self):
        class DatabaseView(BaseView):
            db: BaseModel = Depends(get_db)

        class ItemView(DatabaseView):
            async def get(self) -> dict:
                return {"items": self.db.all()}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        assert response.status_code == 200
        assert len(response.json()["items"]) == 2

    def test_inherited_dep_with_child_dep(self):
        class DatabaseView(BaseView):
            db: BaseModel = Depends(get_db)

        class CachedItemView(DatabaseView):
            cache: BaseModel = Depends(get_cache)

            async def get(self, item_id: int) -> dict:
                item = self.db.get(item_id)
                if item:
                    self.cache.set(f"item:{item_id}", item["name"])
                return {"item": item, "cached": self.cache.get(f"item:{item_id}")}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", CachedItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items/1")
        assert response.status_code == 200
        data = response.json()
        assert data["item"] == {"id": 1, "name": "Test Item"}
        assert data["cached"] == "Test Item"

    def test_multiple_methods(self):
        class ItemView(BaseView):
            db: BaseModel = Depends(get_db)

            async def get(self) -> dict:
                return {"items": self.db.all()}

            async def post(self, name: str) -> dict:
                new_id = max(self.db.items.keys()) + 1
                item = {"id": new_id, "name": name}
                self.db.items[new_id] = item
                return item

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        assert client.get("/items").status_code == 200
        assert client.post("/items?name=New").status_code == 200
