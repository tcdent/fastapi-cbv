"""Integration tests using FastAPI TestClient."""

from __future__ import annotations

import pytest
from fastapi import BackgroundTasks, Depends, FastAPI
from fastapi.testclient import TestClient

from fastcbv import APIRouter, BaseView, status_code


def get_db():
    """Fake database dependency."""
    return {"items": {1: {"id": 1, "name": "Test Item"}, 2: {"id": 2, "name": "Another Item"}}}


class TestBasicView:
    """Tests for basic view functionality."""

    def test_get_request(self):
        class ItemView(BaseView):
            async def get(self) -> dict:
                return {"message": "hello"}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        assert response.status_code == 200
        assert response.json() == {"message": "hello"}

    def test_post_request(self):
        class ItemView(BaseView):
            async def post(self, name: str) -> dict:
                return {"name": name}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.post("/items?name=test")
        assert response.status_code == 200
        assert response.json() == {"name": "test"}

    def test_multiple_methods(self):
        class ItemView(BaseView):
            async def get(self) -> dict:
                return {"method": "get"}

            async def post(self) -> dict:
                return {"method": "post"}

            async def delete(self) -> dict:
                return {"method": "delete"}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        assert client.get("/items").json() == {"method": "get"}
        assert client.post("/items").json() == {"method": "post"}
        assert client.delete("/items").json() == {"method": "delete"}


class TestPathParameters:
    """Tests for path parameter handling."""

    def test_path_param_in_prepare(self):
        class ItemView(BaseView):
            async def __prepare__(self, item_id: int):
                self.item_id = item_id

            async def get(self) -> dict:
                return {"item_id": self.item_id}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items/42")
        assert response.status_code == 200
        assert response.json() == {"item_id": 42}

    def test_path_param_in_method(self):
        class ItemView(BaseView):
            async def get(self, item_id: int) -> dict:
                return {"item_id": item_id}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items/99")
        assert response.status_code == 200
        assert response.json() == {"item_id": 99}


class TestDependencies:
    """Tests for dependency injection."""

    def test_class_level_dependency(self):
        class ItemView(BaseView):
            db: dict = Depends(get_db)

            async def get(self) -> list:
                return list(self.db["items"].values())

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_dependency_with_prepare(self):
        class ItemView(BaseView):
            db: dict = Depends(get_db)

            async def __prepare__(self, item_id: int):
                self.item = self.db["items"].get(item_id)

            async def get(self) -> dict | None:
                return self.item

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items/1")
        assert response.status_code == 200
        assert response.json() == {"id": 1, "name": "Test Item"}


class TestStatusCodes:
    """Tests for custom status codes."""

    def test_default_status_200(self):
        class ItemView(BaseView):
            async def get(self) -> dict:
                return {}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        assert response.status_code == 200

    def test_custom_status_201(self):
        class ItemView(BaseView):
            @status_code(201)
            async def post(self) -> dict:
                return {"created": True}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.post("/items")
        assert response.status_code == 201

    def test_custom_status_204(self):
        class ItemView(BaseView):
            @status_code(204)
            async def delete(self):
                pass

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.delete("/items")
        assert response.status_code == 204


class TestRouterOptions:
    """Tests for router configuration options."""

    def test_router_prefix(self):
        class ItemView(BaseView):
            async def get(self) -> dict:
                return {}

        app = FastAPI()
        router = APIRouter(prefix="/api/v1")
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        assert client.get("/api/v1/items").status_code == 200
        assert client.get("/items").status_code == 404

    def test_view_tags(self):
        class ItemView(BaseView):
            async def get(self) -> dict:
                return {}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView, tags=["items"])
        app.include_router(router)

        # Check OpenAPI schema for tags
        client = TestClient(app)
        schema = client.get("/openapi.json").json()
        assert schema["paths"]["/items"]["get"]["tags"] == ["items"]

    def test_filter_methods(self):
        class ItemView(BaseView):
            async def get(self) -> dict:
                return {"method": "get"}

            async def post(self) -> dict:
                return {"method": "post"}

            async def delete(self) -> dict:
                return {"method": "delete"}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView, methods=["get", "post"])
        app.include_router(router)

        client = TestClient(app)
        assert client.get("/items").status_code == 200
        assert client.post("/items").status_code == 200
        assert client.delete("/items").status_code == 405  # Method not allowed


class TestPrepareHook:
    """Tests for __prepare__ hook."""

    def test_prepare_runs_before_method(self):
        call_order = []

        class ItemView(BaseView):
            async def __prepare__(self):
                call_order.append("prepare")

            async def get(self) -> dict:
                call_order.append("get")
                return {}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        client.get("/items")
        assert call_order == ["prepare", "get"]

    def test_prepare_sets_instance_attributes(self):
        class ItemView(BaseView):
            async def __prepare__(self, value: int):
                self.computed = value * 2

            async def get(self) -> dict:
                return {"computed": self.computed}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{value}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items/5")
        assert response.json() == {"computed": 10}

    def test_prepare_shared_across_methods(self):
        class ItemView(BaseView):
            async def __prepare__(self, item_id: int):
                self.item_id = item_id

            async def get(self) -> dict:
                return {"action": "get", "item_id": self.item_id}

            async def delete(self) -> dict:
                return {"action": "delete", "item_id": self.item_id}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        assert client.get("/items/1").json() == {"action": "get", "item_id": 1}
        assert client.delete("/items/2").json() == {"action": "delete", "item_id": 2}

    def test_prepare_raises_http_exception(self):
        from fastapi import HTTPException

        class ProtectedView(BaseView):
            async def __prepare__(self):
                # Simulate auth check failure
                raise HTTPException(status_code=401, detail="Not authenticated")

            async def get(self) -> dict:
                return {"secret": "data"}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/protected", ProtectedView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/protected")
        assert response.status_code == 401
        assert response.json()["detail"] == "Not authenticated"

    def test_prepare_auth_check_with_header(self):
        from fastapi import HTTPException

        class ProtectedView(BaseView):
            async def __prepare__(self):
                auth = self.request.headers.get("authorization")
                if auth != "Bearer valid-token":
                    raise HTTPException(status_code=401, detail="Invalid token")

            async def get(self) -> dict:
                return {"secret": "data"}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/protected", ProtectedView)
        app.include_router(router)

        client = TestClient(app)

        # Without auth header
        response = client.get("/protected")
        assert response.status_code == 401

        # With invalid token
        response = client.get("/protected", headers={"Authorization": "Bearer bad-token"})
        assert response.status_code == 401

        # With valid token
        response = client.get("/protected", headers={"Authorization": "Bearer valid-token"})
        assert response.status_code == 200
        assert response.json() == {"secret": "data"}


class TestRequestAccess:
    """Tests for request object access."""

    def test_request_available(self):
        class ItemView(BaseView):
            async def get(self) -> dict:
                return {
                    "method": self.request.method,
                    "url": str(self.request.url),
                }

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        data = response.json()
        assert data["method"] == "GET"
        assert "/items" in data["url"]

    def test_request_headers(self):
        class ItemView(BaseView):
            async def get(self) -> dict:
                return {"user_agent": self.request.headers.get("user-agent", "")}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items", headers={"User-Agent": "TestClient"})
        assert "TestClient" in response.json()["user_agent"]


class TestViewDecorator:
    """Tests for @router.view decorator."""

    def test_view_decorator_basic(self):
        app = FastAPI()
        router = APIRouter()

        @router.view("/items")
        class ItemView(BaseView):
            async def get(self) -> dict:
                return {"message": "hello"}

        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        assert response.status_code == 200
        assert response.json() == {"message": "hello"}

    def test_view_decorator_with_options(self):
        app = FastAPI()
        router = APIRouter()

        @router.view("/items", tags=["items"])
        class ItemView(BaseView):
            async def get(self) -> dict:
                return {"message": "hello"}

        app.include_router(router)

        client = TestClient(app)
        schema = client.get("/openapi.json").json()
        assert schema["paths"]["/items"]["get"]["tags"] == ["items"]

    def test_view_decorator_returns_class(self):
        router = APIRouter()

        @router.view("/items")
        class ItemView(BaseView):
            async def get(self) -> dict:
                return {}

        # Decorator should return the class unchanged
        assert ItemView.__name__ == "ItemView"
        assert issubclass(ItemView, BaseView)


class TestViewInheritance:
    """Tests for view class inheritance patterns."""

    def test_inherited_prepare_auth(self):
        from fastapi import HTTPException

        class AuthenticatedView(BaseView):
            """Base view that requires authentication."""

            async def __prepare__(self):
                auth = self.request.headers.get("authorization")
                if not auth or not auth.startswith("Bearer "):
                    raise HTTPException(status_code=401, detail="Not authenticated")
                self.token = auth.replace("Bearer ", "")

        class UserProfileView(AuthenticatedView):
            async def get(self) -> dict:
                return {"profile": "data", "token": self.token}

        class UserSettingsView(AuthenticatedView):
            async def get(self) -> dict:
                return {"settings": "data", "token": self.token}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/profile", UserProfileView)
        router.add_view("/settings", UserSettingsView)
        app.include_router(router)

        client = TestClient(app)

        # Both endpoints reject unauthenticated requests
        assert client.get("/profile").status_code == 401
        assert client.get("/settings").status_code == 401

        # Both endpoints work with valid auth
        headers = {"Authorization": "Bearer my-token"}
        assert client.get("/profile", headers=headers).json() == {"profile": "data", "token": "my-token"}
        assert client.get("/settings", headers=headers).json() == {"settings": "data", "token": "my-token"}

    def test_inherited_prepare_with_override(self):
        from fastapi import HTTPException

        class AuthenticatedView(BaseView):
            async def __prepare__(self):
                auth = self.request.headers.get("authorization")
                if not auth:
                    raise HTTPException(status_code=401, detail="Not authenticated")
                self.user_id = 123  # Simulated user lookup

        class ItemView(AuthenticatedView):
            async def __prepare__(self, item_id: int):  # type: ignore[override]
                await super().__prepare__()  # Call parent auth check
                self.item_id = item_id

            async def get(self) -> dict:
                return {"item_id": self.item_id, "user_id": self.user_id}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)

        # Unauthenticated request fails
        assert client.get("/items/42").status_code == 401

        # Authenticated request works
        response = client.get("/items/42", headers={"Authorization": "Bearer token"})
        assert response.status_code == 200
        assert response.json() == {"item_id": 42, "user_id": 123}

    def test_inherited_class_dependencies(self):
        def get_db():
            return {"connection": "active"}

        class DatabaseView(BaseView):
            db: dict = Depends(get_db)

        class ItemView(DatabaseView):
            async def get(self) -> dict:
                return {"db_status": self.db["connection"]}

        class UserView(DatabaseView):
            async def get(self) -> dict:
                return {"db_status": self.db["connection"], "type": "user"}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        router.add_view("/users", UserView)
        app.include_router(router)

        client = TestClient(app)
        assert client.get("/items").json() == {"db_status": "active"}
        assert client.get("/users").json() == {"db_status": "active", "type": "user"}

    def test_helper_methods_on_view(self):
        class ItemView(BaseView):
            async def __prepare__(self, item_id: int):
                self.item_id = item_id

            def _format_response(self, data: dict) -> dict:
                return {"item_id": self.item_id, "data": data}

            async def _load_item(self) -> dict:
                # Simulate async database lookup
                return {"name": f"Item {self.item_id}", "price": 9.99}

            async def get(self) -> dict:
                item = await self._load_item()
                return self._format_response(item)

            async def delete(self) -> dict:
                return self._format_response({"deleted": True})

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        assert client.get("/items/5").json() == {
            "item_id": 5,
            "data": {"name": "Item 5", "price": 9.99},
        }
        assert client.delete("/items/5").json() == {
            "item_id": 5,
            "data": {"deleted": True},
        }


class TestBackgroundTasks:
    """Tests for background_tasks as a class-level dependency."""

    def test_background_tasks_available(self):
        class ItemView(BaseView):
            background_tasks: BackgroundTasks

            async def get(self) -> dict:
                return {"has_tasks": self.background_tasks is not None}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/items")
        assert response.status_code == 200
        assert response.json() == {"has_tasks": True}

    def test_background_tasks_execute(self):
        results = []

        def log_action(message: str):
            results.append(message)

        class ItemView(BaseView):
            background_tasks: BackgroundTasks

            async def post(self) -> dict:
                self.background_tasks.add_task(log_action, "item_created")
                return {"status": "created"}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.post("/items")
        assert response.status_code == 200
        assert response.json() == {"status": "created"}
        assert results == ["item_created"]

    def test_background_tasks_multiple(self):
        results = []

        def log_action(message: str):
            results.append(message)

        class ItemView(BaseView):
            background_tasks: BackgroundTasks

            async def delete(self, item_id: int) -> dict:
                self.background_tasks.add_task(log_action, f"deleted:{item_id}")
                self.background_tasks.add_task(log_action, f"notified:{item_id}")
                return {"deleted": item_id}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.delete("/items/42")
        assert response.status_code == 200
        assert results == ["deleted:42", "notified:42"]

    def test_background_tasks_with_prepare(self):
        results = []

        def log_action(message: str):
            results.append(message)

        class ItemView(BaseView):
            background_tasks: BackgroundTasks

            async def __prepare__(self, item_id: int):
                self.item_id = item_id

            async def delete(self) -> dict:
                self.background_tasks.add_task(log_action, f"deleted:{self.item_id}")
                return {"deleted": self.item_id}

        app = FastAPI()
        router = APIRouter()
        router.add_view("/items/{item_id}", ItemView)
        app.include_router(router)

        client = TestClient(app)
        response = client.delete("/items/7")
        assert response.status_code == 200
        assert results == ["deleted:7"]
