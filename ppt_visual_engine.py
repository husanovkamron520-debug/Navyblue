"""Native, editable visual extensions for Navyblue's premium PPTX renderer.

Original implementation inspired by public presentation-design patterns; no third-party
templates or source files are vendored. All diagrams are PowerPoint-native shapes/charts.
"""
import math


def _nm(self, shape, name):
    try:
        if hasattr(self, "_nm"):
            self._nm(shape, name)
        else:
            shape.name = name
    except Exception:
        pass
    return shape


def _connector(self, slide, x1, y1, x2, y2, color="soft", width=1.5, arrow=False):
    line = slide.shapes.add_connector(
        1, self.Inches(x1), self.Inches(y1), self.Inches(x2), self.Inches(y2)
    )
    try:
        line.line.color.rgb = self.col(color)
        line.line.width = self.Pt(width)
        if arrow:
            from pptx.oxml.ns import qn
            from lxml import etree
            ln = line.line._get_or_add_ln()
            for old_end in ln.findall(qn("a:headEnd")):
                ln.remove(old_end)
            head = etree.SubElement(ln, qn("a:headEnd"))
            head.set("type", "triangle")
            head.set("w", "med")
            head.set("len", "med")
    except Exception:
        pass
    return line


def _title(self, slide, title):
    if hasattr(self, "_v8_title_left"):
        self._v8_title_left(slide, title)
    else:
        self.title(slide, title)


def render_cards_varied(self, sl):
    """Turn the same card data into genuinely different compositions."""
    cards = sl.get("cards") or []
    comp = getattr(self, "_cur_comp", "modular")
    s = self.new_slide()
    _title(self, s, sl["title"])
    colors = ["b1", "b2", "b3", "brown"]
    if comp in {"editorial_split", "editorial_rows"} and len(cards) >= 3:
        # Editorial: one dominant idea + compact evidence rail.
        first = cards[0]
        self.box(s, 1.0, 2.05, 5.0, 4.65, fill="hdr1", line=None, rounded=True, radius=0.06)
        self.text(s, 1.35, 2.38, 4.25, 0.42, "01 / ASOSIY G'OYA", 11, "white", True, "l", "m", self.tf)
        self.icon_badge(s, first.get("icon", "star"), 2.0, 3.0, 1.0, "brown")
        self.text(s, 1.35, 4.12, 4.25, 0.85, first["head"],
                  self.fit(first["head"], 4.15, 0.85, 27, 15, 0.58, 1.08), "white", True, "l", "m", self.tf)
        self.text(s, 1.35, 5.05, 4.25, 1.25, first["text"],
                  self.fit(first["text"], 4.1, 1.25, 17, 10), "white", False, "l", "t")
        rest = cards[1:]
        row_h = 4.45 / max(1, len(rest))
        for i, c in enumerate(rest):
            y = 2.12 + i * row_h
            self.text(s, 6.55, y, 0.55, 0.45, f"{i + 2:02d}", 18, colors[i % 4], True, "l", "m", self.tf)
            self.text(s, 7.25, y, 4.9, 0.48, c["head"],
                      self.fit(c["head"], 4.8, 0.48, 19, 12, 0.6, 1.08), "dark", True, "l", "m", self.tf)
            self.text(s, 7.25, y + 0.52, 4.85, max(0.42, row_h - 0.62), c["text"],
                      self.fit(c["text"], 4.8, max(0.42, row_h - 0.62), 14, 9), "text", False, "l", "t")
            if i < len(rest) - 1:
                self.box(s, 7.25, y + row_h - 0.06, 4.7, 0.015, fill="line", line=None)
    elif comp in {"asym_grid", "asym_cards"} and len(cards) >= 3:
        # Asymmetric magazine grid: wide lead card, smaller supporting blocks.
        first = cards[0]
        self.box(s, 1.0, 2.05, 6.2, 4.65, fill="card", line="line", rounded=True, radius=0.06)
        self.icon_badge(s, first.get("icon", "star"), 1.85, 2.48, 0.95, "b1")
        self.text(s, 1.45, 3.65, 5.25, 0.75, first["head"],
                  self.fit(first["head"], 5.15, 0.75, 26, 15, 0.58, 1.08), "dark", True, "l", "m", self.tf)
        self.text(s, 1.45, 4.52, 5.2, 1.7, first["text"],
                  self.fit(first["text"], 5.1, 1.7, 18, 11), "text", False, "l", "t")
        rest = cards[1:]
        rh = 4.65 / len(rest)
        for i, c in enumerate(rest):
            y = 2.05 + i * rh
            self.box(s, 7.48, y, 4.85, rh - 0.12, fill="card", line="line", rounded=True, radius=0.05)
            self.icon_badge(s, c.get("icon", "star"), 8.02, y + 0.18, 0.65, colors[(i + 1) % 4])
            self.text(s, 8.52, y + 0.16, 3.5, 0.42, c["head"],
                      self.fit(c["head"], 3.4, 0.42, 17, 11, 0.58, 1.08), "dark", True, "l", "m", self.tf)
            self.text(s, 8.52, y + 0.62, 3.48, max(0.35, rh - 0.8), c["text"],
                      self.fit(c["text"], 3.4, max(0.35, rh - 0.8), 13, 9), "text", False, "l", "t")
    elif comp == "layered":
        # Editorial numbered rows instead of repeated equal-size cards.
        row_h = min(1.28, 4.55 / max(1, len(cards)))
        for i, c in enumerate(cards):
            y = 2.0 + i * (row_h + 0.12)
            self.box(s, 1.0 + i * 0.08, y, 11.25 - i * 0.16, row_h,
                     fill="card", line="line", rounded=True, radius=0.05)
            self._v8_oval(s, 1.62 + i * 0.08, y + row_h / 2, 0.58, colors[i % 4])
            self.text(s, 1.34 + i * 0.08, y + row_h / 2 - 0.22, 0.56, 0.44,
                      str(i + 1), 15, "white", True, "c", "m", self.tf)
            self.text(s, 2.15, y + 0.12, 3.05, row_h - 0.2, c["head"],
                      self.fit(c["head"], 2.95, row_h - 0.2, 19, 12, 0.58, 1.08), "dark", True, "l", "m", self.tf)
            self.text(s, 5.35, y + 0.12, 6.45, row_h - 0.2, c["text"],
                      self.fit(c["text"], 6.3, row_h - 0.2, 15, 9), "text", False, "l", "m")
    else:
        # Original equal-column grid remains available as one option, not the default for all decks.
        n = len(cards)
        gap, total = 0.3, 11.33
        cw = (total - gap * (n - 1)) / n
        for i, c in enumerate(cards):
            x = 1.0 + i * (cw + gap)
            self.box(s, x, 2.0, cw, 4.6)
            self.icon_badge(s, c.get("icon", "star"), x + cw / 2, 2.25, 0.85, colors[i % 4])
            self.text(s, x + 0.12, 3.2, cw - 0.24, 0.75, c["head"],
                      self.fit(c["head"], cw - 0.3, 0.75, 16, 12, 0.6, 1.2), "dark", True, "c", "m", self.tf)
            self.text(s, x + 0.2, 4.05, cw - 0.4, 2.45, c["text"],
                      self.fit(c["text"], cw - 0.4, 2.45, 17, 10), "text", False, "l", "t")
    self.notes(s, sl.get("notes"))


def render_waterfall(self, sl):
    """Editable waterfall diagram; values are explicitly represented as deltas/totals."""
    s = self.new_slide()
    _title(self, s, sl["title"])
    steps = sl["steps"]
    running, points = 0.0, []
    for item in steps:
        value = float(item["value"])
        kind = item.get("kind", "delta")
        start = 0.0 if kind == "total" else running
        end = value if kind == "total" else running + value
        points.append((start, end, value, item))
        running = end
    lo = min([0.0] + [min(a, b) for a, b, _, _ in points])
    hi = max([0.0] + [max(a, b) for a, b, _, _ in points])
    span = max(1.0, hi - lo)
    x0, plot_top, plot_bottom = 1.15, 2.15, 5.85
    plot_h, total_w, gap = plot_bottom - plot_top, 11.0, 0.28
    n = len(points)
    bw = min(1.25, (total_w - gap * (n - 1)) / n)
    actual = n * bw + (n - 1) * gap
    x0 += (total_w - actual) / 2
    def yy(v):
        return plot_bottom - ((v - lo) / span) * plot_h
    zero_y = yy(0.0)
    _connector(self, s, 0.95, zero_y, 12.38, zero_y, "soft", 1.0)
    for i, (a, b, value, item) in enumerate(points):
        x = x0 + i * (bw + gap)
        top, bottom = min(yy(a), yy(b)), max(yy(a), yy(b))
        h = max(0.08, bottom - top)
        kind = item.get("kind", "delta")
        color = "b2" if kind == "total" else ("b3" if value >= 0 else "hdr2")
        rect = self.box(s, x, top, bw, h, fill=color, line=None, rounded=True, radius=0.04)
        _nm(self, rect, f"!!waterfall_{i+1}")
        val_text = f"{value:+g}" if kind != "total" else f"{b:g}"
        self.text(s, x - 0.08, max(1.78, top - 0.38), bw + 0.16, 0.3,
                  val_text, 12, "dark", True, "c", "m", self.tf)
        self.text(s, x - 0.12, 5.98, bw + 0.24, 0.62, item["label"],
                  self.fit(item["label"], bw + 0.15, 0.62, 13, 8, 0.55, 1.0), "text", True, "c", "t", self.tf)
        if i < n - 1:
            next_x = x + bw + gap
            level = yy(b)
            _connector(self, s, x + bw, level, next_x, level, "soft", 1.0)
    if sl.get("text"):
        self.text(s, 1.0, 6.72, 11.3, 0.28, sl["text"],
                  self.fit(sl["text"], 11.2, 0.28, 12, 8), "text", False, "l", "m")
    self.notes(s, sl.get("notes"))


def render_swimlane(self, sl):
    """Editable cross-functional process lanes; each lane owns its own steps."""
    s = self.new_slide()
    _title(self, s, sl["title"])
    lanes = sl["lanes"]
    left, label_w, right = 1.0, 1.75, 12.3
    top, lane_gap = 2.0, 0.12
    lane_h = min(1.45, (4.7 - lane_gap * (len(lanes) - 1)) / len(lanes))
    max_steps = max(len(x["steps"]) for x in lanes)
    usable = right - left - label_w - 0.45
    step_gap = 0.16
    step_w = min(2.1, (usable - (max_steps - 1) * step_gap) / max_steps)
    for li, lane in enumerate(lanes):
        y = top + li * (lane_h + lane_gap)
        self.box(s, left, y, label_w, lane_h, fill=("hdr1" if li % 2 == 0 else "hdr2"),
                 line=None, rounded=True, radius=0.04)
        self.text(s, left + 0.12, y + 0.08, label_w - 0.24, lane_h - 0.16, lane["label"],
                  self.fit(lane["label"], label_w - 0.3, lane_h - 0.2, 16, 10, 0.55, 1.0),
                  "white", True, "c", "m", self.tf)
        for si, step in enumerate(lane["steps"]):
            x = left + label_w + 0.28 + si * (step_w + step_gap)
            self.box(s, x, y, step_w, lane_h, fill="card", line="line", rounded=True, radius=0.04)
            self.text(s, x + 0.1, y + 0.08, step_w - 0.2, 0.34, step["label"],
                      self.fit(step["label"], step_w - 0.25, 0.34, 13, 9, 0.55, 1.0),
                      "dark", True, "c", "m", self.tf)
            if step.get("detail"):
                self.text(s, x + 0.1, y + 0.45, step_w - 0.2, lane_h - 0.5, step["detail"],
                          self.fit(step["detail"], step_w - 0.25, lane_h - 0.52, 10, 7.5),
                          "text", False, "c", "m")
            if si < len(lane["steps"]) - 1:
                _connector(self, s, x + step_w + 0.015, y + lane_h / 2,
                           x + step_w + step_gap - 0.02, y + lane_h / 2, "brown", 1.5, True)
    self.notes(s, sl.get("notes"))


def render_network(self, sl):
    """Native node-link diagram. Only explicit links supplied by the outline are drawn."""
    s = self.new_slide()
    _title(self, s, sl["title"])
    nodes, links = sl["nodes"], sl["links"]
    cx, cy, rx, ry = 6.65, 4.35, 4.35, 2.05
    n = len(nodes)
    positions = []
    start = 90.0
    for i in range(n):
        a = math.radians(start - i * 360.0 / n)
        positions.append((cx + rx * math.cos(a), cy - ry * math.sin(a)))
    # Edges first, so connectors remain behind the editable node cards.
    for edge in links:
        i, j = edge["from"], edge["to"]
        x1, y1 = positions[i]
        x2, y2 = positions[j]
        dx, dy = x2 - x1, y2 - y1
        sx = min(1.0, 1.175 / abs(dx)) if dx else 1.0
        sy = min(1.0, 0.525 / abs(dy)) if dy else 1.0
        source_t = min(sx, sy)
        ex = min(1.0, 1.175 / abs(dx)) if dx else 1.0
        ey = min(1.0, 0.525 / abs(dy)) if dy else 1.0
        target_t = min(ex, ey)
        _connector(self, s, x1 + dx * source_t, y1 + dy * source_t,
                   x2 - dx * target_t, y2 - dy * target_t, "soft", 1.8, True)
        if edge.get("label"):
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            self.box(s, mx - 0.52, my - 0.17, 1.04, 0.34, fill="bg", line=None, rounded=True, radius=0.08)
            self.text(s, mx - 0.5, my - 0.16, 1.0, 0.31, edge["label"],
                      self.fit(edge["label"], 0.95, 0.3, 9, 7), "text", True, "c", "m", self.tf)
    colors = ["hdr1", "b1", "b2", "hdr2", "brown", "b3", "tan"]
    for i, (node, (x, y)) in enumerate(zip(nodes, positions)):
        w, h = 2.35, 1.05
        card = self.box(s, x - w / 2, y - h / 2, w, h, fill="card", line="line", rounded=True, radius=0.06)
        _nm(self, card, f"!!network_node_{i+1}")
        self.box(s, x - w / 2, y - h / 2, 0.08, h, fill=colors[i % len(colors)], line=None)
        self.text(s, x - w / 2 + 0.2, y - 0.38, w - 0.35, 0.36, node["label"],
                  self.fit(node["label"], w - 0.45, 0.36, 15, 9, 0.55, 1.0),
                  "dark", True, "c", "m", self.tf)
        if node.get("detail"):
            self.text(s, x - w / 2 + 0.18, y + 0.02, w - 0.32, 0.38, node["detail"],
                      self.fit(node["detail"], w - 0.4, 0.38, 10, 7.5),
                      "text", False, "c", "m")
    if sl.get("text"):
        self.text(s, 1.0, 6.72, 11.3, 0.28, sl["text"],
                  self.fit(sl["text"], 11.2, 0.28, 12, 8), "text", False, "c", "m")
    self.notes(s, sl.get("notes"))


def render_quote(self, sl):
    """Editorial quotation slide with an explicit attribution field."""
    s = self.new_slide()
    _title(self, s, sl["title"])
    self._kicker(s, sl.get("kicker") or "IQTIBOS", 1.05, 1.72)
    self.text(s, 0.9, 2.0, 1.45, 1.6, "“", 112, "brown", True, "c", "m", self.tf)
    quote = sl["quote"]
    self.text(s, 2.1, 2.12, 9.9, 2.65, quote,
              self.fit(quote, 9.7, 2.6, 36, 19, 0.56, 1.12), "dark", True, "l", "m", self.tf)
    self.box(s, 2.12, 5.0, 1.05, 0.055, fill="brown", line=None)
    if sl.get("attribution"):
        self.text(s, 2.12, 5.25, 9.7, 0.5, sl["attribution"],
                  self.fit(sl["attribution"], 9.6, 0.5, 17, 11), "brown", True, "l", "m", self.tf)
    if sl.get("context"):
        self.text(s, 2.12, 5.82, 9.7, 0.58, sl["context"],
                  self.fit(sl["context"], 9.6, 0.58, 13, 8), "text", False, "l", "t")
    if sl.get("source"):
        self.text(s, 2.12, 6.42, 9.7, 0.25, "Manba: " + sl["source"],
                  self.fit("Manba: " + sl["source"], 9.6, 0.25, 9, 7), "brown", False, "l", "m")
    self.notes(s, sl.get("notes"))


def render_extended_chart(self, sl, original):
    ct = sl.get("chart_type", "donut")
    supplied_series = sl.get("series") or []
    extended = ct in ("area", "bar_horizontal", "radar", "stacked_bar") or bool(supplied_series)
    if not extended:
        return original(sl)
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
    I, Pt = self.Inches, self.Pt
    s = self.new_slide()
    self.title(s, sl["title"])
    if sl.get("text"):
        self.text(s, 1.0, 1.75, 11.33, 0.72, sl["text"],
                  self.fit(sl["text"], 11.2, 0.72, 15, 10), "text", False, "c", "m")
    pts = sl["data"]
    cd = CategoryChartData()
    cd.categories = [p["label"] for p in pts]
    series = supplied_series or [{"name": "Ko'rsatkich", "values": [p["value"] for p in pts]}]
    if ct == "donut" and supplied_series:
        ct = "bar"
    for item in series:
        cd.add_series(item["name"], item["values"])
    kinds = {
        "area": XL_CHART_TYPE.AREA,
        "bar_horizontal": XL_CHART_TYPE.BAR_CLUSTERED,
        "radar": getattr(XL_CHART_TYPE, "RADAR_MARKERS", XL_CHART_TYPE.RADAR),
        "stacked_bar": getattr(XL_CHART_TYPE, "COLUMN_STACKED", XL_CHART_TYPE.COLUMN_CLUSTERED),
        "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
        "line": XL_CHART_TYPE.LINE_MARKERS,
    }
    kind = kinds.get(ct, XL_CHART_TYPE.COLUMN_CLUSTERED)
    gf = s.shapes.add_chart(kind, I(1.1), I(2.55), I(11.1), I(4.0), cd)
    ch, plot = gf.chart, gf.chart.plots[0]
    ch.has_title = False
    ch.has_legend = len(series) > 1
    if ch.has_legend:
        ch.legend.position = XL_LEGEND_POSITION.BOTTOM
        ch.legend.include_in_layout = False
        ch.legend.font.size = Pt(10)
    ch.font.size = Pt(11)
    ch.font.name = self.bf
    ch.font.color.rgb = self.col("text")
    plot.has_data_labels = True
    plot.data_labels.show_value = True
    plot.data_labels.font.size = Pt(10)
    plot.data_labels.font.bold = True
    plot.data_labels.font.color.rgb = self.col("dark")
    palette = self.pal.get("donut") or [self.pal.get("b1"), self.pal.get("b2"), self.pal.get("b3"), self.pal.get("brown")]
    for i, ser in enumerate(plot.series):
        color = palette[i % len(palette)]
        if ct in ("area", "stacked_bar", "bar_horizontal", "bar"):
            ser.format.fill.solid()
            ser.format.fill.fore_color.rgb = self.col(color)
            if ct == "area":
                ser.format.line.color.rgb = self.col(color)
                ser.format.line.width = Pt(1.8)
        else:
            ser.format.line.color.rgb = self.col(color)
            ser.format.line.width = Pt(2.5)
            try:
                ser.marker.format.fill.solid()
                ser.marker.format.fill.fore_color.rgb = self.col(color)
                ser.marker.size = 7
            except Exception:
                pass
    try:
        if ct in ("bar", "bar_horizontal", "stacked_bar"):
            plot.gap_width = 55
        ch.value_axis.has_major_gridlines = True
        ch.value_axis.major_gridlines.format.line.color.rgb = self.col("soft")
        ch.value_axis.format.line.fill.background()
        ch.category_axis.tick_labels.font.size = Pt(10)
        ch.value_axis.tick_labels.font.size = Pt(9)
        if ct in ("area", "line"):
            plot.data_labels.position = XL_LABEL_POSITION.ABOVE
    except Exception:
        pass
    note = sl.get("data_note") or "Namunaviy ma'lumot — haqiqiy statistika sifatida talqin qilmang."
    self.text(s, 1.0, 6.7, 11.3, 0.28, note,
              self.fit(note, 11.2, 0.28, 10, 7.5), "brown", False, "r", "m")
    self.notes(s, sl.get("notes"))


def install(builder_class, layout_set, composition_set):
    """Install compatible visual extensions after the existing builder is defined."""
    new_layouts = {"waterfall", "swimlane", "network", "quote"}
    layout_set.update(new_layouts)
    composition_set.update({"network_graph", "waterfall", "swimlane", "quote_stage", "editorial_rows", "asym_cards"})
    builder_class._pptx_render_waterfall = render_waterfall
    builder_class._pptx_render_swimlane = render_swimlane
    builder_class._pptx_render_network = render_network
    builder_class._pptx_render_quote = render_quote
    old_build_one = builder_class._build_one
    def build_one(self, sl):
        layout = sl.get("layout")
        if layout == "waterfall":
            return self._pptx_render_waterfall(sl)
        if layout == "swimlane":
            return self._pptx_render_swimlane(sl)
        if layout == "network":
            return self._pptx_render_network(sl)
        if layout == "quote":
            return self._pptx_render_quote(sl)
        return old_build_one(self, sl)
    builder_class._build_one = build_one
    old_cards = builder_class.cards
    def cards(self, sl):
        comp = getattr(self, "_cur_comp", "modular")
        if comp in {"editorial_split", "asym_grid", "layered"}:
            return render_cards_varied(self, sl)
        return old_cards(self, sl)
    builder_class.cards = cards
    old_chart = builder_class.chart
    def chart(self, sl):
        return render_extended_chart(self, sl, old_chart)
    builder_class.chart = chart
