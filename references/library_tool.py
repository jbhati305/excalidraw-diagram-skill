"""Find and insert pre-built components from the .excalidrawlib files in references/libraries/.

Library icons (databases, users, load balancers, VPCs, ...) are multi-element drawings with
hand-tuned line paths that are impractical to write by hand. This tool copies them into a
diagram with fresh IDs, positioned and scaled where you want them, with legacy fields
normalized to the current Excalidraw schema.

Usage:
    cd .claude/skills/excalidraw-diagram/references
    python library_tool.py list [--library NAME] [--search TEXT]
    python library_tool.py add <diagram.excalidraw> "<component>" --x 400 --y 200 [--scale 1.5] [--label "Orders DB" | --no-label] [--behind]
    python library_tool.py get "<component>" --x 400 --y 200          # print elements JSON instead of writing
    python library_tool.py sheet <out.excalidraw> [--library NAME]      # contact sheet of every component, for previewing

Components are matched by name, case-insensitive. Use "library/name" to disambiguate.
`add` creates the diagram file if it does not exist, and prints a summary with the component's
bounding box and anchor element id (bind arrows to the anchor, or aim them at the bbox edges).
Boundary-sized components (VPC, subnets, regions, clusters) are inserted at the back of the
z-order so they don't cover what you place inside them.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import re
import sys
from pathlib import Path

LIBRARY_DIR = Path(__file__).parent / "libraries"
LINEAR_TYPES = ("line", "arrow", "draw", "freedraw")
LABEL_FONT_FAMILY = 3
MONO_CHAR_WIDTH = 0.6  # approx glyph width / fontSize for fontFamily 3
BOUNDARY_MIN_SIZE = (200, 120)  # components at least this big are treated as containers


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_libraries(only: str | None = None) -> list[dict]:
    """Return [{library, name, elements}] for every item in every .excalidrawlib file."""
    items: list[dict] = []
    for path in sorted(LIBRARY_DIR.glob("*.excalidrawlib")):
        lib = path.stem
        if only and only.lower() != lib.lower():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_items = data.get("libraryItems")
        if raw_items is None:  # v1 format: bare list of element lists, no names
            raw_items = [{"elements": els} for els in data.get("library", [])]
        for i, item in enumerate(raw_items):
            elements = [e for e in item.get("elements", []) if not e.get("isDeleted")]
            if not elements:
                continue
            items.append({
                "library": lib,
                "name": item.get("name") or f"item-{i + 1}",
                "elements": elements,
            })
    return items


def find_component(query: str) -> dict:
    items = load_libraries()
    lib_filter = None
    name = query
    if "/" in query:
        lib_filter, name = query.split("/", 1)
    matches = [
        it for it in items
        if it["name"].lower() == name.lower()
        and (lib_filter is None or it["library"].lower() == lib_filter.lower())
    ]
    if not matches:
        close = [f"{it['library']}/{it['name']}" for it in items if name.lower() in it["name"].lower()]
        hint = f" Did you mean: {', '.join(close)}?" if close else " Run `list` to see available components."
        sys.exit(f"ERROR: No component named '{query}'.{hint}")
    if len(matches) > 1:
        names = ", ".join(f"{m['library']}/{m['name']}" for m in matches)
        sys.exit(f"ERROR: '{query}' is ambiguous: {names}")
    return matches[0]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def element_bounds(el: dict) -> tuple[float, float, float, float]:
    """Axis-aligned bounds of one element, accounting for rotation."""
    x, y = el.get("x", 0), el.get("y", 0)
    if el.get("type") in LINEAR_TYPES and el.get("points"):
        xs = [x + px for px, _ in el["points"]]
        ys = [y + py for _, py in el["points"]]
        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    else:
        x1, y1 = x, y
        x2, y2 = x + abs(el.get("width", 0)), y + abs(el.get("height", 0))
    angle = el.get("angle") or 0
    if not angle:
        return x1, y1, x2, y2
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    cos, sin = math.cos(angle), math.sin(angle)
    corners = [
        (cx + (px - cx) * cos - (py - cy) * sin, cy + (px - cx) * sin + (py - cy) * cos)
        for px, py in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    ]
    return (
        min(c[0] for c in corners), min(c[1] for c in corners),
        max(c[0] for c in corners), max(c[1] for c in corners),
    )


def group_bounds(elements: list[dict]) -> tuple[float, float, float, float]:
    bounds = [element_bounds(e) for e in elements]
    return (
        min(b[0] for b in bounds), min(b[1] for b in bounds),
        max(b[2] for b in bounds), max(b[3] for b in bounds),
    )


# ---------------------------------------------------------------------------
# Normalization + placement
# ---------------------------------------------------------------------------


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "item"


def find_label(elements: list[dict], name: str) -> dict | None:
    """The free-floating caption text of a component, if it has one."""
    texts = [e for e in elements if e.get("type") == "text" and not e.get("containerId")]
    for t in texts:
        if t.get("text", "").strip().lower() == name.lower():
            return t
    return texts[-1] if len(texts) == 1 else None


def find_anchor(elements: list[dict]) -> dict:
    """Largest closed shape — the best target for arrow bindings."""
    shapes = [e for e in elements if e.get("type") in ("rectangle", "ellipse", "diamond")]
    pool = shapes or [e for e in elements if e.get("type") != "text"] or elements
    return max(pool, key=lambda e: abs(e.get("width", 0) * e.get("height", 0)))


def place_component(
    component: dict,
    x: float,
    y: float,
    scale: float = 1.0,
    label: str | None = None,
    show_label: bool = True,
    taken_ids: set[str] | None = None,
) -> tuple[list[dict], dict]:
    """Return (elements, summary) for a component placed with its top-left at (x, y)."""
    taken_ids = taken_ids or set()
    rng = random.Random()
    src = copy.deepcopy(component["elements"])
    name = component["name"]

    label_el = find_label(src, name)
    if label_el is not None and not show_label:
        src = [e for e in src if e is not label_el]
        label_el = None

    if label_el is not None:
        # A caption beside the icon (e.g. a VPC header) keeps its left edge; one below it stays centered
        others = [e for e in src if e is not label_el]
        _, oy1, _, oy2 = group_bounds(others) if others else (0, 0, 0, 0)
        is_header = oy1 <= label_el["y"] + label_el.get("height", 0) / 2 <= oy2
        label_el["fontFamily"] = LABEL_FONT_FAMILY
        if label:
            label_el["text"] = label_el["originalText"] = label
        lines = label_el["text"].split("\n")
        old_cx = label_el["x"] + label_el.get("width", 0) / 2
        label_el["width"] = max(len(line) for line in lines) * label_el.get("fontSize", 20) * MONO_CHAR_WIDTH
        label_el["height"] = len(lines) * label_el.get("fontSize", 20) * 1.25
        if is_header:
            label_el["textAlign"] = "left"
        else:
            label_el["x"] = old_cx - label_el["width"] / 2
            label_el["textAlign"] = "center"
    elif label and show_label:
        # Icon ships without a caption: add one centered below it, ~16px after scaling
        ix1, _, ix2, iy2 = group_bounds(src)
        size = 16 / scale
        label_el = caption("__label__", label, 0, iy2 + 8 / scale, size, "#374151")
        label_el["x"] = (ix1 + ix2) / 2 - label_el["width"] / 2
        label_el["textAlign"] = "center"
        src.append(label_el)

    # Fresh, readable IDs that don't collide with the target diagram
    base = slug(name)
    prefix = base
    n = 2
    while any(i.startswith(prefix + "_") for i in taken_ids):
        prefix = f"{base}{n}"
        n += 1
    id_map = {e["id"]: f"{prefix}_{i}" for i, e in enumerate(src)}
    outer_group = f"{prefix}_group"
    group_map: dict[str, str] = {}
    for e in src:
        for g in e.get("groupIds") or []:
            group_map.setdefault(g, f"{prefix}_g{len(group_map)}")

    label_id = id_map[label_el["id"]] if label_el is not None else None
    min_x, min_y, _, _ = group_bounds(src)

    out: list[dict] = []
    for e in src:
        old_id = e["id"]
        if e["type"] == "draw":  # legacy linear type, restored by Excalidraw as "line"
            e["type"] = "line"

        sharpness = e.pop("strokeSharpness", None)
        if "roundness" not in e:
            if sharpness == "round":
                e["roundness"] = {"type": 2} if e["type"] in LINEAR_TYPES else {"type": 3}
            else:
                e["roundness"] = None

        legacy_bound = e.pop("boundElementIds", None)
        bound = e.get("boundElements")
        if bound is None and legacy_bound:
            bound = [{"id": b, "type": "arrow"} for b in legacy_bound]
        e["boundElements"] = [
            {**b, "id": id_map[b["id"]]} for b in (bound or []) if b.get("id") in id_map
        ]

        for key in ("startBinding", "endBinding"):
            binding = e.get(key)
            if binding and binding.get("elementId") in id_map:
                e[key] = {**binding, "elementId": id_map[binding["elementId"]]}
            elif key in e:
                e[key] = None

        if e.get("containerId"):
            e["containerId"] = id_map.get(e["containerId"])

        e["id"] = id_map[old_id]
        e["groupIds"] = [group_map[g] for g in e.get("groupIds") or []] + [outer_group]
        e["x"] = x + (e["x"] - min_x) * scale
        e["y"] = y + (e["y"] - min_y) * scale
        e["width"] = e.get("width", 0) * scale
        e["height"] = e.get("height", 0) * scale
        if e.get("points"):
            e["points"] = [[px * scale, py * scale] for px, py in e["points"]]
        e.pop("lastCommittedPoint", None)
        if e["type"] == "text":
            e["fontSize"] = round(e.get("fontSize", 20) * scale, 1)
            e.setdefault("lineHeight", 1.25)
            e.pop("baseline", None)

        e["seed"] = rng.randint(1, 2**31 - 1)
        e["version"] = 1
        e["versionNonce"] = rng.randint(1, 2**31 - 1)
        e["isDeleted"] = False
        e.setdefault("link", None)
        e.setdefault("locked", False)
        e.pop("updated", None)
        out.append(e)

    bx1, by1, bx2, by2 = group_bounds(out)
    icon = [e for e in out if e["id"] != label_id]
    ix1, iy1, ix2, iy2 = group_bounds(icon)
    anchor = find_anchor(icon)
    # Only offer an anchor that actually represents the icon (not e.g. one head of "Users")
    anchor_area = abs(anchor.get("width", 0) * anchor.get("height", 0))
    icon_area = max((ix2 - ix1) * (iy2 - iy1), 1)
    summary = {
        "component": f"{component['library']}/{name}",
        "group_id": outer_group,
        "anchor_id": anchor["id"] if anchor_area >= 0.4 * icon_area else None,
        "label_id": label_id,
        "bbox": [round(bx1, 1), round(by1, 1), round(bx2 - bx1, 1), round(by2 - by1, 1)],
        "icon_bbox": [round(ix1, 1), round(iy1, 1), round(ix2 - ix1, 1), round(iy2 - iy1, 1)],
        "element_ids": [e["id"] for e in out],
    }
    return out, summary


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def empty_scene() -> dict:
    return {
        "type": "excalidraw",
        "version": 2,
        "source": "https://excalidraw.com",
        "elements": [],
        "appState": {"viewBackgroundColor": "#ffffff", "gridSize": 20},
        "files": {},
    }


def cmd_list(args: argparse.Namespace) -> None:
    current = None
    for it in load_libraries(args.library):
        if args.search and args.search.lower() not in it["name"].lower():
            continue
        if it["library"] != current:
            current = it["library"]
            print(f"\n[{current}]")
        x1, y1, x2, y2 = group_bounds(it["elements"])
        print(f"  {it['name']:<28} {x2 - x1:>5.0f} x {y2 - y1:<5.0f} ({len(it['elements'])} elements)")


def cmd_get(args: argparse.Namespace) -> None:
    comp = find_component(args.component)
    elements, _ = place_component(comp, args.x, args.y, args.scale, args.label, not args.no_label)
    print(json.dumps(elements, indent=2))


def cmd_add(args: argparse.Namespace) -> None:
    path: Path = args.diagram
    scene = json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_scene()
    taken = {e["id"] for e in scene.get("elements", [])}
    comp = find_component(args.component)
    elements, summary = place_component(
        comp, args.x, args.y, args.scale, args.label, not args.no_label, taken
    )
    # Boundaries (VPC, subnet, region, cluster...) go to the back so they don't cover contents
    iw, ih = summary["icon_bbox"][2:]
    behind = args.behind or (iw >= BOUNDARY_MIN_SIZE[0] and ih >= BOUNDARY_MIN_SIZE[1])
    if behind:
        scene["elements"] = elements + scene.get("elements", [])
    else:
        scene.setdefault("elements", []).extend(elements)
    summary["z_order"] = "back" if behind else "front"
    path.write_text(json.dumps(scene, indent=2), encoding="utf-8")
    del summary["element_ids"]
    print(json.dumps(summary, indent=2))


def cmd_sheet(args: argparse.Namespace) -> None:
    """Lay out every component in a grid with a caption, for visual browsing."""
    scene = empty_scene()
    taken: set[str] = set()
    cols, cell_w, cell_h = args.columns, 320, 300
    items = load_libraries(args.library)
    row_y = 0.0
    current_lib = None
    col = 0
    for it in items:
        if it["library"] != current_lib:
            if current_lib is not None:
                row_y += cell_h
            current_lib = it["library"]
            col = 0
            scene["elements"].append(caption(f"lib_{slug(current_lib)}", current_lib, 0, row_y, 28, "#1e40af"))
            row_y += 60
        elif col == cols:
            col = 0
            row_y += cell_h
        x1, y1, x2, y2 = group_bounds(it["elements"])
        w, h = x2 - x1, y2 - y1
        s = min(1.0, (cell_w - 40) / w, (cell_h - 70) / h)
        cx = col * cell_w
        elements, summary = place_component(it, cx + (cell_w - w * s) / 2, row_y, s, taken_ids=taken)
        taken.update(e["id"] for e in elements)
        scene["elements"].extend(elements)
        bottom = summary["bbox"][1] + summary["bbox"][3]
        scene["elements"].append(
            caption(f"cap_{len(taken)}", f"{it['library']}/{it['name']}", cx + 10, bottom + 12, 12, "#64748b")
        )
        col += 1
    args.output.write_text(json.dumps(scene, indent=2), encoding="utf-8")
    print(f"{args.output} ({len(items)} components)")


def caption(id_: str, text: str, x: float, y: float, size: int, color: str) -> dict:
    return {
        "type": "text", "id": id_, "x": x, "y": y,
        "width": len(text) * size * MONO_CHAR_WIDTH, "height": size * 1.25,
        "text": text, "originalText": text, "fontSize": size, "fontFamily": LABEL_FONT_FAMILY,
        "textAlign": "left", "verticalAlign": "top", "strokeColor": color,
        "backgroundColor": "transparent", "fillStyle": "solid", "strokeWidth": 1,
        "strokeStyle": "solid", "roughness": 0, "opacity": 100, "angle": 0,
        "seed": 1, "version": 1, "versionNonce": 1, "isDeleted": False, "groupIds": [],
        "boundElements": None, "link": None, "locked": False, "containerId": None,
        "lineHeight": 1.25,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Excalidraw component library helper")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="List available components")
    p.add_argument("--library", help="Only this library (file stem)")
    p.add_argument("--search", help="Substring filter on component name")
    p.set_defaults(func=cmd_list)

    for name, func in (("get", cmd_get), ("add", cmd_add)):
        p = sub.add_parser(name, help=f"{name} a component")
        if name == "add":
            p.add_argument("diagram", type=Path, help="Target .excalidraw file (created if missing)")
        p.add_argument("component", help='Component name, or "library/name"')
        p.add_argument("--x", type=float, required=True, help="Left edge of the placed component")
        p.add_argument("--y", type=float, required=True, help="Top edge of the placed component")
        p.add_argument("--scale", type=float, default=1.0)
        p.add_argument("--label", help="Replace the component's caption text")
        p.add_argument("--no-label", action="store_true", help="Drop the component's caption")
        if name == "add":
            p.add_argument("--behind", action="store_true",
                           help="Insert at the back of the z-order (automatic for boundary-sized components)")
        p.set_defaults(func=func)

    p = sub.add_parser("sheet", help="Write a contact sheet of all components")
    p.add_argument("output", type=Path)
    p.add_argument("--library", help="Only this library (file stem)")
    p.add_argument("--columns", type=int, default=6)
    p.set_defaults(func=cmd_sheet)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
