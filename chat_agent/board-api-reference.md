# Board Agent Commands

> **Base URL:** `http://localhost:3000/api/board`
>
> All mutating endpoints push real-time SSE updates to the board UI automatically.

---

## 1. Add Item to Board

```bash
curl -X POST http://localhost:3000/api/board/{boardId}/items \
  -H "Content-Type: application/json" \
  -d '{
    "type": "text-card",
    "zoneId": "zone-demographics",
    "label": "Blood Pressure",
    "content": { "value": "120/80 mmHg", "trend": "stable" },
    "focusZoom": 1.5
  }'
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `type` | `ItemType` | ✅ | `text-card` \| `image` \| `timeline-node` \| `table` \| `status-badge` \| `chart` \| `svg-visual` \| `svg-embed` \| `note` |
| `zoneId` | `string` | ❌ | Auto-detects section; falls back to first section if omitted |
| `sectionId` | `string` | ❌ | Explicit section target |
| `label` | `string` | ✅ | Display label |
| `content` | `object` | ✅ | Item-specific data payload |
| `focusZoom` | `number` | ❌ | Zoom level after adding (default: `1.2`) |

---

## 2. Update Item

```bash
curl -X PATCH http://localhost:3000/api/board/{boardId}/items/{itemId} \
  -H "Content-Type: application/json" \
  -d '{
    "data": { "label": "Updated BP", "content": { "value": "130/85 mmHg" } },
    "position": { "x": 100, "y": 200 }
  }'
```

All fields (`data`, `position`, `style`) are optional and merge-updated.

---

## 3. Delete Item

```bash
curl -X DELETE http://localhost:3000/api/board/{boardId}/items/{itemId}
```

Removes the item, cleans up edges, and re-runs layout automatically.

---

## 4. Add Section

```bash
curl -X POST http://localhost:3000/api/board/{boardId}/sections \
  -H "Content-Type: application/json" \
  -d '{
    "section": {
      "id": "section-vitals",
      "label": "Vital Signs",
      "description": "Current readings",
      "height": 400,
      "color": "emerald",
      "nodes": [],
      "edges": []
    }
  }'
```

If a section with the same `id` exists, it is replaced.

---

## 5. Add Zone

```bash
curl -X POST http://localhost:3000/api/board/{boardId}/zones \
  -H "Content-Type: application/json" \
  -d '{
    "sectionId": "section-vitals",
    "label": "Heart Rate Zone",
    "x": 50,
    "y": 100,
    "width": 800,
    "height": 400,
    "layoutDirection": "horizontal",
    "color": "rose"
  }'
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `sectionId` | `string` | ✅ | Target section |
| `label` | `string` | ✅ | Zone label |
| `x`, `y` | `number` | ✅ | Position |
| `width` | `number` | ❌ | Default: `600` |
| `height` | `number` | ❌ | Default: `300` |
| `layoutDirection` | `string` | ✅ | `horizontal` \| `vertical` \| `grid` |
| `color` | `string` | ❌ | Default: `slate` |

---

## 6. Focus on Section/Node

```bash
# Focus by section + node
curl -X POST http://localhost:3000/api/board/{boardId}/focus \
  -H "Content-Type: application/json" \
  -d '{ "sectionId": "section-vitals", "nodeId": "item-abc", "zoom": 1.5 }'

# Focus by node only (auto-finds section)
curl -X POST http://localhost:3000/api/board/{boardId}/focus \
  -H "Content-Type: application/json" \
  -d '{ "nodeId": "item-abc" }'
```

At least one of `sectionId` or `nodeId` is required. Default zoom: `1.2`.

---

## 7. Relayout with Measurements

```bash
curl -X POST http://localhost:3000/api/board/{boardId}/relayout \
  -H "Content-Type: application/json" \
  -d '{
    "sectionId": "section-vitals",
    "measurements": {
      "item-abc": { "width": 320, "height": 180 },
      "item-def": { "width": 280, "height": 150 }
    }
  }'
```

Recomputes layout. If `sectionId` is omitted, all sections are re-laid out.

---

## 8. Get Board State

```bash
curl http://localhost:3000/api/board/{boardId}
```

Returns full board with all sections, nodes, edges. Creates a demo board if none exists.

---

## 9. Save Board State

```bash
curl -X PUT http://localhost:3000/api/board/{boardId} \
  -H "Content-Type: application/json" \
  -d '{
    "patientId": "patient-123",
    "sections": [...],
    "viewport": { "x": 0, "y": 0, "zoom": 1 },
    "updatedAt": "2026-03-23T06:00:00.000Z"
  }'
```

---

## 10. Poll for Events

```bash
curl "http://localhost:3000/api/board/{boardId}/stream?since=1711180800000"
```

Returns events since the given timestamp (ms). Event types: `board-sync`, `focus`, `access-request`, `access-granted`.
