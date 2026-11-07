"""Render documentation PNG/Mermaid and an actual-output GIF. Requires Pillow.

Source: diagrams.json (layout/content), current lifecycle.ALLOWED (captured in the
case graph), and workflow-run.json (observed values). No engine writes or sends.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
BG, INK, MUTED, ACCENT = "#f3f6fb", "#152d46", "#52667c", "#176f91"


def font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size=size)


def lines(draw, xy, text, width, size=22, fill=INK, bold=False):
    x, y = xy
    for paragraph in str(text).splitlines():
        for line in textwrap.wrap(paragraph, width=width, break_long_words=True) or [""]:
            draw.text((x, y), line, font=font(size, bold), fill=fill)
            y += size + 9
    return y


def route(a, b, centers, height):
    """Orthogonal A* routes avoid every node box (no false through-node edges)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if abs(dx) / 420 > abs(dy) / 176:
        sign = 1 if dx > 0 else -1
        port_a, outer_a = (a[0] + sign * 210, a[1]), (a[0] + sign * 235, a[1])
        port_b, outer_b = (b[0] - sign * 210, b[1]), (b[0] - sign * 235, b[1])
    else:
        sign = 1 if dy > 0 else -1
        port_a, outer_a = (a[0], a[1] + sign * 88), (a[0], a[1] + sign * 115)
        port_b, outer_b = (b[0], b[1] - sign * 88), (b[0], b[1] - sign * 115)
    start = (round(outer_a[0] / 10), round(outer_a[1] / 10))
    end = (round(outer_b[0] / 10), round(outer_b[1] / 10))

    def blocked(x, y):
        return (
            x < 2
            or x > 152
            or y < 13
            or y * 10 > height - 110
            or any(abs(x * 10 - cx) < 222 and abs(y * 10 - cy) < 100 for cx, cy in centers.values())
        )

    initial = (*start, 4)
    queue = [(0, 0, initial)]
    costs, parent = {initial: 0}, {}
    final = None
    while queue:
        _, cost, state = heapq.heappop(queue)
        x, y, direction = state
        if cost != costs[state]:
            continue
        if (x, y) == end:
            final = state
            break
        for nd, (xx, yy) in enumerate(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))):
            if blocked(xx, yy):
                continue
            ns = (xx, yy, nd)
            nc = cost + 1 + (2.5 if direction != 4 and direction != nd else 0)
            if nc < costs.get(ns, float("inf")):
                costs[ns] = nc
                parent[ns] = state
                heapq.heappush(queue, (nc + abs(xx - end[0]) + abs(yy - end[1]), nc, ns))
    if final is None:
        raise ValueError("No unobstructed diagram edge route")
    points = []
    while final != initial:
        points.append((final[0] * 10, final[1] * 10))
        final = parent[final]
    points.append((start[0] * 10, start[1] * 10))
    points.reverse()
    return [port_a, outer_a, *points, outer_b, port_b]


def graph(name, spec, out):
    rows = max(n["row"] for n in spec["nodes"]) + 1
    height = 160 + rows * 240 + 100
    im = Image.new("RGB", (1540, height), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1540, 110), fill=INK)
    d.text((45, 28), spec["title"], fill="white", font=font(32, True))
    centers = {n["id"]: (260 + n["col"] * 510, 235 + n["row"] * 240) for n in spec["nodes"]}
    for edge in spec["edges"]:
        a, b = centers[edge["from"]], centers[edge["to"]]
        points = route(a, b, centers, height)
        start, end = points[-2], points[-1]
        d.line(points, fill="#9aabbc", width=3, joint="curve")
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        arrow = [
            end,
            (end[0] - 13 * math.cos(angle - 0.5), end[1] - 13 * math.sin(angle - 0.5)),
            (end[0] - 13 * math.cos(angle + 0.5), end[1] - 13 * math.sin(angle + 0.5)),
        ]
        d.polygon(arrow, fill=ACCENT)
    for n in spec["nodes"]:
        x, y = centers[n["id"]]
        d.rounded_rectangle((x - 210, y - 88, x + 210, y + 88), radius=15, fill="white", outline="#c3d2e0", width=2)
        d.rectangle((x - 209, y - 70, x - 203, y + 64), fill=ACCENT)
        yy = lines(d, (x - 188, y - 70), n["title"], 28, 23, bold=True)
        lines(d, (x - 188, yy + 7), n["body"], 33, 19, MUTED)
    lines(d, (45, height - 85), spec["caption"], 122, 18, MUTED)
    im.save(out / f"{name}.png")
    mmd = ["flowchart TB"]
    for n in spec["nodes"]:
        label = (n["title"] + "<br/>" + n["body"]).replace('"', "'").replace("->", "to")
        mmd.append(f'    {n["id"]}["{label}"]')
    mmd.extend(f"    {e['from']} --> {e['to']}" for e in spec["edges"])
    (ROOT / f"{name}.mmd").write_text("\n".join(mmd) + "\n")


def workflow(record, out):
    r, n = record["result"], record["notification"]
    e, case = r["evidence"], record["case"]
    decision = e.get("decision", {})
    stages = [
        ("Alert received", {"event_id": r["event_id"], "tenant": r["tenant_code"], **e["temps"]}),
        ("Product reference matched (not independent verification)", e["product"]),
        ("Storage limits parsed", e["labelled_range"]),
        ("Cited study assessed", e["stability"]),
        ("SOP index checked; authority still unresolved", {"sop": e["sop"], "authority": e["sop_authority"]}),
        ("Carrier and regulatory reference checked", {"carrier": e["carrier"], "regulatory": e["regulatory"]}),
        (
            "Recommendation returned",
            {
                "recommendation": r["recommendation"],
                "triage_label": r["triage_label"],
                "decision": decision,
                "requires_human_signature": r["requires_human_signature"],
            },
        ),
        (
            "Evidence stored; case awaits review",
            {"state": case["state"], **record["bundle"], "replay_identical": record["replay"]["identical"]},
        ),
        (
            "Independent notification lane remains open",
            {
                k: n[k]
                for k in (
                    "event_id",
                    "state",
                    "reportability_status",
                    "deadline_status",
                    "deadline_utc",
                    "delivery_status",
                )
            },
        ),
    ]
    frames = []
    for i, (title, values) in enumerate(stages):
        im = Image.new("RGB", (1540, 1040), BG)
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 1540, 125), fill=INK)
        d.text((45, 23), "EXC-107133 | observed local workflow", font=font(34, True), fill="white")
        d.text(
            (45, 77),
            f"Stage {i + 1} / {len(stages)} - current code, actual recorded values",
            font=font(22),
            fill="#b7dceb",
        )
        for j in range(len(stages)):
            d.rounded_rectangle((45 + j * 162, 148, 188 + j * 162, 159), radius=5, fill=ACCENT if j <= i else "#d7e0ea")
        lines(d, (45, 190), title, 85, 28, bold=True)
        text = json.dumps(values, indent=2, ensure_ascii=False, default=str)
        # All displayed values are from the saved run. For a long stage, show a
        # prefix and explicitly direct the reader to the complete JSON sidecar.
        shown = text.splitlines()
        if len(shown) > 19:
            shown = shown[:18] + ["... full values in workflow-run.json"]
        yy = 260
        for line in shown:
            for part in textwrap.wrap(line, width=105, replace_whitespace=False, drop_whitespace=False) or [""]:
                d.text((60, yy), part, font=font(21), fill=INK)
                yy += 29
        d.rectangle((0, 955, 1540, 1040), fill="#e5edf5")
        d.text(
            (45, 970),
            "Source: workflow-run.json | no disposition signed and no notification sent in this demo",
            font=font(21),
            fill=MUTED,
        )
        d.text(
            (45, 1004),
            "Historical classifications are reference data, not independent closure verification.",
            font=font(20),
            fill=MUTED,
        )
        frames.append(im)
    frames[0].save(
        out / "workflow.gif",
        save_all=True,
        append_images=frames[1:],
        duration=[2400] * len(frames),
        loop=0,
        optimize=False,
    )
    frames[6].save(out / "workflow-decision.png")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-json", type=Path, default=ROOT.parent / "images" / "workflow-run.json")
    parser.add_argument("--out", type=Path, default=ROOT.parent / "images")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, spec in json.loads((ROOT / "diagrams.json").read_text()).items():
        graph(name, spec, args.out)
    workflow(json.loads(args.case_json.read_text()), args.out)
    print("Rendered seven design diagrams, one real-output GIF, and its decision still.")


if __name__ == "__main__":
    main()
