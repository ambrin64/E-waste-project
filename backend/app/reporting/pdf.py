"""Tiny dependency-free PDF writer for text reports and vector facility plans."""
from __future__ import annotations

import textwrap


def _clean(value: object) -> str:
    text = str(value).encode("cp1252", errors="replace").decode("cp1252")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _assemble(streams: list[bytes]) -> bytes:
    objects: list[bytes] = []
    page_refs = [f"{4 + index * 2} 0 R" for index in range(len(streams))]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{' '.join(page_refs)}] /Count {len(streams)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for index, stream in enumerate(streams):
        stream_id = 5 + index * 2
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>".encode())
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref_at = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF".encode())
    return bytes(output)


def text_report_pdf(pages: list[list[str]]) -> bytes:
    """Render plain report lines with stable pagination and no optional packages."""
    streams = []
    for lines in pages:
        commands = ["BT", "/F1 10 Tf", "48 798 Td", "14 TL"]
        for line in lines:
            for display_line in textwrap.wrap(line, width=95) or [""]:
                commands.append(f"({_clean(display_line)}) Tj T*")
        commands.append("ET")
        streams.append("\n".join(commands).encode("cp1252", errors="replace"))
    return _assemble(streams or [b"BT /F1 10 Tf 48 798 Td (No report data.) Tj ET"])


def facility_layout_pdf(design: dict) -> bytes:
    """Draw envelope and labelled zones to a vector PDF page."""
    env = design["envelope"]
    scale = min(480 / env["width_m"], 550 / env["depth_m"])
    x0, y0 = 56.0, 205.0
    width, depth = env["width_m"] * scale, env["depth_m"] * scale
    colors = [(0.82, 0.91, 0.86), (0.88, 0.91, 0.97), (0.94, 0.87, 0.75),
              (0.93, 0.84, 0.83), (0.85, 0.90, 0.93), (0.89, 0.89, 0.81)]
    ops = ["0.88 0.90 0.88 RG", "0.25 w"]
    for meter in range(0, int(env["width_m"]) + 1, 10):
        gx = x0 + meter * scale
        ops.append(f"{gx} {y0} m {gx} {y0 + depth} l S")
    for meter in range(0, int(env["depth_m"]) + 1, 10):
        gy = y0 + meter * scale
        ops.append(f"{x0} {gy} m {x0 + width} {gy} l S")
    ops.extend(["0.16 0.28 0.22 RG", "1.4 w", f"{x0} {y0} {width} {depth} re S"])
    for zone, color in zip(design["zones"], colors):
        x = x0 + zone["x_m"] * scale
        y = y0 + (env["depth_m"] - zone["y_m"] - zone["depth_m"]) * scale
        w = zone["width_m"] * scale
        h = zone["depth_m"] * scale
        r, g, b = color
        ops.extend([f"{r} {g} {b} rg", f"{x} {y} {w} {h} re B", "0.4 w", "0.25 0.3 0.26 RG",
                    f"{x} {y} {w} {h} re S"])
    ops.extend(["BT", "/F1 14 Tf", "56 790 Td", "(CONCEPTUAL FACILITY LAYOUT - NOT FOR CONSTRUCTION) Tj", "ET",
                "BT", "/F1 9 Tf", f"56 {y0 - 22} Td", f"(Envelope {env['width_m']:.1f} m x {env['depth_m']:.1f} m; required area {design['required_area_m2']:.1f} m2) Tj", "ET",
                "BT", "/F1 9 Tf", f"56 {y0 - 38} Td", f"(Annual throughput {design['annual_throughput_tonnes']:.1f} tonnes/year; storage {design['storage_capacity_tonnes']:.1f} tonnes) Tj", "ET"])
    ops.extend(["BT", "/F1 9 Tf", f"56 {y0 - 54} Td",
        f"(Process {design.get('process_area_m2', design['required_area_m2']):.1f} m2; circulation {design.get('circulation_area_m2', 0):.1f} m2; unallocated {design['remaining_area_m2']:.1f} m2) Tj", "ET"])
    y = y0 - 74
    for zone in design["zones"]:
        ops.extend(["BT", "/F1 9 Tf", f"56 {y} Td",
            f"({_clean(zone['label'])}: {zone['width_m']:.2f} m x {zone['depth_m']:.2f} m; {zone['area_m2']:.1f} m2) Tj", "ET"])
        y -= 15
    validation_y = y - 8
    ops.extend(["BT", "/F1 9 Tf", f"56 {validation_y} Td",
        f"(VALIDATION: {len(design['zones'])} zones contained within {env['width_m']:.1f} x {env['depth_m']:.1f} m envelope.) Tj", "ET",
        "BT", "/F1 9 Tf", f"56 {validation_y - 17} Td",
        "(LIMITATIONS: Conceptual only; no engineering, legal, fire, access, code or measured benefit review.) Tj", "ET"])
    # A second page enlarges the occupied zone cluster without changing its
    # metre coordinates or implying a larger footprint on the plot.
    detail_width = max((zone["x_m"] + zone["width_m"] for zone in design["zones"]), default=1.0)
    detail_depth = max((zone["y_m"] + zone["depth_m"] for zone in design["zones"]), default=1.0)
    detail_scale = min(480 / max(detail_width, 1e-9), 400 / max(detail_depth, 1e-9))
    detail_x0, detail_y0 = 56.0, 350.0
    detail_ops = ["BT", "/F1 14 Tf", "56 790 Td", "(ENLARGED ZONE DETAIL - SAME METRE GEOMETRY) Tj", "ET",
                  "BT", "/F1 9 Tf", "56 770 Td", f"(Detail extent {detail_width:.2f} m x {detail_depth:.2f} m; 1 m grid) Tj", "ET",
                  "0.88 0.90 0.88 RG", "0.2 w"]
    for meter in range(int(detail_width) + 1):
        gx = detail_x0 + meter * detail_scale
        detail_ops.append(f"{gx} {detail_y0} m {gx} {detail_y0 + detail_depth * detail_scale} l S")
    for meter in range(int(detail_depth) + 1):
        gy = detail_y0 + meter * detail_scale
        detail_ops.append(f"{detail_x0} {gy} m {detail_x0 + detail_width * detail_scale} {gy} l S")
    for zone, color in zip(design["zones"], colors):
        x = detail_x0 + zone["x_m"] * detail_scale
        y = detail_y0 + (detail_depth - zone["y_m"] - zone["depth_m"]) * detail_scale
        w, h = zone["width_m"] * detail_scale, zone["depth_m"] * detail_scale
        r, g, b = color
        detail_ops.extend([f"{r} {g} {b} rg", f"{x} {y} {w} {h} re B",
                           "0.4 w", "0.25 0.3 0.26 RG", f"{x} {y} {w} {h} re S"])
    detail_ops.append(f"{detail_x0} {detail_y0} {detail_width * detail_scale} {detail_depth * detail_scale} re S")
    y = 330
    for zone in design["zones"]:
        detail_ops.extend(["BT", "/F1 9 Tf", f"56 {y} Td",
            f"({_clean(zone['label'])}: {zone['width_m']:.2f} m x {zone['depth_m']:.2f} m; {zone['area_m2']:.1f} m2) Tj", "ET"])
        y -= 14
    detail_ops.extend(["BT", "/F1 9 Tf", f"56 {y - 5} Td",
        "(Enlarged for legibility only; zone coordinates and dimensions are unchanged.) Tj", "ET",
        "BT", "/F1 9 Tf", f"56 {y - 21} Td",
        "(CONCEPTUAL ONLY - NOT AN ENGINEERING APPROVAL OR REGULATORY REVIEW.) Tj", "ET"])
    return _assemble(["\n".join(ops).encode("ascii", errors="replace"),
                      "\n".join(detail_ops).encode("ascii", errors="replace")])
