# Message Image Lightbox — Design

**Status:** Draft
**Date:** 2026-05-22

## Goal

Let users click any image rendered in the frontend (starting with chat messages) to open a fullscreen viewer that supports Mac trackpad pinch-zoom and two-finger pan, and closes via Esc, backdrop click, or an explicit close button.

Today, message images render as plain `<img>` capped at `max-height: 360px` (see `frontend/src/components/Chat/ChatBoardPanel.css:137`). They are not interactive; users cannot see the original resolution or pan into detail.

## Scope

In scope:

- New reusable `ZoomableImage` component that replaces `<img>` at any site that wants click-to-zoom. Same prop shape as `<img>` (`src`, `alt`, `className`), so callers swap the tag and nothing else.
- New `ImageLightbox` overlay rendered via React portal when an image is opened.
- Wire `ZoomableImage` into the two current image render sites: `frontend/src/components/Chat/PlainBubble.tsx:25` and `frontend/src/components/Chat/ChatCard.tsx:105`.

Out of scope:

- Multi-image gallery / next-prev navigation (only one image at a time, no surrounding album to step through).
- Mouse-wheel zoom, click-and-drag pan, double-click toggle, on-screen +/− buttons — explicitly declined; the only zoom/pan input is the Mac trackpad gesture set.
- Mobile touch (pinch on touchscreen). The app is desktop-first; mobile is not a target for this iteration. A later iteration can add `pointer` / `touch` handlers if needed.
- Download / share / copy-link affordances.

## Interaction Model

### Open

- Single left-click anywhere on the image inside its host (chat bubble or card) opens the lightbox.
- Cursor over the host image is `zoom-in` so the affordance is discoverable.

### Initial layout

- The opened image fits within the viewport at `max-width: 90vw` and `max-height: 90vh` using `object-fit: contain`.
- Initial transform state: `scale = 1`, `translate = (0, 0)`.

### Zoom — Mac trackpad pinch only

- Listen for `wheel` events on the lightbox image with `event.ctrlKey === true`. macOS browsers (Safari, Chrome, Firefox) synthesize this event from a two-finger trackpad pinch.
- `event.preventDefault()` is required, otherwise the browser will perform a page zoom instead. The listener must therefore be attached non-passively (`addEventListener('wheel', handler, { passive: false })`).
- Scale step: `nextScale = scale * exp(-deltaY * 0.01)`. Clamp `nextScale` to `[0.5, 8]`.
- Anchor: zoom centers on the cursor position, not the image center. The image is rendered centered in the stage with `transform: translate(tx, ty) scale(s)` and `transform-origin: center center`, so a pre-transform image point `p` lands at `s·p + t` in stage-center coordinates. To keep the point currently under the cursor `c` (also measured from stage center) fixed after scaling to `s'`:

  ```
  p  = (c - t) / s
  t' = c - p · s'
  ```

### Pan — Mac trackpad two-finger drag only

- Listen for `wheel` events with `event.ctrlKey === false`. macOS synthesizes these from a two-finger drag on the trackpad.
- `event.preventDefault()` so the page behind the overlay does not scroll.
- Update translate: `translate += (-deltaX, -deltaY)` (the trackpad convention: drag fingers right → content moves right under them).
- Clamp translate so at least ~64px of the image always remains within the stage on each axis. For axis `x` with scaled image half-width `w/2` and stage half-width `S/2`, the bound is `|tx| ≤ S/2 + w/2 − 64`; same shape for `y`. At `scale = 1` with the image already smaller than the stage, this collapses to a small range around `0`, which is fine — there is nothing to pan toward anyway.

### Close

Any of:

- Press `Esc`.
- Click anywhere outside the image's rendered pixels (including the letterbox/empty areas of the overlay).
- Click the `×` button in the top-right corner of the overlay.

Click directly on the image's pixels does **not** close, so users do not lose their place during interaction. Implementation: attach the close handler to the backdrop, and stop click propagation on the `<img>` element itself (not on the surrounding stage container) so the letterbox area still closes.

### Body scroll lock

While the lightbox is open, set `document.body.style.overflow = 'hidden'` and restore on close.

### State reset

State is *not* persisted across opens. Every open starts fresh at `scale = 1`, `translate = (0, 0)`.

## Architecture

Two new files, plus call-site updates.

```
frontend/src/components/common/
├── ZoomableImage.tsx        // <img>-shaped wrapper that opens a lightbox on click
├── ZoomableImage.test.tsx
├── ImageLightbox.tsx        // Portal-rendered overlay, owns scale/translate state
├── ImageLightbox.test.tsx
└── ImageLightbox.css        // .image-lightbox-backdrop, .image-lightbox-stage, .image-lightbox-close
```

### `ZoomableImage`

```ts
interface ZoomableImageProps {
  src: string;
  alt?: string;
  className?: string;
}
```

- Renders an `<img>` with the given props, plus `style={{ cursor: 'zoom-in' }}` and an `onClick` that toggles internal `open` state.
- When `open` is true, renders `<ImageLightbox src={src} alt={alt} onClose={...} />` via `createPortal(..., document.body)`.
- Only one `ZoomableImage` in the document can be open at a time in practice (the first click locks body scroll; clicking through another image to open it would require closing the current one first). We do not enforce a global singleton — each instance owns its own open state. If two were somehow open, both would respond to Esc; this is acceptable because the UX path that produces two opens does not exist.

### `ImageLightbox`

```ts
interface ImageLightboxProps {
  src: string;
  alt?: string;
  onClose: () => void;
}
```

- State (via `useState` or `useReducer`): `scale: number`, `translate: { x: number; y: number }`.
- Refs: stage element (the centered container) and image element. Stage ref is used to compute pinch anchor offsets relative to its bounding rect.
- Effects:
  - On mount: lock body scroll; attach `keydown` listener on `window` for Esc; attach `wheel` listener on the stage element with `{ passive: false }`.
  - On unmount: restore body scroll; remove listeners.
- Render structure:
  ```
  <div class="image-lightbox-backdrop" onClick={onClose}>
    <button class="image-lightbox-close" onClick={onClose} aria-label="Close">×</button>
    <div class="image-lightbox-stage" ref={stageRef}>
      <img src=... onClick={stop} style={transform: translate(...) scale(...)} />
    </div>
  </div>
  ```
  Only the `<img>` itself stops click propagation; the stage container does not. That way clicks on the letterbox (transparent space inside the stage around the image) bubble up to the backdrop and close. The close `×` button also lives inside the backdrop; without `stopPropagation` its click triggers both its own `onClose` and the backdrop's `onClose`, but since both call the same function the net effect is identical to one close. No special handling required.

### Call-site updates

`frontend/src/components/Chat/PlainBubble.tsx:25` — replace:

```tsx
<img className="chat-group-image" src={authedAssetUrl(imageUrl)} alt="" />
```

with:

```tsx
<ZoomableImage className="chat-group-image" src={authedAssetUrl(imageUrl)} alt="" />
```

`frontend/src/components/Chat/ChatCard.tsx:105` — same swap.

No CSS changes to `.chat-group-image`; the new component leaves the host `<img>` rendering identical, so the `360px` cap and surrounding layout still apply.

## CSS Sketch

```css
.image-lightbox-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.85);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: default;
}

.image-lightbox-stage {
  /* Wraps the image so transforms apply relative to a known center. */
  display: flex;
  align-items: center;
  justify-content: center;
  width: 90vw;
  height: 90vh;
  overflow: hidden;
}

.image-lightbox-stage img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  transform-origin: center center;
  will-change: transform;
  user-select: none;
  -webkit-user-drag: none;
}

.image-lightbox-close {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 32px;
  height: 32px;
  border: 0;
  background: rgba(0, 0, 0, 0.4);
  color: white;
  font-size: 24px;
  line-height: 1;
  border-radius: 16px;
  cursor: pointer;
}
```

Z-index `1000` puts the overlay above the existing modal layer (`PageSettingsModal` uses unspecified default + backdrop, no other component currently sits above `999`).

## Error and Edge Cases

- **Image fails to load in the lightbox.** The `<img>` shows the browser's broken-image glyph. Acceptable — no error UI in this iteration. The image already loaded successfully in the host bubble (otherwise the user could not see it to click), so failure here is rare.
- **Image still loading when opened.** Browsers cache the URL, so the open is effectively instant. If not, the lightbox renders an empty stage that fills in. No spinner.
- **Open during a chat update.** The host bubble might unmount if the message is filtered out mid-view. `ZoomableImage` owns the `open` state on itself, so an unmount automatically closes the portal. Acceptable.
- **Multiple wheel events arriving fast.** State updates are based on the latest `scale`/`translate` snapshot inside the handler closure. To avoid stale-closure bugs, use the functional updater form: `setScale(prev => clamp(prev * factor, 0.5, 8))`. Same for translate.
- **Non-Mac users.** A Windows mouse wheel emits `wheel` without `ctrlKey`, which our handler treats as pan. So Windows users get a pan-only experience and no zoom. This is acceptable for the desktop-only-on-Mac context this app targets; a follow-up could add a separate `wheel`-as-zoom mode behind a setting if needed.

## Testing

Vitest + React Testing Library.

`ZoomableImage.test.tsx`:

- Renders an `<img>` with the given `src`, `alt`, `className`.
- Clicking the image opens the lightbox (assert lightbox role/test-id appears in `document.body`).

`ImageLightbox.test.tsx`:

- Pressing `Escape` calls `onClose`.
- Clicking the backdrop calls `onClose`.
- Clicking the `×` button calls `onClose`.
- Clicking the `<img>` element does NOT call `onClose`.
- Clicking the stage container's letterbox area DOES call `onClose` (clicks bubble through stage to backdrop).
- Dispatching a `wheel` event with `ctrlKey=true` and `deltaY=-100` increases `scale` (assert via inline `style.transform`).
- Dispatching a `wheel` event with `ctrlKey=false` and `deltaX=50` shifts `translate.x` (assert via inline `style.transform`).
- On unmount, `document.body.style.overflow` returns to its previous value.

## Open Questions

None at this time.
