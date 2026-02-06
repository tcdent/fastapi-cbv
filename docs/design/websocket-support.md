# WebSocket Support — UX Design

## Motivation

fastcbv organizes HTTP endpoints as class methods. WebSockets have a natural
lifecycle (connect, receive, disconnect) that maps well to class methods too —
arguably better than HTTP does, since stuffing all three phases into a single
function leads to exactly the kind of branching that CBVs are designed to
eliminate.

## Design Principles

1. **The framework owns the lifecycle.** Connect, receive loop, disconnect are
   managed internally. The developer overrides hooks for the phases they care
   about.
2. **Sane defaults for the common case.** The primary use case is a persistent
   connection where the server pushes to an authenticated client. That should
   require near-zero boilerplate.
3. **`ConnectionManager` is built in.** Tracking connections and sending
   targeted messages is too common to leave as an exercise for the user.
4. **Don't outrun FastAPI.** FastAPI adds dependency injection to WebSockets
   and not much else over Starlette. The library should leverage `Depends` and
   `__prepare__`, not invent new abstractions.
5. **Scale later, same API.** The in-memory `ConnectionManager` covers
   single-process apps. A `Backend` protocol enables distributed delivery
   without changing application code.

## `WebSocketView`

A new base class, separate from `BaseView`. Different lifecycle, different
registration (`add_websocket_route` vs `add_api_route`), different mental
model — they shouldn't be mixed.

### Lifecycle

The framework manages the following sequence for each connection:

```
__prepare__()        →  resolve deps, auth, setup (can reject here)
on_connect()         →  default: accept the connection
                        register with manager (if present on the class)
    receive loop     →  on_receive() called per message
on_disconnect()      →  unregister from manager (if present)
                        user cleanup
```

### Hooks

All hooks are optional. Defaults are sane for the push-to-client case.

```python
class WebSocketView:
    encoding: str = "text"  # "text" | "bytes" | "json"

    async def on_connect(self, websocket: WebSocket):
        """Called after __prepare__. Default: accept the connection."""
        await websocket.accept()

    async def on_receive(self, websocket: WebSocket, data: str | bytes | Any):
        """Called per message. Data decoded per `encoding`. Not defined by
        default — omit for push-only endpoints."""
        pass

    async def on_disconnect(self, websocket: WebSocket, code: int):
        """Called on disconnect. Default: no-op."""
        pass
```

`encoding` determines how incoming messages are decoded:

| `encoding` | `data` type | Starlette method     |
|------------|-------------|----------------------|
| `"text"`   | `str`       | `receive_text()`     |
| `"bytes"`  | `bytes`     | `receive_bytes()`    |
| `"json"`   | `Any`       | `receive_json()`     |

### Return / yield from `on_receive`

Returning a value from `on_receive` sends it back to the client, encoded per
`encoding`. This eliminates direct `websocket.send_*()` calls in the common
request/response pattern:

```python
async def on_receive(self, websocket: WebSocket, data: dict):
    result = await process(data)
    return result  # framework sends it back
```

For streaming multiple frames in response to a single message:

```python
async def on_receive(self, websocket: WebSocket, data: dict):
    async for chunk in stream_response(data):
        yield chunk  # each yield sends a frame
```

The raw `websocket` is still available on `self.websocket` (and passed to the
hook) for cases that need direct control.

### Dependencies and `__prepare__`

Class-level `Depends` and `__prepare__` work identically to `BaseView`. This
is the primary value over raw Starlette WebSockets.

```python
@router.view("/live")
class LiveView(WebSocketView):
    db: Session = Depends(get_db)
    user: User = Depends(get_current_user)

    async def on_connect(self, websocket: WebSocket):
        await websocket.accept()
        self.manager.identify(websocket, self.user.id)

    async def on_receive(self, websocket: WebSocket, data: dict):
        result = await process(data, self.db)
        return result
```

Authentication is the developer's concern — handled through `Depends` or
`__prepare__`, not baked into the view or manager.

## `ConnectionManager`

An in-memory connection tracker. Handles the boilerplate that every WebSocket
app copies around.

### API

```python
manager = ConnectionManager()

# Lifecycle (called by the framework automatically when manager is
# present as a class attribute on a WebSocketView)
manager.connect(websocket)
manager.disconnect(websocket)

# Identity — opt-in, called by the developer
manager.identify(websocket, "user-42")

# Groups — opt-in
manager.add_to_group(websocket, "doc:789")
manager.remove_from_group(websocket, "doc:789")

# Sending
await manager.send("user-42", data)              # by id
await manager.broadcast(data)                     # to all
await manager.broadcast(data, group="doc:789")    # to group
```

### Encoding

Inferred from the data type passed to `send` / `broadcast`:

```python
await manager.send(id, "hello")         # send_text
await manager.send(id, b"\x00\x01")    # send_bytes
await manager.send(id, {"event": "x"}) # send_json
```

### Automatic integration with `WebSocketView`

When a `ConnectionManager` instance is a class attribute on a `WebSocketView`,
the framework automatically calls `connect` / `disconnect` at the appropriate
lifecycle points. The developer never manages this plumbing:

```python
@router.view("/notifications")
class NotificationView(WebSocketView):
    manager = ConnectionManager()
    user: User = Depends(get_current_user)

    async def on_connect(self, websocket: WebSocket):
        await websocket.accept()
        self.manager.identify(websocket, self.user.id)
```

That's a fully functional push endpoint. `manager.connect()` is called by the
framework before `on_connect`. `manager.disconnect()` is called after
`on_disconnect`. From anywhere else in the app:

```python
await manager.send(user_id, {"event": "task_complete", "url": url})
```

### Scaling: the `Backend` protocol

The in-memory manager is the complete solution for single-process apps. For
multi-process deployments, a `Backend` can be provided for cross-server
delivery.

The key insight: **not every message needs to go through the backend.** The
manager checks local connections first. The backend is only used when the
target connection lives on another server.

```python
# Single process — no backend needed
manager = ConnectionManager()

# Multi-process — same application code
manager = ConnectionManager(backend=RedisBackend("redis://..."))
```

The backend stores a lightweight registry (user → server mapping), not
messages. Updated only on connect/disconnect. Per-message flow:

1. `manager.send("user-42", data)` → is user-42 local? Send directly. Done.
2. Not local → look up server in backend registry → publish to that server's
   channel.

Each server subscribes to its own channel and only receives messages destined
for its local connections.

#### Protocol

```python
class Backend(Protocol):
    async def register(self, id: str, server_id: str) -> None: ...
    async def unregister(self, id: str, server_id: str) -> None: ...
    async def lookup(self, id: str) -> set[str]: ...
    async def publish(self, server_id: str, payload: bytes) -> None: ...
    async def subscribe(self, server_id: str) -> AsyncIterator[bytes]: ...
```

Five methods. Implementable with Redis, Postgres LISTEN/NOTIFY, NATS, or
anything else. The library may ship a `RedisBackend` as an optional extra
(`fastcbv[redis]`), but the protocol is simple enough to implement in ~30
lines for any message transport.

## Router integration

Registered through the same `@router.view()` decorator and `add_view()`. The
router detects the view type (`BaseView` vs `WebSocketView`) and calls
`add_api_route` or `add_websocket_route` accordingly.

```python
router = APIRouter()

@router.view("/items")
class ItemView(BaseView):
    async def get(self) -> list: ...

@router.view("/items/live")
class ItemStream(WebSocketView):
    async def on_receive(self, websocket: WebSocket, data: dict):
        return await process(data)
```

## Usage tiers

### Tier 1: Push-only (most common, minimal code)

Server pushes to authenticated clients. No incoming message handling.

```python
@router.view("/notifications")
class NotificationView(WebSocketView):
    manager = ConnectionManager()
    user: User = Depends(get_current_user)

    async def on_connect(self, websocket: WebSocket):
        await websocket.accept()
        self.manager.identify(websocket, self.user.id)

# Elsewhere:
await manager.send(user.id, {"event": "new_message", "from": sender})
```

### Tier 2: Interactive (request/response over WebSocket)

```python
@router.view("/rpc")
class RPCView(WebSocketView):
    encoding = "json"
    user: User = Depends(get_current_user)

    async def on_receive(self, websocket: WebSocket, data: dict):
        result = await dispatch_rpc(data["method"], data["params"])
        return {"id": data["id"], "result": result}
```

### Tier 3: Collaborative (groups, shared state)

```python
@router.view("/collab/{doc_id}")
class CollabView(WebSocketView):
    encoding = "json"
    manager = ConnectionManager()
    user: User = Depends(get_current_user)

    async def on_connect(self, websocket: WebSocket):
        await websocket.accept()
        self.manager.identify(websocket, self.user.id)
        self.manager.add_to_group(websocket, f"doc:{self.doc_id}")

    async def on_receive(self, websocket: WebSocket, data: dict):
        await self.manager.broadcast(data, group=f"doc:{self.doc_id}")

    async def on_disconnect(self, websocket: WebSocket, code: int):
        await save_cursor(self.user.id, self.doc_id)
```

### Tier 4: Raw (opt out of the lifecycle)

For cases where the framework's lifecycle doesn't fit, define a `ws` method
for full manual control:

```python
@router.view("/custom")
class CustomView(WebSocketView):
    async def ws(self, websocket: WebSocket):
        await websocket.accept()
        # full manual control — no lifecycle hooks, no manager
        async for message in websocket.iter_text():
            await websocket.send_text(f"echo: {message}")
```

When `ws` is defined, the framework skips the lifecycle hooks entirely and
delegates to it directly.

## What this does NOT cover

- **SSE (Server-Sent Events):** Already works with `BaseView` — just return a
  `StreamingResponse` from a `get` method. No new abstraction needed.
- **Message persistence / queuing:** Out of scope. Use a message broker.
- **Reconnection logic:** Client-side concern.
- **Rate limiting:** Middleware or dependency concern.
- **Binary protocol framing:** Use `encoding = "bytes"` and handle it yourself.
