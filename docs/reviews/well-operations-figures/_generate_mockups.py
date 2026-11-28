"""Generate the review mock-ups for the Well Operations daily-report rework.

These are *wireframes*, not screenshots: they exist so the plan in
`docs/reviews/well-operations-daily-report-rework-plan.md` can be reviewed before
any code is written. Colours are the committed light-mode tokens from
`frontend/src/designSystem.ts`; type is DejaVu Sans (Inter is not installed in the
figure environment), so sizes are approximate.

Run from the repository root:

    python3 docs/reviews/well-operations-figures/_generate_mockups.py

Requires Pillow (`pip install pillow`). Output: PNG next to this file.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
S = 2  # supersample factor; final images are 1/S of the drawing canvas

# ---------------------------------------------------------------------------
# Tokens (light theme, frontend/src/designSystem.ts)
# ---------------------------------------------------------------------------
CANVAS = "#F3F6F6"
PAPER = "#FFFFFF"
HOVER = "#F0F5F5"
SELECTED = "#E2EEEF"
DIVIDER = "#DFE7E8"
DIVIDER_STRONG = "#C2CFD1"
TEXT = "#0D1B22"
MUTED = "#52666D"
DISABLED = "#84969D"
PRIMARY = "#15515B"
PRIMARY_SOFT = "#E7F2F3"
BRASS = "#A9782B"
BRASS_SOFT = "#F3E7CE"
SUCCESS_FG, SUCCESS_BG, SUCCESS_BD = "#1B5E3F", "#E8F3EC", "#C4DFCF"
WARNING_FG, WARNING_BG, WARNING_BD = "#76500E", "#FAF3E4", "#EAD7B1"
ERROR_FG, ERROR_BG, ERROR_BD = "#94261F", "#FBECEB", "#F0CBC7"
INFO_FG, INFO_BG, INFO_BD = "#10454F", "#E7F1F3", "#C2DBDF"
NEUTRAL_FG, NEUTRAL_BG, NEUTRAL_BD = "#45585F", "#EEF3F4", "#DDE6E8"

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")


def font(size: float, weight: str = "regular") -> ImageFont.FreeTypeFont:
    name = {"regular": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf", "mono": "DejaVuSansMono.ttf"}[weight]
    return ImageFont.truetype(str(FONT_DIR / name), int(round(size * S)))


F = {
    "title": font(16.5, "bold"),
    "stat": font(15.5, "bold"),
    "sub": font(10.4),
    "h": font(11.5, "bold"),
    "b": font(10.3),
    "bs": font(10.3, "bold"),
    "s": font(9.5),
    "xs": font(8.6),
    "xbs": font(8.6, "bold"),
    "mono": font(9.0, "mono"),
    "kpi": font(18, "bold"),
}


def px(v: float) -> int:
    return int(round(v * S))


class Canvas:
    def __init__(self, w: float, h: float):
        self.w, self.h = w, h
        self.img = Image.new("RGB", (px(w), px(h)), CANVAS)
        self.d = ImageDraw.Draw(self.img)

    def rect(self, x, y, w, h, fill=None, outline=None, r=0, width=1):
        box = [px(x), px(y), px(x + w), px(y + h)]
        if r:
            self.d.rounded_rectangle(box, radius=px(r), fill=fill, outline=outline, width=px(width))
        else:
            self.d.rectangle(box, fill=fill, outline=outline, width=px(width))

    def line(self, x1, y1, x2, y2, fill=DIVIDER, width=1):
        self.d.line([px(x1), px(y1), px(x2), px(y2)], fill=fill, width=px(width))

    def text(self, x, y, s, f="b", fill=TEXT, anchor="la"):
        self.d.text((px(x), px(y)), s, font=F[f], fill=fill, anchor=anchor)

    def tw(self, s, f="b"):
        return self.d.textlength(s, font=F[f]) / S

    def chip(self, x, y, label, fg=NEUTRAL_FG, bg=NEUTRAL_BG, bd=NEUTRAL_BD, f="xbs", padx=7, h=18):
        w = self.tw(label, f) + padx * 2
        self.rect(x, y, w, h, fill=bg, outline=bd, r=9)
        self.text(x + w / 2, y + h / 2 + 0.3, label, f, fg, anchor="mm")
        return w

    def button(self, x, y, label, primary=False, w=None, h=26, f="bs", outline=DIVIDER_STRONG):
        w = w or self.tw(label, f) + 26
        if primary:
            self.rect(x, y, w, h, fill=PRIMARY, r=6)
            self.text(x + w / 2, y + h / 2 + 0.3, label, f, "#FFFFFF", anchor="mm")
        else:
            self.rect(x, y, w, h, fill=PAPER, outline=outline, r=6)
            self.text(x + w / 2, y + h / 2 + 0.3, label, f, TEXT, anchor="mm")
        return w

    def card(self, x, y, w, h, fill=PAPER, r=10, outline=DIVIDER):
        self.rect(x, y, w, h, fill=fill, outline=outline, r=r)

    def bar(self, x, y, w, h, frac, colour, track=DIVIDER, r=3, over=None):
        self.rect(x, y, w, h, fill=track, r=r)
        seg = w * max(0.0, min(1.0, frac))
        if seg > 0:
            self.rect(x, y, seg, h, fill=colour, r=r)
        if over:
            self.rect(x + w + 2, y - 2, 5, h + 4, fill=ERROR_FG, r=2)

    def save(self, name):
        path = OUT / name
        self.img.resize((px(self.w) // S, px(self.h) // S), Image.LANCZOS).save(path)
        print("wrote", path)


def header_band(c: Canvas, title, subtitle, right_buttons, width):
    c.rect(0, 0, width, 62, fill=PAPER)
    c.line(0, 62, width, 62, DIVIDER)
    c.text(20, 13, title, "title")
    c.text(20, 38, subtitle, "sub", MUTED)
    x = width - 20
    for label, primary in reversed(right_buttons):
        w = c.tw(label, "bs") + 26
        x -= w
        c.button(x, 17, label, primary=primary)
        x -= 8


def tabs(c: Canvas, x, y, labels, active=0, gap=24, w=None):
    cursor = x
    for i, label in enumerate(labels):
        tw = c.tw(label, "bs")
        c.text(cursor, y, label, "bs" if i == active else "b", TEXT if i == active else MUTED)
        if i == active:
            c.rect(cursor, y + 21, tw, 2, fill=PRIMARY)
        cursor += tw + gap
    c.line(x, y + 22, w or cursor, y + 22, DIVIDER)


def field(c: Canvas, x, y, w, label, value="", h=28, focus=False, fg=None):
    c.rect(x, y, w, h, fill=PAPER, outline=PRIMARY if focus else DIVIDER_STRONG, r=6)
    if value:
        c.text(x + 9, y + h / 2, value, "s", fg or TEXT, anchor="lm")
    else:
        c.text(x + 9, y + h / 2, label, "s", MUTED, anchor="lm")
    return w


# ===========================================================================
# Figure 1 — the daily report workspace after the change
# ===========================================================================
def figure_workspace():
    W, H = 1500, 900
    c = Canvas(W, H)
    c.rect(0, 0, W, H, fill=PAPER)
    header_band(
        c,
        "Daily report · ACHARA-EAST-4PH · 16 Nov 2026",
        "Rig-9 / drilling · DDR 55 · draft · West Africa Time (UTC+1:00)    |    9 lines · 24.000 h logged · MD 2,760 → 2,818 m",
        [("Cancel", False), ("Report PDF", False), ("Save draft", True)],
        W,
    )

    # ---- action strip ----------------------------------------------------
    y = 72
    c.text(20, y + 6, "PT 11.500 h", "bs")
    c.chip(112, y, "UPA 1.000", INFO_FG, INFO_BG, INFO_BD, h=19)
    c.chip(184, y, "NPT 10.000", WARNING_FG, WARNING_BG, WARNING_BD, h=19)
    c.chip(264, y, "SP 1.500", BRASS, BRASS_SOFT, WARNING_BD, h=19)
    c.chip(332, y, "24.000 h · balance 0 min", SUCCESS_FG, SUCCESS_BG, SUCCESS_BD, h=19)
    c.text(474, y + 6, "Programme v3 active · 8 of 12 activities open", "s", MUTED)
    x = W - 20
    for label, primary in reversed(
        [("+ Add line", False), ("Assign criteria", False), ("Sequence codes", False), ("Hours & lead / lag", True)]
    ):
        w = c.tw(label, "bs") + 24
        x -= w
        c.button(x, y - 3, label, primary=primary, h=24)
        x -= 8

    tabs(c, 20, 108, ["Activity log (9)", "Measurements & wellbore", "Sources & surveys (12)"], 0, w=W - 40)

    # ---- geometry --------------------------------------------------------
    left_w = 1050
    rail_x, rail_w = 1072, W - 1072 - 20
    grid_y = 144
    row_h = 34
    head_h = 28

    cols = [
        ("#", 28),
        ("Time (WAT)", 116),
        ("Dur", 42),
        ("Activity", 322),
        ("Sequence · hours left", 130),
        ("Line ÷ code plan", 104),
        ("Alloc", 52),
        ("State", 94),
        ("", 28),
    ]
    c.rect(0, grid_y, left_w, head_h, fill="#F6F8F8")
    c.line(0, grid_y, left_w, grid_y, DIVIDER)
    c.line(0, grid_y + head_h, left_w, grid_y + head_h, DIVIDER)
    x = 8
    for label, w in cols:
        c.text(x, grid_y + head_h / 2, label, "xbs", MUTED, anchor="lm")
        x += w

    # seq, plan, logged-on-code, this line, bar fraction — so every row adds up
    rows = [
        ("1", "06:00 – 09:30", "3.500", 'Drill 12¼" hole 2,760 → 2,818 m', "12", "8.000", "3.000", "PT", "in progress", 0.375, False),
        ("2", "09:30 – 11:00", "1.500", "Ream and condition hole", "12", "8.000", "4.500", "PT", "in progress", 0.5625, False),
        ("3", "11:00 – 13:00", "2.000", "Wiper trip, short", "12", "8.000", "6.500", "PT", "in progress", 0.8125, True),
        ("4", "13:00 – 15:30", "2.500", 'Run and cement 9⅝" casing', "13", "6.000", "2.500", "PT", "in progress", 0.4167, False),
        ("5", "15:30 – 17:30", "2.000", "Wait on cement (WOC)", "—", "", "", "NPT", "unplanned", 0.0, False),
        ("6", "17:30 – 18:30", "1.000", "Slips / BOP test", "—", "", "", "UPA", "unplanned", 0.0, False),
        ("7", "18:30 – 20:00", "1.500", "Mix and pump spacer", "14", "4.000", "1.500", "SP", "in progress", 0.375, False),
        ("8", "20:00 – 22:00", "2.000", "Trip in hole with BHA", "15", "7.000", "2.000", "PT", "in progress", 0.2857, False),
        ("9", "22:00 – 06:00", "8.000", "No operations — rig repairs", "—", "", "", "NPT", "unplanned", 0.0, False),
    ]
    y = grid_y + head_h
    for idx, (no, span, dur, narrative, seq, plan, logged, alloc, state, frac, selected) in enumerate(rows):
        c.rect(0, y, left_w, row_h, fill=SELECTED if selected else (PAPER if idx % 2 == 0 else "#FBFCFC"))
        if selected:
            c.rect(0, y, 3, row_h, fill=PRIMARY)
        c.line(0, y + row_h, left_w, y + row_h, DIVIDER)
        x = 8
        c.text(x, y + row_h / 2, no, "s", MUTED, anchor="lm"); x += cols[0][1]
        c.text(x, y + row_h / 2, span, "s", MUTED, anchor="lm"); x += cols[1][1]
        c.text(x, y + row_h / 2, dur, "s", TEXT, anchor="lm"); x += cols[2][1]
        c.text(x, y + row_h / 2, narrative, "bs" if selected else "b", TEXT, anchor="lm"); x += cols[3][1]
        if seq != "—":
            c.text(x, y + 9, seq, "xs", TEXT, anchor="lm")
            c.bar(x + 20, y + 13, 74, 4, frac, BRASS)
            left = float(plan) - float(logged)
            c.text(x, y + 25, f"{left:.3f} h left", "xs", MUTED, anchor="lm")
            x += cols[4][1]
            # the row's own hours over the code's budget — never the code's
            # verdict, which belongs to the code (G8) and lives in the rail
            c.text(x, y + row_h / 2, f"{float(dur):.3f} / {float(plan):.3f}", "s", TEXT, anchor="lm")
            x += cols[5][1]
        else:
            c.text(x, y + row_h / 2, "choose sequence…", "xs", DISABLED, anchor="lm")
            x += cols[4][1] + cols[5][1]
        c.text(x, y + row_h / 2, alloc, "s", ERROR_FG if alloc == "NPT" else (BRASS if alloc == "SP" else MUTED), anchor="lm")
        x += cols[6][1]
        tone = {"in progress": (INFO_FG, INFO_BG, INFO_BD), "unplanned": (WARNING_FG, WARNING_BG, WARNING_BD)}[state]
        c.chip(x, y + 8, state, *tone, h=17)
        x += cols[7][1]
        c.text(x, y + row_h / 2, "⋯", "bs", PRIMARY, anchor="lm")
        y += row_h

    # pagination strip
    c.rect(0, y, left_w, 38, fill=PAPER)
    c.line(0, y, left_w, y, DIVIDER)
    c.text(14, y + 13, "9 lines · one page", "s", MUTED)
    c.chip(left_w - 190, y + 10, "20 / page", h=19)
    c.text(left_w - 104, y + 14, "Export CSV · XLSX · PDF", "xs", DISABLED)

    # footnote: what changed
    c.line(0, H - 62, W, H - 62, DIVIDER)
    c.text(20, H - 52, "WHAT CHANGED ON THIS SCREEN", "xbs", DISABLED)
    c.text(250, H - 52, "22 columns → 9 · 3,450 px of grid → 1,050 px · row dialog + hours dialog + sequence dialog → one always-visible inspector.", "s", MUTED)
    c.text(250, H - 34, "Four scroll regions → one (the grid). Every field is still editable and still exported from the full row.", "s", MUTED)

    # ---- rail ------------------------------------------------------------
    c.card(rail_x, 144, rail_w, H - 220, r=10)
    # segmented control
    c.rect(rail_x + 12, 156, rail_w - 24, 30, fill=HOVER, r=8)
    c.rect(rail_x + 14, 158, 168, 26, fill=PAPER, outline=DIVIDER_STRONG, r=6)
    c.text(rail_x + 28, 165, "Line 3", "bs", PRIMARY)
    c.text(rail_x + 202, 165, "Programme", "b", MUTED)

    # line editor
    ly = 196
    c.text(rail_x + 14, ly, "LINE 3 · WIPER TRIP, SHORT · 2.000 h", "xbs", DISABLED)
    c.text(rail_x + 14, ly + 14, "11:00 – 13:00 WAT · logged 2.000 h", "s", MUTED)

    def pair(y, left, right):
        for i, (label, value, focus) in enumerate((left, right)):
            fx = rail_x + 14 + i * ((rail_w - 34) / 2 + 6)
            fw = (rail_w - 34) / 2
            c.text(fx, y, label, "xs", MUTED)
            field(c, fx, y + 10, fw, "", value, h=26, focus=focus)

    py = ly + 38
    pair(py, ("Activity", 'Drill 12¼" hole', False), ("Allocation", "PT", False)); py += 44
    pair(py, ("Hole section", '12¼"', False), ("Phase", "Drilling", False)); py += 44
    pair(py, ("Sub-phase", "Drilling ahead", False), ("Cause", "—", False)); py += 44
    pair(py, ("Agency / vendor", "—", False), ("Responsible agency", "Company man", False)); py += 44
    pair(py, ("From MD / To MD (m)", "2,760 / 2,818", False), ("Rotating h", "2.750", False)); py += 44
    pair(py, ("ROP (m/h)", "23.27", False), ("Sequence", "12 · this line", True)); py += 40

    # more-fields disclosure: holds the other ten fields, expands in place
    c.rect(rail_x + 14, py, rail_w - 28, 26, fill=HOVER, outline=DIVIDER, r=6)
    c.text(rail_x + 26, py + 8, "More fields — operations, coordinates, fluid, narrative", "xs", PRIMARY)
    c.text(rail_x + rail_w - 26, py + 8, "10", "xs", DISABLED, anchor="ra")
    py += 36

    c.text(rail_x + 14, py, "NOTE / REASON (audit log)", "xbs", DISABLED)
    field(c, rail_x + 14, py + 12, rail_w - 28, "Explain a corrected duration…", h=40)
    c.text(rail_x + 14, py + 60, "Restores the logged 2.000 h", "xs", DISABLED)
    c.button(rail_x + rail_w - 14 - 96, py + 54, "Restore", h=22)

    # always-visible outcome strip
    sy = py + 88
    c.line(rail_x + 12, sy, rail_x + rail_w - 12, sy, DIVIDER)
    c.text(rail_x + 14, sy + 10, "AFTER THIS LINE", "xbs", DISABLED)
    c.text(rail_x + 14, sy + 26, "seq 12 · 8.000 h plan · 8.500 h logged incl. this line", "s", TEXT)
    c.text(rail_x + 14, sy + 44, "0.500 h over plan · no lead/lag until seq 12 is closed", "xs", ERROR_FG)
    c.bar(rail_x + 14, sy + 62, rail_w - 28, 6, 0.8125, BRASS)
    c.text(rail_x + rail_w - 14, sy + 74, "0.021 d over plan · a lag if closed now", "xs", DISABLED, anchor="ra")

    c.line(rail_x + 12, sy + 92, rail_x + rail_w - 12, sy + 92, DIVIDER)
    c.text(rail_x + 14, sy + 100, "PROGRAMME OUTCOME", "xbs", DISABLED)
    c.text(rail_x + 14, sy + 116, "−0.729 d", "kpi", ERROR_FG)
    c.text(rail_x + 96, sy + 122, "lag · finished work only", "xs", MUTED)
    c.text(rail_x + 14, sy + 146, "Schedule position  +0.750 d ahead", "s", SUCCESS_FG)
    c.text(rail_x + 14, sy + 164, "12.000 h unplanned · 3.000 h released by seq 18", "xs", MUTED)

    c.text(rail_x + 14, H - 60, "Nothing here scrolls on its own: the seven field pairs, the", "xs", DISABLED)
    c.text(rail_x + 14, H - 47, "note and the budget strip fit above the fold. The other ten", "xs", DISABLED)
    c.text(rail_x + 14, H - 34, "fields open in place under “More fields”, never in a dialog.", "xs", DISABLED)

    c.save("01-daily-report-workspace.png")


# ===========================================================================
# Figure 2 — assignment with a visible budget, and the budget workspace
# ===========================================================================
def figure_assignment():
    W, H = 1500, 900
    c = Canvas(W, H)
    # faint workspace behind the dialog
    c.rect(0, 0, W, H, fill="#EEF2F2")
    c.rect(0, 0, W, 58, fill=PAPER)
    c.text(20, 16, "Daily report · ACHARA-EAST-4PH · 16 Nov 2026", "title")
    c.text(20, 38, "Activity log · 9 lines", "sub", MUTED)
    c.line(0, 58, W, 58, DIVIDER)

    # ---- the assignment popover, anchored on the selected row -------------
    dx, dy, dw, dh = 320, 92, 860, 700
    c.rect(dx + 6, dy + 8, dw, dh, fill="#0D1B22", r=12)
    c.card(dx, dy, dw, dh, r=12)
    c.rect(dx, dy, dw, 66, fill=PAPER, r=12)
    c.rect(dx, dy + 50, dw, 16, fill=PAPER)
    c.text(dx + 20, dy + 14, "Assign sequence · line 3 · 2.000 h", "title")
    c.text(dx + 20, dy + 40, "A sequence is a spend. Pick the open activity this line's hours come out of — the hours left are shown before you commit.", "sub", MUTED)
    c.line(dx, dy + 66, dx + dw, dy + 66, DIVIDER)

    # filter + mode row
    field(c, dx + 20, dy + 78, 360, "Search 12, 13, casing, cement…")
    c.chip(dx + 392, dy + 84, "Open (8)", SUCCESS_FG, SUCCESS_BG, SUCCESS_BD)
    c.chip(dx + 468, dy + 84, "Finished (5)", NEUTRAL_FG, NEUTRAL_BG, NEUTRAL_BD)
    c.chip(dx + 552, dy + 84, "Skipped (1)", MUTED, NEUTRAL_BG, NEUTRAL_BD)
    c.text(dx + dw - 20, dy + 90, "Grouped by phase · holesection", "xs", DISABLED, anchor="ra")

    # column header
    hy = dy + 118
    heads = [("SEQ", 24), ("ACTIVITY", 330), ("BUDGET", 74), ("LOGGED", 74), ("LEFT BEFORE", 82), ("THIS LINE", 74), ("LEFT AFTER", 84)]
    hx = dx + 20
    for label, w in heads:
        c.text(hx, hy, label, "xbs", DISABLED)
        hx += w
    c.line(dx + 20, hy + 18, dx + dw - 20, hy + 18, DIVIDER)

    rows = [
        # seq, desc, plan, logged, left_before, this, barfrac, selected, note
        ("11", 'Drill 12¼" 2,700–2,900 m · PT', "40.000", "43.500", "−3.500", "—", 1.0, False, "over plan", ERROR_FG, ERROR_BG, ERROR_BD),
        ("12", 'Drill 12¼" 2,900–3,050 m · PT', "8.000", "6.500", "1.500", "2.000", 0.8125, True, "would overrun by 0.500 h", ERROR_FG, ERROR_BG, ERROR_BD),
        ("13", 'Run 9⅝" casing · PT', "6.000", "2.500", "3.500", "2.000", 0.4167, False, "", INFO_FG, INFO_BG, INFO_BD),
        ("14", "Cement job · SP", "4.000", "6.000", "−2.000", "—", 1.0, False, "over plan · slow progress", WARNING_FG, WARNING_BG, WARNING_BD),
        ("15", "Trip in hole with BHA · PT", "7.000", "2.000", "5.000", "2.000", 0.286, False, "", INFO_FG, INFO_BG, INFO_BD),
        ("16", "Displace to brine · PT", "3.000", "0.000", "3.000", "—", 0.0, False, "not started", NEUTRAL_FG, NEUTRAL_BG, NEUTRAL_BD),
        ("17", "Rig up cement unit · PT", "2.500", "0.000", "2.500", "—", 0.0, False, "not started", NEUTRAL_FG, NEUTRAL_BG, NEUTRAL_BD),
        ("18", "Skipped · no cement head", "3.000", "—", "released", "—", 0.0, False, "skipped — 3.000 h saved", MUTED, NEUTRAL_BG, NEUTRAL_BD),
    ]
    ry = hy + 26
    for seq, desc, plan, logged, left, this, frac, sel, note, fg, bg, bd in rows:
        rh = 44
        if sel:
            c.rect(dx + 12, ry - 6, dw - 24, rh + 4, fill=SELECTED, r=8)
            c.rect(dx + 12, ry - 6, 3, rh + 4, fill=PRIMARY)
        c.text(dx + 24, ry + 7, seq, "mono", TEXT)
        c.text(dx + 44, ry + 2, desc, "bs" if sel else "b", TEXT if seq != "18" else DISABLED)
        if note:
            c.text(dx + 44, ry + 18, note, "xs", fg)
        c.text(dx + 354, ry + 7, plan, "mono", MUTED)
        c.text(dx + 428, ry + 7, logged, "mono", MUTED)
        c.text(dx + 502, ry + 7, left, "mono", ERROR_FG if left.startswith("−") else TEXT)
        if this != "—":
            c.rect(dx + 578, ry + 2, 58, 22, fill=PAPER, outline=PRIMARY if sel else DIVIDER_STRONG, r=5)
            c.text(dx + 607, ry + 13, this, "mono", PRIMARY if sel else TEXT, anchor="mm")
        else:
            c.text(dx + 607, ry + 7, "—", "mono", DISABLED, anchor="ra")
        # after
        if this not in ("—", "", "released"):
            before = float(left)
            after = before - float(this)
            label = f"{after:+.3f}".replace("+", "") if after >= 0 else f"−{abs(after):.3f}"
            colour = ERROR_FG if after < 0 else (BRASS if after < 1 else SUCCESS_FG)
            c.text(dx + 650, ry + 7, label, "mono", colour)
        else:
            c.text(dx + 650, ry + 7, "—", "mono", DISABLED)
        # mini budget bar
        if seq != "18":
            c.bar(dx + 690, ry + 9, 120, 6, min(1.0, frac if frac else 0.0), BRASS if frac < 1 else ERROR_FG, over=frac >= 1)
        ry += rh

    # budget preview card
    py = ry + 8
    c.rect(dx + 20, py, dw - 40, 96, fill=PRIMARY_SOFT, outline=INFO_BD, r=8)
    c.text(dx + 32, py + 10, "BEFORE YOU COMMIT", "xbs", PRIMARY)
    c.text(dx + 32, py + 26, "Sequence 12 · 8.000 h planned · 6.500 h already logged", "bs")
    c.text(dx + 32, py + 44, "This line takes 2.000 h → 8.500 h logged, 0.500 h over plan.", "s", ERROR_FG)
    c.text(dx + 32, py + 62, "The overrun stays “over plan, still open” until you mark the activity finished. It is never a lead,", "xs", MUTED)
    c.text(dx + 32, py + 76, "and it is not NPT or UPA unless you classify the excess that way on the lines.", "xs", MUTED)

    # footer
    c.line(dx, dy + dh - 58, dx + dw, dy + dh - 58, DIVIDER)
    c.text(dx + 20, dy + dh - 44, "Nothing is written until you apply.", "xs", MUTED)
    b = c.button(dx + dw - 20 - 218, dy + dh - 46, "Apply 2.000 h to seq 12", primary=True, h=28, w=218)

    # no callout: the column headings and the "before you commit" card
    # already say what the four budget columns mean

    c.save("02-sequence-assignment-budget.png")


# ===========================================================================
# Figure 3 — the skip decision, and what each choice does to the arithmetic
# ===========================================================================
def figure_skip():
    W, H = 1500, 900
    c = Canvas(W, H)
    c.rect(0, 0, W, H, fill="#EEF2F2")
    c.text(20, 14, "Programme v3 · ACHARA-EAST-4PH · drilling", "title")
    c.text(20, 38, "Plans & timeline · sequence register", "sub", MUTED)
    c.line(0, 58, W, 58, DIVIDER)

    # ---- gantt excerpt on the left ---------------------------------------
    gx, gy, gw = 24, 80, 660
    c.card(gx, gy, gw, 470, r=10)
    c.text(gx + 16, gy + 12, "PROGRAMME STRIP — the last four sequences", "xbs", DISABLED)
    c.text(gx + 16, gy + 28, "planned 15.500 h · logged 12.500 h · one sequence skipped", "s", MUTED)

    bars = [
        ("15", "Trip in hole with BHA", 0.0, 0.42, "finished", SUCCESS_FG, SUCCESS_BG, SUCCESS_BD),
        ("16", "Displace to brine", 0.42, 0.55, "finished", SUCCESS_FG, SUCCESS_BG, SUCCESS_BD),
        ("17", "Rig up cement unit", 0.55, 0.86, "finished", SUCCESS_FG, SUCCESS_BG, SUCCESS_BD),
        ("18", "Skipped · no cement head", 0.86, 1.0, "skipped", MUTED, NEUTRAL_BG, NEUTRAL_BD),
    ]
    bx, bw = gx + 16, gw - 32
    y = gy + 62
    for seq, desc, a, b, state, fg, bg, bd in bars:
        c.text(bx, y, seq, "mono", TEXT)
        c.text(bx + 26, y - 1, desc, "b", TEXT if state != "skipped" else MUTED)
        x0 = bx + 26 + (bw - 26) * a
        x1 = bx + 26 + (bw - 26) * b
        if state == "skipped":
            # hatched block
            c.rect(x0, y + 20, max(60, x1 - x0), 18, fill=NEUTRAL_BG, outline=bd, r=4)
            hx = x0 + 4
            while hx < x0 + max(60, x1 - x0) - 3:
                c.line(hx, y + 36, hx + 10, y + 22, DIVIDER_STRONG, 1)
                hx += 11
            c.text(x0 + 8, y + 29, "skipped", "xbs", MUTED, anchor="lm")
        else:
            c.rect(x0, y + 20, x1 - x0, 18, fill=bg, outline=bd, r=4)
            c.rect(x0, y + 20, x1 - x0, 18, fill=None, outline=None)
            c.text(x0 + 8, y + 29, "finished", "xbs", fg, anchor="lm")
        c.chip(bx + bw - 66, y + 1, state, fg, bg, bd, h=17)
        y += 66

    # today marker
    tx = bx + 26 + (bw - 26) * 0.93
    c.line(tx, gy + 56, tx, gy + 420, PRIMARY, 1)
    c.text(tx + 6, gy + 56, "today · day 18", "xs", PRIMARY)

    c.line(gx + 16, gy + 330, gx + gw - 16, gy + 330, DIVIDER)
    c.text(gx + 16, gy + 342, "WHAT THE REGISTER SHOWS FOR SEQ 18", "xbs", DISABLED)
    c.text(gx + 16, gy + 358, "planned 3.000 h", "xs", MUTED)
    c.text(gx + 150, gy + 358, "logged 0.000 h", "xs", MUTED)
    c.text(gx + 274, gy + 358, "no verdict — skipped", "xs", MUTED)
    c.rect(gx + 16, gy + 378, gw - 32, 74, fill=WARNING_BG, outline=WARNING_BD, r=8)
    c.text(gx + 26, gy + 386, "3.000 h released. The effective curve of every later activity", "s", WARNING_FG)
    c.text(gx + 26, gy + 404, "moves 0.125 d earlier; the signed baseline is not rewritten.", "s", WARNING_FG)
    c.text(gx + 26, gy + 424, "The 3.000 h can be credited, or written off — you choose.", "xs", WARNING_FG)

    # ---- skip dialog on the right ----------------------------------------
    dx, dy, dw, dh = 716, 80, 760, 640
    c.rect(dx + 6, dy + 8, dw, dh, fill="#0D1B22", r=12)
    c.card(dx, dy, dw, dh, r=12)
    c.text(dx + 22, dy + 16, "Skip sequence 18 · 3.000 h planned", "title")
    c.text(dx + 22, dy + 42, "“Skipped” has three meanings and they move the numbers differently. Say which one this is; the reason is kept.", "sub", MUTED)
    c.line(dx, dy + 68, dx + dw, dy + 68, DIVIDER)

    options = [
        (
            "A · The work was not needed",
            "Nothing was done and nothing replaces it. The 3.000 h leave the plan and are released to schedule.",
            ["planned in scope   −3.000 h", "outcome            0.000 h (released, not earned)", "curve              0.125 d earlier from seq 19 on"],
            True,
        ),
        (
            "B · The work was done on another activity",
            "The time was spent inside another sequence. Name that sequence: the hours move there and this one releases its plan.",
            ["planned in scope   −3.000 h", "receiver's logged  +3.000 h → may now overrun (lag)", "sequence outcome   depends on the receiver's plan"],
            False,
        ),
        (
            "C · Skipped, but the time still counts",
            "The sequence will not be done, yet the shift time was spent and must stay on the record (e.g. waiting on a skipped job).",
            ["planned in scope   −3.000 h", "unplanned time     +2.000 h stays on record → lag", "sequence outcome   −2.000 h, and NPT/UPA only if you classify it"],
            False,
        ),
    ]
    oy = dy + 82
    for title, body, effects, chosen in options:
        oh = 118 if not chosen else 172
        c.rect(dx + 20, oy, dw - 40, oh, fill=PRIMARY_SOFT if chosen else PAPER, outline=PRIMARY if chosen else DIVIDER_STRONG, r=10, width=2 if chosen else 1)
        # radio
        rx, ryy = dx + 36, oy + 18
        c.d.ellipse([px(rx), px(ryy), px(rx + 15), px(ryy + 15)], outline=PRIMARY if chosen else DIVIDER_STRONG, width=px(1.6), fill=PAPER)
        if chosen:
            c.d.ellipse([px(rx + 4), px(ryy + 4), px(rx + 11), px(ryy + 11)], fill=PRIMARY)
        c.text(dx + 60, oy + 12, title, "bs", PRIMARY if chosen else TEXT)
        c.text(dx + 60, oy + 32, body, "xs", MUTED)
        ey = oy + 58
        for line in effects:
            c.text(dx + 60, ey, line, "xs", TEXT if chosen else MUTED)
            ey += 14
        # only the chosen option asks for the rest
        if chosen:
            c.text(dx + 60, oy + 118, "REASON (KEPT IN THE AUDIT LOG)", "xbs", DISABLED)
            field(c, dx + 60, oy + 131, 296, "Why the work is not needed")
            c.chip(dx + 368, oy + 134, "credit 3.000 h", SUCCESS_FG, SUCCESS_BG, SUCCESS_BD, h=20)
            c.chip(dx + 484, oy + 134, "write off", MUTED, NEUTRAL_BG, NEUTRAL_BD, h=20)
        oy += oh + 10

    c.line(dx, dy + dh - 62, dx + dw, dy + dh - 62, DIVIDER)
    c.text(dx + 22, dy + dh - 48, "A needs no coded lines · B and C move them · the skip itself is reversible and audited.", "xs", MUTED)
    c.button(dx + dw - 20 - 262, dy + dh - 50, "Skip sequence 18 · option A", primary=True, h=30, w=262)

    c.save("03-skip-decisions.png")


# ===========================================================================
# Figure 4 — the calculation, one page
# ===========================================================================
def figure_calculation():
    W, H = 1500, 852
    c = Canvas(W, H)
    c.rect(0, 0, W, H, fill=PAPER)
    c.text(24, 18, "How the daily report turns hours into lead and lag", "title")
    c.text(24, 44, "Three steps, three numbers, never mixed. Worked example — the log is one shift; the budgets are cumulative: seq 12 planned 8.000 h took 9.000 h, seq 15 planned 4.000 h took 6.000 h, and 4.000 h carry no sequence.", "sub", MUTED)
    c.line(0, 72, W, 72, DIVIDER)

    # ---------------- step strip -----------------------------------------
    steps = [
        ("STEP 1", "The time log", "Every line records what happened: from, to, duration, allocation (PT / UPA / NPT / SP) and the sequence it is charged to."),
        ("STEP 2", "The sequence budget", "A sequence is a spend: planned hours in, logged hours out. What is left is what the code still owes."),
        ("STEP 3", "The well verdict", "Two questions, two numbers: where the well is today (schedule position), and what finished work cost (sequence outcome)."),
    ]
    x = 24
    for i, (tag, title, body) in enumerate(steps):
        c.text(x, 88, tag, "xbs", PRIMARY)
        c.text(x, 102, title, "bs")
        # wrapped body
        words, line, lines = body.split(), "", []
        for w in words:
            if c.tw(line + " " + w, "xs") > 340:
                lines.append(line)
                line = w
            else:
                line = (line + " " + w).strip()
        lines.append(line)
        yy = 120
        for ln in lines:
            c.text(x, yy, ln, "xs", MUTED)
            yy += 14
        x += 484
    c.line(24, 186, W - 24, 186, DIVIDER)

    # ---------------- step 1: the log ------------------------------------
    top = 200
    c.text(24, top, "1 · THE LOG — one shift", "h")
    rows = [
        ("06:00–08:00", "2.000", "Drill 12¼\" ahead (RSS)", "12", "PT"),
        ("08:00–09:00", "1.000", "Drill ahead, sliding — slow", "12", "SP"),
        ("09:00–15:00", "6.000", "Ream and condition hole", "12", "PT"),
        ("15:00–17:00", "2.000", "Wait on cement (WOC)", "—", "NPT"),
        ("17:00–19:00", "2.000", "Slips / BOP test", "—", "UPA"),
        ("19:00–00:00", "5.000", "Run 9⅝\" casing", "14", "PT"),
    ]
    ty = top + 22
    heads = [("FROM–TO (WAT)", 24, 112), ("H", 136, 40), ("WHAT HAPPENED", 176, 226), ("SEQ", 402, 44), ("ALLOC", 446, 50)]
    for label, hx, _w in heads:
        c.text(hx, ty, label, "xbs", DISABLED)
    c.line(24, ty + 16, 500, ty + 16, DIVIDER)
    ty += 24
    for span, hrs, what, seq, alloc in rows:
        c.text(24, ty, span, "mono", MUTED)
        c.text(136, ty, hrs, "mono", TEXT)
        c.text(176, ty, what, "xs", TEXT)
        c.text(402, ty, seq, "mono", TEXT if seq != "—" else DISABLED)
        c.text(446, ty, alloc, "mono", ERROR_FG if alloc == "NPT" else (BRASS if alloc == "SP" else MUTED))
        c.line(24, ty + 15, 500, ty + 15, DIVIDER)
        ty += 26
    c.text(24, ty + 4, "Total 18.000 h · coded 14.000 h · uncoded 4.000 h", "xbs", TEXT)
    c.text(24, ty + 22, "Allocation is the user's statement. Nothing infers NPT or UPA from a slow line.", "xs", MUTED)

    # ---------------- step 2: the budgets ---------------------------------
    bx0 = 536
    c.text(bx0, top, "2 · THE BUDGETS — what each sequence still owes", "h")
    budgets = [
        ("12", 'Drill 12¼" 2,900–3,050 m', 8.0, 9.0, "1.000 over · closed", 1.0, ERROR_FG, ERROR_BG, ERROR_BD),
        ("13", "Ream and condition (not used)", 2.0, 0.0, "0.000 · untouched", 0.0, NEUTRAL_FG, NEUTRAL_BG, NEUTRAL_BD),
        ("14", 'Run 9⅝" casing', 10.0, 5.0, "5.000 left", 0.5, INFO_FG, INFO_BG, INFO_BD),
        ("15", "Cement job", 4.0, 6.0, "2.000 over · closed", 1.0, ERROR_FG, ERROR_BG, ERROR_BD),
    ]
    by = top + 24
    for seq, desc, plan, actual, label, frac, fg, bg, bd in budgets:
        c.text(bx0, by, seq, "mono", TEXT)
        c.text(bx0 + 24, by, desc, "xs", TEXT)
        c.chip(bx0 + 236, by - 2, label, fg, bg, bd, h=17)
        note = f"plan {plan:.3f} · logged {actual:.3f}"
        if seq == "14":
            note += " · this shift"
        elif seq == "15":
            note += " · earlier shifts"
        c.text(bx0 + 24, by + 16, note, "xs", MUTED)
        c.bar(bx0 + 24, by + 30, 440, 5, frac, ERROR_FG if "over" in label else (BRASS if frac >= 1 else INFO_FG), over="over" in label)
        by += 50
    c.rect(bx0, by + 2, 448, 106, fill=HOVER, outline=DIVIDER, r=8)
    c.text(bx0 + 12, by + 10, "THE CARRY-OVER, IN ONE LINE", "xbs", DISABLED)
    c.text(bx0 + 12, by + 26, "An 8.000 h code: a 3.000 h line → 5.000 h left; a 4.000 h line → 1.000 h left.", "xs", TEXT)
    c.text(bx0 + 12, by + 42, "A line assigned to another code leaves that 1.000 h on its own code; nothing", "xs", TEXT)
    c.text(bx0 + 12, by + 58, "moves by itself — it stays until the code is closed or skipped.", "xs", TEXT)
    c.text(bx0 + 12, by + 78, "Seq 12 here overran by 1.000 h: the same planned activity, late —", "xs", BRASS)
    c.text(bx0 + 12, by + 92, "not an NPT event, and never a cause the system invented.", "xs", BRASS)

    # ---------------- step 3: the verdicts --------------------------------
    vx = 1016
    c.text(vx, top, "3 · THE VERDICTS — kept apart", "h")
    c.card(vx, top + 24, W - vx - 24, 128, fill=PAPER, r=10)
    c.text(vx + 14, top + 34, "SCHEDULE POSITION — where the well is today", "xbs", DISABLED)
    c.text(vx + 14, top + 50, "+0.750 d ahead", "kpi", SUCCESS_FG)
    c.text(vx + 14, top + 82, "planned cumulative 9.250 d at the confirmed", "xs", MUTED)
    c.text(vx + 14, top + 95, "checkpoint − elapsed 10.000 d", "xs", MUTED)
    c.text(vx + 14, top + 112, "moves with the calendar and the checkpoint.", "xs", MUTED)

    c.card(vx, top + 158, W - vx - 24, 128, fill=PAPER, r=10)
    c.text(vx + 14, top + 168, "SEQUENCE OUTCOME — finished work only", "xbs", DISABLED)
    c.text(vx + 14, top + 184, "−0.292 d lag", "kpi", ERROR_FG)
    c.text(vx + 14, top + 216, "Σ (plan − logged) over the 2 finished codes −3.000 h,", "xs", MUTED)
    c.text(vx + 14, top + 229, "less 4.000 h unplanned = −7.000 h ÷ 24 = −0.292 d", "xs", MUTED)
    c.text(vx + 14, top + 248, "open codes show progress and hours owed, never a lead.", "xs", MUTED)

    # ---------------- the four buckets ------------------------------------
    gtop = 556
    c.text(24, gtop, "WHERE THE LAG COMES FROM — three buckets that add up, and one label inside them", "h")
    c.text(24, gtop + 22, "Slow progress is a planned activity that took longer. It is lag inside Planned/PT — not NPT, not UPA. NPT and UPA are only ever stated by the user.", "xs", MUTED)

    buckets = [
        ("PLANNED · PT", "Finished codes that cost more than their plan", "3.000 h", "seq 12 −1.000, seq 15 −2.000 → 0.125 d", BRASS, BRASS_SOFT, WARNING_BD, "inferred from the hours"),
        ("SLOW PROGRESS · SP", "The part of that overrun the engineer calls slow", "1.000 h", "of the 3.000 · a label, never added again", BRASS, BRASS_SOFT, WARNING_BD, "user states SP"),
        ("NPT", "Waiting, repairs, trouble — no plan absorbs it", "2.000 h", "always lag → 0.083 d", ERROR_FG, ERROR_BG, ERROR_BD, "user states NPT"),
        ("UPA / NO CODE", "Work nobody planned", "2.000 h", "always lag → 0.083 d", WARNING_FG, WARNING_BG, WARNING_BD, "user states UPA, or no code"),
    ]
    x = 24
    bw = (W - 48 - 36) / 4
    for title, body, hours, effect, fg, bg, bd, source in buckets:
        c.rect(x, gtop + 44, bw, 168, fill=PAPER, outline=DIVIDER, r=10)
        c.chip(x + 14, gtop + 56, title, fg, bg, bd, h=19)
        c.text(x + 14, gtop + 84, body, "xs", TEXT)
        c.text(x + 14, gtop + 112, hours, "kpi", TEXT)
        c.text(x + 14, gtop + 142, effect, "xs", fg)
        c.text(x + 14, gtop + 162, "source: " + source, "xs", DISABLED)
        x += bw + 12
    c.rect(24, gtop + 226, W - 48, 52, fill=PRIMARY_SOFT, outline=INFO_BD, r=8)
    c.text(36, gtop + 234, "RULE", "xbs", PRIMARY)
    c.text(78, gtop + 233, "3.000 planned overrun + 2.000 NPT + 2.000 UPA = 7.000 h = −0.292 d, the whole lag; SP is not a fifth bucket — it names 1.000 h inside the 3.000.", "xs", TEXT)
    c.text(78, gtop + 249, "Every logged hour belongs to one line, one allocation and one sequence (or none), so nothing is counted twice. Hours ÷ 24 gives days, once, at the boundary.", "xs", TEXT)

    c.save("04-calculation-model.png")


# ===========================================================================
# Figure 5 — what changes on the register rows (before / after)
# ===========================================================================
def figure_register():
    W, H = 1500, 760
    c = Canvas(W, H)
    c.rect(0, 0, W, H, fill=PAPER)
    c.text(24, 16, "Daily reports register — scanning a month without opening a report", "title")
    c.text(24, 42, "Left: the register as it is — 17 columns, the first 13 shown here, not one of them a programme figure. Right: the same data grouped by activity, with the two numbers that matter.", "sub", MUTED)
    c.line(0, 68, W, 68, DIVIDER)

    # ---- before ----------------------------------------------------------
    c.text(24, 82, "TODAY", "xbs", DISABLED)
    cols = ["DATE", "RIG", "WELL", "SCOPE", "TYPE", "NO.", "START MD", "END MD", "TVD", "BIT", "PROG", "MW", "HOURS", "STATUS"]
    x = 24
    widths = [58, 44, 62, 52, 34, 38, 60, 60, 48, 44, 46, 40, 50, 54]
    for label, w in zip(cols, widths):
        c.text(x, 100, label, "xbs", DISABLED)
        x += w
    c.line(24, 114, 720, 114, DIVIDER)
    data = [
        ("16 Nov", "R9", "ACH-E", "drill", "DDR", "55", "3,960", "4,127", "3,212", "4,120", "167", "9.8", "24.0", "approved"),
        ("15 Nov", "R9", "ACH-E", "drill", "DDR", "54", "3,700", "3,960", "3,080", "3,955", "260", "9.7", "24.0", "approved"),
        ("14 Nov", "R9", "ACH-E", "drill", "DDR", "53", "3,520", "3,700", "2,940", "3,690", "180", "9.7", "24.0", "approved"),
        ("13 Nov", "R9", "ACH-E", "drill", "DDR", "52", "3,300", "3,520", "2,780", "3,510", "220", "9.6", "22.5", "submitted"),
        ("12 Nov", "R9", "ACH-E", "drill", "DDR", "51", "3,300", "3,300", "2,700", "3,300", "0", "9.6", "24.0", "approved"),
        ("11 Nov", "R9", "ACH-E", "drill", "DDR", "50", "3,140", "3,300", "2,600", "3,290", "160", "9.6", "24.0", "approved"),
    ]
    y = 122
    for row in data:
        x = 24
        for val, w in zip(row, widths):
            c.text(x, y, val, "xs", TEXT if val not in ("approved", "submitted") else (SUCCESS_FG if val == "approved" else INFO_FG))
            x += w
        c.line(24, y + 16, 720, y + 16, DIVIDER)
        y += 24
    c.text(24, y + 8, "No programme column: the reader cannot see which activity the month moved,", "xs", MUTED)
    c.text(24, y + 22, "and must open every report to find out. 17 header columns already push the grid wide.", "xs", MUTED)

    # ---- after -----------------------------------------------------------
    c.text(756, 82, "AFTER — grouped by programme activity", "xbs", PRIMARY)
    c.rect(756, 96, W - 780, 40, fill="#F6F8F8", outline=DIVIDER, r=6)
    c.text(768, 108, "Programme v3 · 12 activities · 6 reports this period", "bs")
    c.chip(1120, 105, "show only activities with hours", PRIMARY, PRIMARY_SOFT, INFO_BD, h=19)
    c.chip(1290, 105, "12 / 12 open", NEUTRAL_FG, NEUTRAL_BG, NEUTRAL_BD, h=19)

    groups = [
        ("11", 'Drill 12¼" 2,700–2,900 m', "40.000", "43.500", "lag 3.500 h", "0.146 d", "finished", ERROR_FG, ERROR_BG, ERROR_BD, 1.0),
        ("12", 'Drill 12¼" 2,900–3,050 m', "8.000", "6.500", "1.500 h left", "—", "in progress", INFO_FG, INFO_BG, INFO_BD, 0.81),
        ("13", 'Run 9⅝" casing', "6.000", "2.500", "3.500 h left", "—", "in progress", INFO_FG, INFO_BG, INFO_BD, 0.42),
        ("14", "Cement job", "4.000", "6.000", "lag 2.000 h · SP", "0.083 d", "finished", ERROR_FG, ERROR_BG, ERROR_BD, 1.0),
        ("15", "Trip in hole with BHA", "7.000", "2.000", "5.000 h left", "—", "in progress", INFO_FG, INFO_BG, INFO_BD, 0.29),
        ("16", "Displace to brine", "3.000", "0.000", "3.000 h left", "—", "not started", NEUTRAL_FG, NEUTRAL_BG, NEUTRAL_BD, 0.0),
        ("17", "Rig up cement unit", "2.500", "0.000", "2.500 h left", "—", "not started", NEUTRAL_FG, NEUTRAL_BG, NEUTRAL_BD, 0.0),
        ("18", "Skipped · no cement head", "3.000", "—", "3.000 h released", "—", "skipped", MUTED, NEUTRAL_BG, NEUTRAL_BD, 0.0),
    ]
    hx = [("SEQ", 768, 34), ("ACTIVITY", 806, 250), ("PLAN", 1062, 54), ("LOGGED", 1120, 54), ("LEFT", 1178, 92), ("OUTCOME", 1274, 78), ("STATE", 1356, 76)]
    for label, x, _w in hx:
        c.text(x, 146, label, "xbs", DISABLED)
    c.line(756, 162, W - 20, 162, DIVIDER)
    y = 172
    for seq, desc, plan, logged, left, days, state, fg, bg, bd, frac in groups:
        c.text(768, y + 6, seq, "mono", TEXT)
        c.text(806, y + 1, desc, "b" if state != "skipped" else "s", TEXT if state != "skipped" else DISABLED)
        c.text(806, y + 16, "", "xs", MUTED)
        c.bar(806, y + 30, 200, 4, frac, BRASS if frac < 1 else (ERROR_FG if "lag" in left else SUCCESS_FG), over="lag" in left)
        c.text(1062, y + 6, plan, "xs", MUTED)
        c.text(1120, y + 6, logged, "xs", TEXT)
        c.text(1178, y + 6, left, "xs", fg)
        c.text(1274, y + 6, days, "xs", fg if days != "—" else DISABLED)
        c.chip(1356, y + 3, state, fg, bg, bd, h=18)
        c.line(756, y + 38, W - 20, y + 38, DIVIDER)
        y += 40

    # unplanned row
    c.rect(756, y + 2, W - 780, 34, fill=WARNING_BG, outline=WARNING_BD, r=6)
    c.text(768, y + 11, "—", "mono", WARNING_FG)
    c.text(806, y + 4, "Unplanned activity (no sequence)", "bs", WARNING_FG)
    c.text(806, y + 19, "NPT 3.000 + UPA 2.000 + no code 7.000 = 12.000 h", "xs", WARNING_FG)
    c.text(1120, y + 11, "12.000", "mono", WARNING_FG)
    c.text(1274, y + 11, "−0.500 d", "mono", WARNING_FG)

    # totals strip
    ty = y + 54
    c.rect(756, ty, W - 780, 96, fill=PRIMARY_SOFT, outline=INFO_BD, r=8)
    c.text(768, ty + 10, "SEQUENCE OUTCOME for this programme", "xbs", PRIMARY)
    c.text(768, ty + 26, "−0.729 d lag", "kpi", ERROR_FG)
    c.text(960, ty + 30, "the 2 finished codes here −5.500 h, less 12.000 h unplanned = −17.500 h ÷ 24", "xs", MUTED)
    c.text(960, ty + 44, "+ 3.000 h released by the skipped sequence (shown, not netted by default)", "xs", MUTED)
    c.text(768, ty + 62, "SCHEDULE POSITION  +0.750 d ahead", "bs", SUCCESS_FG)
    c.text(1010, ty + 62, "a different question: planned curve at the checkpoint − elapsed days", "xs", MUTED)

    c.text(24, H - 46, "Nothing here changes a signed month: the strip counts submitted + approved reports, with draft hours shown beside it as “+7.600 h in drafts”.", "s", MUTED)
    c.text(24, H - 28, "Registers keep DataTable: search, advanced + date filters, 20/50/100 pagination, CSV/XLSX/PDF export and checked-row export.", "s", MUTED)

    c.save("05-reports-register.png")


if __name__ == "__main__":
    figure_workspace()
    figure_assignment()
    figure_skip()
    figure_calculation()
    figure_register()
