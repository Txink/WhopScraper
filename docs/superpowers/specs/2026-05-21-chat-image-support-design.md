# Chat Image Support — Design

**Date:** 2026-05-21
**Branch:** `chat-component-isolation` (current)

## Goal

Whop chat messages can carry images (inside a `[data-attachment-id]` block in
the DOM). Today, the live extractor only uses the presence of an attachment as
a filter signal — image-only messages are dropped, and no image URL is
extracted. This spec adds end-to-end image support: parse, persist, serve,
render.

Specifically:

1. Parse the image URL from the `<img>` tag inside the message DOM.
2. Download the image at scrape time and persist it to local disk (Whop's
   signed S3 URLs expire after ~24h, so storing only the URL would mean every
   image >24h old breaks).
3. Render the image inside the chat bubble, above any text content.
4. Allow image-only messages (no caption) to flow through the pipeline.

## Out of scope

- Multiple images per message (single image only — `image_url: string | null`).
- Non-image attachments (video, file, etc.).
- Image lightbox / fullscreen view.
- Disk eviction / garbage collection for cached images.
- Migrating historical messages that pre-date this change. Old rows simply have
  no image; nothing to backfill.
- Editing/updating `scraper/message_extractor.py` (legacy test path, not in
  the live pipeline).

## Reference HTML

The DOM structure we parse is in the user-supplied snippet in chat. The
key locators are:

- Message element: `[data-message-id]` (already used by the existing
  extractor).
- Attachment block: descendant `[data-attachment-id]`.
- Image: descendant `img` with `src` matching `whop.com`. The `src` attribute
  points directly at the largest variant (the `srcset` has lower-resolution
  alternatives, which we don't need).

Example URL:
```
https://img-v2-prod.whop.com/unsafe/rs:fit:3840:0/plain/https%3A%2F%2F...
  ...png%3FX-Amz-...Expires%3D86400%26X-Amz-Signature%3D...
```

The `X-Amz-Expires=86400` is the 24h expiry that motivates local caching.

## Data flow

```
Whop DOM
  └─ [data-attachment-id] > img[src*="whop.com"]
       │
       ▼
extractor._extract_image_url(msg_el) → str | None
       │
       ▼
domain.Message(image_url=<remote url>)   ← transient, only on the event
       │
       ▼  CHAT_MESSAGE_RECEIVED
       │
chat_writer._handler:
  ├─ if msg.image_url: await _download_image(msg.id, msg.image_url)
  │     → writes data/chat-images/<msg_id>.<ext>, returns filename or None
  └─ upsert ChatMessageRow(image_filename=<filename> | None)
       │
       ▼  CHAT_MESSAGE_STORED (live only)
       │
GET /api/whop/pages/{page_id}/chat-messages
  └─ ChatMessageOut(image_url="/api/chat-images/<msg_id>" | null)
       │
       ▼
Frontend renders <img src=image_url> inside PlainBubble
```

The download is **synchronous within `chat_writer._handler`** (Approach A from
brainstorming). The writer is already a separate subscriber from the extractor,
so blocking on the download only delays the `CHAT_MESSAGE_STORED` broadcast
for this one message — it does not stall message extraction.

## Backend changes

### `backend/app/whop/extractor.py`

- New helper `_extract_image_url(msg_el: BeautifulSoup tag) -> str | None`:
  - Find the first descendant matching `[data-attachment-id]`.
  - Within it, find the first `img[src*="whop.com"]`.
  - Return `src` (or `None`).
- Replace the current image-only-skip guard at **lines 577-582**:
  - Old: detect `has_attachment`; skip if also no real content.
  - New: extract `image_url`; pass to `Message(...)`; skip only if **both**
    `content` is empty/metadata AND `image_url` is `None`.

### `backend/app/domain/message.py`

- Add `image_url: str | None = None` to the `Message` dataclass.

### `backend/app/storage/schema.py`

- Add `image_filename: Mapped[str | None]` column to `ChatMessageRow`. Store
  only the filename (e.g., `post_1CbE4Lcw7sLL2ze9wsR3Xg.avif`), not the full
  path, so the data directory can move without invalidating rows.

### Migration

- Inspect the current migration mechanism (Alembic? hand-rolled CREATE TABLE
  with `IF NOT EXISTS`?) and follow it. If the schema is created idempotently
  at boot via SQLAlchemy `metadata.create_all`, that handles new installs;
  for existing DBs add an `ALTER TABLE chat_messages ADD COLUMN
  image_filename TEXT NULL` shim in the startup migration step.

### `backend/app/whop/chat_writer.py`

- `_row_from_message(page_id, msg, image_filename)` — accept the new
  `image_filename` argument and assign it on the row.
- New private async helper `_download_image(msg_id: str, remote_url: str,
  data_dir: Path) -> str | None`:
  - `httpx.AsyncClient(timeout=10s)` GET.
  - Map response `Content-Type` to file extension:
    - `image/avif` → `.avif`
    - `image/png` → `.png`
    - `image/jpeg` → `.jpg`
    - `image/webp` → `.webp`
    - default → `.bin`
  - Write bytes to `<data_dir>/chat-images/<msg_id><ext>`.
  - Return filename (relative to `data_dir/chat-images/`).
  - Catch all exceptions, log warning, return `None`.
- In `_handler`:
  - Resolve `data_dir` (likely via existing settings / app state).
  - If `payload.message.image_url`: `filename = await _download_image(...)`,
    else `filename = None`.
  - Pass `filename` into `_row_from_message`.

### `backend/app/api/schemas.py`

- Add `image_url: str | None = None` to `ChatMessageOut`.

### `backend/app/api/http.py`

- `_row_to_chat_out(row)` — if `row.image_filename`:
  `image_url = f"/api/chat-images/{row.id}"`; else `image_url = None`.
- New route `GET /api/chat-images/{message_id}`:
  - Look up `ChatMessageRow` by id.
  - If no row or `image_filename` is `None` → 404.
  - Otherwise return `FileResponse(data_dir / "chat-images" / filename,
    media_type=<from extension>)`.

## Frontend changes

### `frontend/src/components/Chat/chatCards.ts`

- Add `image_url?: string | null` to `ChatMessageOut`.

### `frontend/src/components/Chat/PlainBubble.tsx`

- Add `imageUrl?: string | null` prop.
- Render order inside the bubble:
  1. Quoted block (existing).
  2. `<img src={imageUrl}>` if set.
  3. `{content}` if non-empty.
- If `content` is empty and `imageUrl` is set, the bubble is image-only —
  remove text padding so the image fills the bubble.

### `frontend/src/components/Chat/ChatMessage.tsx`

- Pass `imageUrl={m.image_url}` to `PlainBubble`.

### `frontend/src/components/Chat/ChatCard.tsx`

- In `renderBlock`, render the image inside the existing `chat-group-bubble`
  div, above `{m.content}`. (`ChatCard` does not use `PlainBubble` directly —
  inline the image markup here to keep behavior identical.)

### CSS

- `.chat-group-bubble img`: `max-width: 100%; max-height: 360px;
  border-radius: 8px; display: block;`
- Image-only bubble (no text): tighten padding so the image looks framed.

## Edge cases

| Case | Behavior |
|---|---|
| Download fails (network / 403 / timeout) | Log warning; row written with `image_filename=None`; frontend renders text-only. If content is also empty AND image_filename is None, skip the row at insert time (same "skip empty message" guard as today) — no orphan empty bubbles. |
| Historical replay with expired signed URLs | Same as above — download fails (403), message renders without image. |
| Duplicate scrapes of same `msg_id` | `upsert_chat_message` is idempotent. Download overwrites same path — also idempotent. |
| Disk fills up | Out of scope. Operator can manually `rm -rf data/chat-images/`. |
| Concurrent downloads of same id | Theoretically possible, harmless — same bytes to same path. |
| `srcset` with multiple resolutions | Ignored — `src` already points to the largest variant. |
| Message with `data-attachment-id` but no `img.whop.com` (other attachment type) | `_extract_image_url` returns `None`, treated as text-only message. |

## Testing

- **Unit** — `backend/app/whop/extractor_test.py` (or wherever the existing
  extractor tests live):
  - `_extract_image_url` against the user-supplied HTML fixture → returns the
    expected URL.
  - `_extract_image_url` against a text-only message → returns `None`.
  - End-to-end extract → `Message.image_url` populated; image-only messages
    no longer dropped.
- **Unit** — `backend/app/whop/chat_writer_test.py`:
  - `_download_image` happy path (mock httpx, assert file written, correct
    extension from Content-Type).
  - `_download_image` 403/timeout/network error → returns `None`, no file.
  - `_handler` end-to-end: publishing `CHAT_MESSAGE_RECEIVED` with
    `image_url` set produces a row with `image_filename` and a file on disk.
- **Frontend** — extend `PlainBubble.test.tsx`:
  - Renders `<img>` when `imageUrl` is set.
  - Image-only mode (no content) renders bubble without text.
  - Regular text mode (no image) unchanged.
