# fastcbv

Class-based views for FastAPI.

## Installation

```bash
uv add fastcbv
```

## Quick Start

```python
from fastapi import FastAPI
from fastcbv import APIRouter, BaseView

app = FastAPI()
router = APIRouter()

@router.view("/items")
class ItemView(BaseView):
    async def get(self) -> dict:
        return {"message": "Hello, World!"}

    async def post(self, name: str) -> dict:
        return {"name": name}

app.include_router(router)
```

Or use `add_view()` if you prefer to keep all of your routes together:

```python
router.add_view("/items", ItemView, tags=["items"])
```

## Features

- Define HTTP methods as class methods (`get`, `post`, `put`, `patch`, `delete`, `head`, `options`)
- Class-level dependencies with FastAPI's `Depends` and `Annotated`
- `__prepare__` hook for shared setup logic across methods
- Full support for path parameters, query parameters, and request bodies
- Full support for `from __future__ import annotations`
- View inheritance for reusable patterns
- Access to the request object via `self.request`

## Basic Usage

### Simple View

```python
from fastcbv import APIRouter, BaseView

class HealthView(BaseView):
    async def get(self) -> dict:
        return {"status": "ok"}

router = APIRouter()
router.add_view("/health", HealthView)
```

### Path Parameters

Path parameters can be declared in method signatures:

```python
class ItemView(BaseView):
    async def get(self, item_id: int) -> dict:
        return {"item_id": item_id}

router.add_view("/items/{item_id}", ItemView)
```

### Class-Level Dependencies

Use `Annotated` with `Depends` as class attributes to share dependencies across all methods:

```python
from typing import Annotated
from fastapi import Depends

def get_db():
    return Database()

class ItemView(BaseView):
    db: Annotated[Database, Depends(get_db)]

    async def get(self, item_id: int) -> dict:
        return await self.db.get_item(item_id)

    async def delete(self, item_id: int) -> None:
        await self.db.delete_item(item_id)
```

### The `__prepare__` Hook

The `__prepare__` method runs before every HTTP method. Use it for common setup like loading resources:

```python
class ItemView(BaseView):
    db: Annotated[Database, Depends(get_db)]

    async def __prepare__(self, item_id: int) -> None:
        self.item = await self.db.get_item(item_id)
        if not self.item:
            raise HTTPException(status_code=404, detail="Item not found")

    async def get(self) -> dict:
        return self.item

    async def put(self, name: str) -> dict:
        self.item["name"] = name
        return self.item

    async def delete(self) -> None:
        await self.db.delete(self.item["id"])

router.add_view("/items/{item_id}", ItemView)
```

### Query Parameters

Use `Annotated` with `Query` for validated query parameters:

```python
from typing import Annotated
from fastapi import Query

class ItemView(BaseView):
    async def get(
        self,
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
    ) -> list[dict]:
        return await get_items(limit=limit)
```

### Custom Status Codes

Use the `@status_code` decorator to set response status codes:

```python
from fastcbv import BaseView, status_code

class ItemView(BaseView):
    @status_code(201)
    async def post(self, name: str) -> dict:
        return {"id": 1, "name": name}

    @status_code(204)
    async def delete(self, item_id: int) -> None:
        pass
```

## Patterns

### Authentication with Inheritance

Create a base view that handles authentication, then inherit from it:

```python
from fastapi import HTTPException
from fastcbv import BaseView

class AuthenticatedView(BaseView):
    """Base view that requires authentication."""

    async def __prepare__(self) -> None:
        auth = self.request.headers.get("authorization")
        if not auth or not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Not authenticated")

        self.token = auth.replace("Bearer ", "")
        self.user = await get_user_from_token(self.token)

class ProfileView(AuthenticatedView):
    async def get(self) -> dict:
        return {"user_id": self.user.id, "name": self.user.name}

class SettingsView(AuthenticatedView):
    async def get(self) -> dict:
        return {"user_id": self.user.id, "settings": self.user.settings}

    async def put(self, theme: str) -> dict:
        self.user.settings["theme"] = theme
        return {"settings": self.user.settings}
```

You can also extend `__prepare__` while calling the parent:

```python
class ItemView(AuthenticatedView):
    async def __prepare__(self, item_id: int) -> None:
        await super().__prepare__()  # Run auth check first
        self.item = await load_item(item_id)

    async def get(self) -> dict:
        return {"item": self.item, "user": self.user.id}
```

### Shared Dependencies via Inheritance

```python
class DatabaseView(BaseView):
    """Base view with database access."""
    db: Annotated[Database, Depends(get_db)]

class ItemView(DatabaseView):
    async def get(self) -> list:
        return await self.db.get_all_items()

class UserView(DatabaseView):
    async def get(self) -> list:
        return await self.db.get_all_users()
```

### Views with Helper Methods

Organize complex logic using helper methods. Methods starting with `_` are ignored by the router:

```python
class OrderView(BaseView):
    db: Annotated[Database, Depends(get_db)]

    async def __prepare__(self, order_id: int) -> None:
        self.order = await self.db.get_order(order_id)
        if not self.order:
            raise HTTPException(status_code=404)

    def _calculate_total(self) -> float:
        """Helper method for price calculation."""
        subtotal = sum(item["price"] * item["qty"] for item in self.order["items"])
        tax = subtotal * 0.08
        return subtotal + tax

    async def _send_notification(self, message: str) -> None:
        """Async helper for notifications."""
        await notify_user(self.order["user_id"], message)

    async def get(self) -> dict:
        return {
            **self.order,
            "total": self._calculate_total(),
        }

    @status_code(200)
    async def post(self, action: str) -> dict:
        if action == "complete":
            self.order["status"] = "completed"
            await self._send_notification("Your order is complete!")
        return self.order
```

### Accessing the Request

The request object is available via `self.request`:

```python
class ItemView(BaseView):
    async def get(self) -> dict:
        user_agent = self.request.headers.get("user-agent", "")
        client_ip = self.request.client.host
        return {"user_agent": user_agent, "ip": client_ip}
```

Properties are useful for cleanly accessing request state:

```python
class ItemView(BaseView):
    @property
    def current_user_id(self) -> str | None:
        """Extract user ID from request state (set by auth middleware)."""
        return getattr(self.request.state, "user_id", None)

    @property
    def is_admin(self) -> bool:
        """Check admin status from request state."""
        return getattr(self.request.state, "is_admin", False)

    async def get(self) -> dict:
        return {"user_id": self.current_user_id, "admin": self.is_admin}

    async def delete(self) -> None:
        if not self.is_admin:
            raise HTTPException(status_code=403, detail="Admin required")
        # ... delete logic
```

### Background Tasks

Add FastAPI's `BackgroundTasks` as a class-level dependency to schedule work after the response is sent:

```python
from fastapi import BackgroundTasks

class OrderView(BaseView):
    background_tasks: BackgroundTasks
    db: Annotated[Database, Depends(get_db)]

    @status_code(201)
    async def post(self, name: str) -> dict:
        order = await self.db.create_order(name)
        self.background_tasks.add_task(send_confirmation_email, order.email)
        self.background_tasks.add_task(update_inventory, order.items)
        return order
```

## Router Options

### Tags and Prefix

```python
router = APIRouter(prefix="/api/v1")
router.add_view("/items", ItemView, tags=["items"])
```

### Filter Methods

Register only specific HTTP methods:

```python
router.add_view("/items", ItemView, methods=["get", "post"])
```

### Route Dependencies

Apply dependencies to all methods in a view:

```python
router.add_view(
    "/admin/items",
    AdminItemView,
    dependencies=[Depends(require_admin)],
)
```

## API Reference

### `BaseView`

Base class for all views. Provides:

- `self.request` - The FastAPI/Starlette `Request` object
- `__prepare__(*args, **kwargs)` - Override to add setup logic

### `APIRouter`

Extended FastAPI router with `add_view()` method.

The `APIRouter` from `fastcbv` is a drop-in replacement for FastAPI's `APIRouter`. All existing routes, decorators, and configurations work unchanged—just swap the import and start using `add_view()` alongside your existing routes:

```python
# Before
from fastapi import APIRouter

# After
from fastcbv import APIRouter

router = APIRouter(prefix="/api")

# Existing function-based routes still work
@router.get("/health")
async def health():
    return {"status": "ok"}

# Add class-based views alongside them
@router.view("/items/{item_id}")
class ItemView(BaseView):
    async def get(self, item_id: int) -> dict:
        return {"item_id": item_id}
```

#### `@router.view(path, **options)` (decorator)

Decorator to register a class-based view. Accepts all the same options as `add_view()`:

```python
@router.view("/items/{item_id}", tags=["items"], dependencies=[Depends(auth)])
class ItemView(BaseView):
    async def get(self, item_id: int) -> dict:
        return {"item_id": item_id}
```

#### `add_view(path, view, **options)`

The `add_view` method accepts most parameters from FastAPI's `add_api_route`, making it familiar and compatible. Parameters that are method-specific (like `status_code`) or handled automatically (like `endpoint` and `response_model`) are excluded.

| Parameter | Type | Description |
|-----------|------|-------------|
| `path` | `str` | URL path for the view |
| `view` | `type[BaseView]` | View class to register |
| `methods` | `list[str]` | HTTP methods to register (default: auto-detect) |
| `name_prefix` | `str` | Prefix for route names (default: class name) |
| `tags` | `list[str \| Enum]` | OpenAPI tags |
| `dependencies` | `Sequence[Depends]` | Dependencies for all methods |
| `responses` | `dict[int \| str, dict]` | Additional OpenAPI responses |
| `deprecated` | `bool` | Mark all methods as deprecated |
| `include_in_schema` | `bool` | Include in OpenAPI schema |
| `callbacks` | `list[BaseRoute]` | OpenAPI callbacks |
| `openapi_extra` | `dict` | Additional OpenAPI metadata |

### `@status_code(code)`

Decorator to set the HTTP status code for a method.

Most route parameters can be configured at the router level (`tags`, `dependencies`, `responses`, `deprecated`) or derived from the method signature (parameters, return type). However, `status_code` is unique—it's method-specific and can't be inferred or set globally. The `@status_code` decorator provides a clean way to set this per-method:

```python
from fastcbv import BaseView, status_code

class ItemView(BaseView):
    async def get(self, item_id: int) -> dict:
        """Default 200 status code."""
        return {"id": item_id}

    @status_code(201)
    async def post(self, name: str) -> dict:
        """201 Created for new resources."""
        return {"id": 1, "name": name}

    @status_code(204)
    async def delete(self, item_id: int) -> None:
        """204 No Content for deletions."""
        pass

    @status_code(202)
    async def put(self, item_id: int) -> dict:
        """202 Accepted for async processing."""
        return {"id": item_id, "status": "processing"}
```

Without the decorator, methods return `200 OK` by default.

## License

MIT
