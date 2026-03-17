#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate draw.io (diagrams.net) XML files with embedded logo images.

Reads images from a local directory and embeds them as base64 data URIs
inside drawio XML, so the resulting .drawio file is fully portable.

Usage:
    # List available logos
    python3 generate_drawio.py --list-logos --logo-dir ./imgs

    # Generate diagram from JSON config
    python3 generate_drawio.py \
        --config diagram.json \
        --output diagram.drawio \
        --logo-dir ./imgs

    # Inline JSON config
    python3 generate_drawio.py \
        --config '{"nodes":[{"id":"a","label":"Agent","logo":"logo.png"}]}' \
        --output diagram.drawio
"""

import argparse
import base64
import json
import mimetypes
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_LOGO_DIR = SCRIPT_DIR.parent / "imgs"

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp", ".webp"}

# Default node dimensions
DEFAULT_NODE_WIDTH = 120
DEFAULT_NODE_HEIGHT = 80
DEFAULT_LOGO_SIZE = 40
DEFAULT_SPACING_X = 180
DEFAULT_SPACING_Y = 140

# Draw.io style templates
STYLE_RECT = (
    "rounded=1;whiteSpace=wrap;html=1;"
    "fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=12;fontStyle=1;"
)
STYLE_RECT_NO_LOGO = (
    "rounded=1;whiteSpace=wrap;html=1;"
    "fillColor=#dae8fc;strokeColor=#6c8ebf;fontSize=12;fontStyle=1;"
    "verticalAlign=middle;"
)
STYLE_LOGO = (
    "shape=image;verticalLabelPosition=bottom;labelBackgroundColor=none;"
    "verticalAlign=top;aspect=fixed;imageAspect=0;image={data_uri};"
)
STYLE_EDGE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=1;"
    "orthogonalLoop=1;jettySize=auto;html=1;"
    "strokeColor=#6c8ebf;strokeWidth=2;fontSize=11;"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate draw.io diagrams with embedded logo images"
    )
    parser.add_argument(
        "--config",
        help="Diagram config: JSON string or @filepath. "
             'Format: {"nodes":[...], "edges":[...]}',
    )
    parser.add_argument(
        "--output",
        help="Output .drawio file path.",
    )
    parser.add_argument(
        "--logo-dir",
        default=str(DEFAULT_LOGO_DIR),
        help=f"Directory containing logo images (default: {DEFAULT_LOGO_DIR}).",
    )
    parser.add_argument(
        "--list-logos",
        action="store_true",
        help="List available logo images and exit.",
    )
    return parser.parse_args()


def scan_logos(logo_dir: Path) -> dict:
    """Scan directory for image files. Returns {filename: absolute_path}."""
    logos = {}
    if not logo_dir.is_dir():
        return logos
    for f in sorted(logo_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS:
            logos[f.name] = f
    return logos


def image_to_data_uri(image_path: Path) -> str:
    """Convert an image file to a base64 data URI string."""
    mime, _ = mimetypes.guess_type(str(image_path))
    if mime is None:
        ext = image_path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
        }
        mime = mime_map.get(ext, "application/octet-stream")
    data = image_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def resolve_config(raw: str) -> dict:
    """Parse config from JSON string or @filepath."""
    if raw.startswith("@"):
        filepath = Path(raw[1:]).expanduser()
        if not filepath.exists():
            print(json.dumps({"status": "error", "message": f"Config file not found: {filepath}"}))
            sys.exit(1)
        raw = filepath.read_text(encoding="utf-8")
    return json.loads(raw)


def auto_layout(nodes: list):
    """Assign default x/y positions to nodes that don't have them."""
    col = 0
    row = 0
    max_cols = max(3, int(len(nodes) ** 0.5) + 1)
    for node in nodes:
        if "x" not in node:
            node["x"] = 60 + col * DEFAULT_SPACING_X
        if "y" not in node:
            node["y"] = 60 + row * DEFAULT_SPACING_Y
        col += 1
        if col >= max_cols:
            col = 0
            row += 1


def build_drawio_xml(config: dict, logo_dir: Path) -> str:
    """Build draw.io XML string from config dict with embedded logos."""
    available_logos = scan_logos(logo_dir)

    nodes = config.get("nodes", [])
    edges = config.get("edges", [])
    title = config.get("title", "Page-1")

    auto_layout(nodes)

    # Preload referenced logos as data URIs
    logo_cache = {}
    for node in nodes:
        logo_name = node.get("logo")
        if logo_name and logo_name not in logo_cache:
            if logo_name not in available_logos:
                print(json.dumps({
                    "status": "error",
                    "message": f"Logo '{logo_name}' not found in {logo_dir}. "
                               f"Available: {list(available_logos.keys())}",
                }))
                sys.exit(1)
            logo_cache[logo_name] = image_to_data_uri(available_logos[logo_name])

    # Build XML tree
    mxfile = ET.Element("mxfile", host="Claude", type="device")
    diagram = ET.SubElement(mxfile, "diagram", name=title, id="diagram_0")
    model = ET.SubElement(
        diagram, "mxGraphModel",
        dx="1024", dy="768", grid="1", gridSize="10",
        guides="1", tooltips="1", connect="1", arrows="1",
        fold="1", page="1", pageScale="1",
        pageWidth="1920", pageHeight="1080",
    )
    root = ET.SubElement(model, "root")

    # Required root cells
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")

    cell_id = 2  # next available id
    node_id_map = {}  # user node id -> (xml cell id, geometry for edge anchoring)

    for node in nodes:
        nid = node.get("id", f"node_{cell_id}")
        label = node.get("label", nid)
        x = node.get("x", 0)
        y = node.get("y", 0)
        w = node.get("width", DEFAULT_NODE_WIDTH)
        h = node.get("height", DEFAULT_NODE_HEIGHT)
        logo_name = node.get("logo")
        node_style = node.get("style", "")

        if logo_name and logo_name in logo_cache:
            # --- Node with logo: create a group with logo image + label box ---
            logo_size = node.get("logo_size", DEFAULT_LOGO_SIZE)

            # Group container (invisible)
            group_id = str(cell_id)
            cell_id += 1
            group_cell = ET.SubElement(
                root, "mxCell",
                id=group_id, value="", style="group",
                vertex="1", connectable="1", parent="1",
            )
            group_geo = ET.SubElement(
                group_cell, "mxGeometry",
                x=str(x), y=str(y),
                width=str(w), height=str(h + logo_size + 8),
            )
            group_geo.set("as", "geometry")

            node_id_map[nid] = group_id

            # Logo image cell (top center of group)
            logo_id = str(cell_id)
            cell_id += 1
            data_uri = logo_cache[logo_name]
            logo_style = STYLE_LOGO.format(data_uri=data_uri)
            logo_cell = ET.SubElement(
                root, "mxCell",
                id=logo_id, value="", style=logo_style,
                vertex="1", parent=group_id,
            )
            logo_geo = ET.SubElement(
                logo_cell, "mxGeometry",
                x=str((w - logo_size) // 2), y="0",
                width=str(logo_size), height=str(logo_size),
            )
            logo_geo.set("as", "geometry")

            # Label box below logo
            label_id = str(cell_id)
            cell_id += 1
            rect_style = node_style if node_style else STYLE_RECT
            label_cell = ET.SubElement(
                root, "mxCell",
                id=label_id, value=label, style=rect_style,
                vertex="1", parent=group_id,
            )
            label_geo = ET.SubElement(
                label_cell, "mxGeometry",
                x="0", y=str(logo_size + 8),
                width=str(w), height=str(h),
            )
            label_geo.set("as", "geometry")
        else:
            # --- Plain node without logo ---
            plain_id = str(cell_id)
            cell_id += 1
            rect_style = node_style if node_style else STYLE_RECT_NO_LOGO
            plain_cell = ET.SubElement(
                root, "mxCell",
                id=plain_id, value=label, style=rect_style,
                vertex="1", parent="1",
            )
            plain_geo = ET.SubElement(
                plain_cell, "mxGeometry",
                x=str(x), y=str(y),
                width=str(w), height=str(h),
            )
            plain_geo.set("as", "geometry")

            node_id_map[nid] = plain_id

    # Edges
    for edge in edges:
        src = edge.get("source", edge.get("from", ""))
        tgt = edge.get("target", edge.get("to", ""))
        elabel = edge.get("label", "")
        estyle = edge.get("style", STYLE_EDGE)

        src_cell = node_id_map.get(src)
        tgt_cell = node_id_map.get(tgt)
        if not src_cell or not tgt_cell:
            continue

        edge_id = str(cell_id)
        cell_id += 1
        edge_cell = ET.SubElement(
            root, "mxCell",
            id=edge_id, value=elabel, style=estyle,
            edge="1", parent="1",
            source=src_cell, target=tgt_cell,
        )
        edge_geo = ET.SubElement(edge_cell, "mxGeometry")
        edge_geo.set("relative", "1")
        edge_geo.set("as", "geometry")

    # Serialize with XML declaration
    ET.indent(mxfile, space="  ")
    return ET.tostring(mxfile, encoding="unicode", xml_declaration=True)


def main():
    args = parse_args()
    logo_dir = Path(args.logo_dir).expanduser().resolve()

    # --list-logos mode
    if args.list_logos:
        logos = scan_logos(logo_dir)
        result = {
            "status": "success",
            "logo_dir": str(logo_dir),
            "logos": [
                {"name": name, "path": str(path), "size_bytes": path.stat().st_size}
                for name, path in logos.items()
            ],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # Validate required args
    if not args.config:
        print(json.dumps({"status": "error", "message": "--config is required (use --list-logos to see available logos)"}))
        sys.exit(1)
    if not args.output:
        print(json.dumps({"status": "error", "message": "--output is required"}))
        sys.exit(1)

    try:
        config = resolve_config(args.config)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "message": f"Invalid JSON config: {e}"}))
        sys.exit(1)

    xml_str = build_drawio_xml(config, logo_dir)

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_str, encoding="utf-8")

    # Count stats
    num_nodes = len(config.get("nodes", []))
    num_edges = len(config.get("edges", []))
    logos_used = {n["logo"] for n in config.get("nodes", []) if n.get("logo")}

    result = {
        "status": "success",
        "output": str(output_path),
        "format": "drawio",
        "nodes": num_nodes,
        "edges": num_edges,
        "logos_embedded": sorted(logos_used),
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
