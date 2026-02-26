"""SmartThings Desktop Dashboard (tkinter)
- Reads smartthings_collector.dashboard_state directly
- Refreshed only by collector callback (no polling)
- Plug: power/energy graph
- Motion sensor: motion/temperature graph
"""

import tkinter as tk
from tkinter import ttk
import logging
import csv
import os
import glob
from datetime import datetime
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib import rcParams

# Font settings
rcParams["font.family"] = "Segoe UI"
rcParams["axes.unicode_minus"] = False

# Device alias mapping
DEVICE_ALIAS = {
    "SMP02": "Jeein PC",
    "SMP03": "Smart TV",
    "SMP04": "Humidifier",
    "SMP05": "Refrigerator",
    "SMP16": "Printer",
    "SMP17": "Meeting Laptop Charger",
    "SMP18": "Jeein Monitor",
    "SMP19": "Junhee Monitor",
    "SMP20": "Junhee PC",
    "SMP21": "Haewon Monitor",
    "SMP22": "Speaker",
    "SMP23": "Haewon PC",
    "MS1": "Entrance",
    "MS2": "Between Junhee/Jeein (Rear)",
    "MS3": "Between Jeein/Haewon (Front)",
    "MS4": "Meeting Table (Rear)",
    "MS5": "Meeting Table (Front)",
    "MS6": "Meeting Wall (Left)",
    "MS7": "Below Smart TV (Left)",
    "MS8": "Meeting Wall (Right)",
}

# Color palette
BG      = "#0f1117"
CARD_BG = "#1a1d27"
BORDER  = "#2d3148"
FG      = "#e2e8f0"
MUTED   = "#64748b"
GREEN   = "#22c55e"
RED     = "#ef4444"
BLUE    = "#60a5fa"
YELLOW  = "#fbbf24"
ORANGE  = "#fb923c"


def get_alias(label: str) -> str:
    return DEVICE_ALIAS.get(label.upper(), "")

def device_display_name(label: str) -> str:
    name = DEVICE_ALIAS.get(label.upper())
    return f"{name} ({label})" if name else label


class Dashboard(tk.Tk):
    def __init__(self, collector_module):
        super().__init__()
        self.collector = collector_module
        self.title("SmartThings Data Collector")
        self.geometry("1400x700")
        self.configure(bg=BG)
        self.resizable(True, True)
        self._build_ui()
        collector_module.on_data_updated = self._on_collected
        self._refresh()

    # ──────────────────────────────
    # UI Setup
    # ──────────────────────────────
    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self, bg=CARD_BG, pady=12)
        header.pack(fill="x")

        self.dot = tk.Label(header, text="●", fg=YELLOW, bg=CARD_BG, font=("Segoe UI", 12))
        self.dot.pack(side="left", padx=(16, 6))

        tk.Label(
            header, text="SmartThings Data Collector",
            fg=FG, bg=CARD_BG, font=("Segoe UI", 13, "bold")
        ).pack(side="left")

        self.lbl_token = tk.Label(
            header, text="Token Expires: Loading...",
            fg=MUTED, bg=CARD_BG, font=("Segoe UI", 10)
        )
        self.lbl_token.pack(side="right", padx=16)

        # ── Summary cards ──
        card_frame = tk.Frame(self, bg=BG, pady=16)
        card_frame.pack(fill="x", padx=16)

        self.lbl_total   = self._make_card(card_frame, "Total Devices",  "-", BLUE)
        self.lbl_success = self._make_card(card_frame, "Success",  "-", GREEN)
        self.lbl_fail    = self._make_card(card_frame, "Failed",  "-", RED)
        self.lbl_status  = self._make_card(card_frame, "Status",  "-", YELLOW)

        # ── Divider ──
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16)

        tk.Label(
            self, text="Device Status",
            fg=MUTED, bg=BG, font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=16, pady=(12, 4))

        # ── Treeview table ──
        table_frame = tk.Frame(self, bg=BG)
        table_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Custom.Treeview",
            background=CARD_BG, foreground=FG, fieldbackground=CARD_BG,
            rowheight=30, font=("Segoe UI", 10), borderwidth=0,
        )
        style.configure("Custom.Treeview.Heading",
            background="#13151f", foreground=MUTED,
            font=("Segoe UI", 9, "bold"), relief="flat",
        )
        style.map("Custom.Treeview",
            background=[("selected", "#1e2235")],
            foreground=[("selected", FG)],
        )

        cols = ("label", "alias", "location", "room", "type",
                "power", "energy", "motion", "temp", "status", "updated")
        self.tree = ttk.Treeview(
            table_frame, columns=cols, show="headings",
            style="Custom.Treeview", selectmode="browse"
        )

        headers = {
            "label":    ("Label",        90),
            "alias":    ("Alias",    160),
            "location": ("Location",         110),
            "room":     ("Room",            90),
            "type":     ("Type",           60),
            "power":    ("Power (W)",       85),
            "energy":   ("Energy (Wh)",   110),
            "motion":   ("Motion",           70),
            "temp":     ("Temp (°C)",      80),
            "status":   ("Status",           60),
            "updated":  ("Last Updated",   150),
        }
        center_cols = {"type", "power", "energy", "motion", "temp", "status"}
        for col, (head, width) in headers.items():
            self.tree.heading(col, text=head)
            self.tree.column(col, width=width, anchor="center" if col in center_cols else "w")

        self.tree.tag_configure("success", foreground=GREEN)
        self.tree.tag_configure("fail",    foreground=RED)
        self.tree.tag_configure("plug",    foreground=BLUE)
        self.tree.tag_configure("motion",  foreground=ORANGE)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_device_click)

        # ── Status bar ──
        statusbar = tk.Frame(self, bg="#13151f", pady=5)
        statusbar.pack(fill="x", side="bottom")
        tk.Label(
            statusbar, text="Auto-refresh on collection (60s interval)  |  Double-click device for graph",
            fg=MUTED, bg="#13151f", font=("Segoe UI", 9)
        ).pack(side="left", padx=12)
        self.lbl_refreshed = tk.Label(
            statusbar, text="-", fg=MUTED, bg="#13151f", font=("Segoe UI", 9)
        )
        self.lbl_refreshed.pack(side="right", padx=12)

    def _make_card(self, parent, label_text, value_text, color):
        frame = tk.Frame(
            parent, bg=CARD_BG, bd=1, relief="flat",
            highlightbackground=BORDER, highlightthickness=1
        )
        frame.pack(side="left", expand=True, fill="both", padx=6)
        tk.Label(frame, text=label_text, fg=MUTED, bg=CARD_BG,
                 font=("Segoe UI", 9), pady=8).pack()
        lbl = tk.Label(frame, text=value_text, fg=color, bg=CARD_BG,
                       font=("Segoe UI", 24, "bold"), pady=4)
        lbl.pack(pady=(0, 10))
        return lbl

    # ──────────────────────────────
    # Data Refresh
    # ──────────────────────────────
    def _on_collected(self):
        """Collector thread → safely forward to main thread."""
        self.after(0, self._refresh)

    def _refresh(self):
        try:
            state = self.collector.dashboard_state

            self.lbl_total.config(text=str(state.get("total", 0)))
            self.lbl_success.config(text=str(state.get("success", 0)))
            self.lbl_fail.config(text=str(state.get("fail", 0)))
            self.lbl_status.config(text=state.get("status", "Initializing"))

            status = state.get("status", "")
            self.dot.config(fg=GREEN if status == "Collecting" else YELLOW)

            expires = state.get("token_expires")
            self.lbl_token.config(
                text=f"Token Expires: {expires}" if expires else "No token info"
            )

            self.tree.delete(*self.tree.get_children())

            def sort_key(d):
                import re
                label = d.get("label", "")
                nums = re.findall(r'\d+', label)
                # (device type prefix, number) — e.g. "SMP02" → ("SMP", 2), "Motion Sensor 3" → ("Motion Sensor ", 3)
                prefix = re.split(r'\d', label)[0]
                return (prefix, int(nums[0]) if nums else 0)

            for d in sorted(state.get("devices", []), key=sort_key):
                dev_type = d.get("type", "")

                # Plug-specific values
                power  = f"{d['power']} W" if d.get("power") not in (None, "-") else "-"
                try:
                    energy = f"{float(d['energy']):.1f} Wh" if d.get("energy") not in (None, "-") else "-"
                except (ValueError, TypeError):
                    energy = "-"

                # Motion-specific values
                motion = d.get("motion", "-")
                temp   = f"{d['temp']}°C" if d.get("temp") not in (None, "-") else "-"

                type_label = "Plug" if dev_type == "plug" else "Motion"
                tag = "success" if d["status"] == "OK" else "fail"

                self.tree.insert("", "end", values=(
                    d["label"],
                    get_alias(d["label"]),
                    d.get("location", "-"),
                    d.get("room", "-") or "-",
                    type_label,
                    power, energy, motion, temp,
                    d["status"], d["updated"]
                ), tags=(tag,))

            self.lbl_refreshed.config(
                text=f"Last refresh: {datetime.now().strftime('%H:%M:%S')}"
            )
        except Exception as e:
            logging.error(f"UI refresh error: {e}")

    # ──────────────────────────────
    # Graph Window
    # ──────────────────────────────
    def _on_device_click(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        if not values:
            return
        label    = values[0]   # device label (e.g. SMP18, Motion Sensor 1)
        dev_type = values[4]   # "Plug" or "Motion"
        self._open_graph_window(label, dev_type)

    def _find_csv_files(self, label):
        base    = "C:/smartthings_data/csv_data"
        pattern = os.path.join(base, "**", f"{label}_*.csv")
        return sorted(glob.glob(pattern, recursive=True))

    def _load_plug_csv(self, label, days=1):
        """Plug CSV: returns timestamp, power, energy."""
        files = self._find_csv_files(label)[-days:]
        timestamps, powers, energies = [], [], []
        for fpath in files:
            try:
                with open(fpath, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        try:
                            timestamps.append(datetime.strptime(row["Timestamp"], "%Y-%m-%d %H:%M:%S"))
                            powers.append(float(row["Power (W)"]))
                            energies.append(float(row["Energy (Wh)"]))
                        except (ValueError, KeyError):
                            continue
            except Exception:
                continue
        return timestamps, powers, energies

    def _load_motion_csv(self, label, days=1):
        """Motion CSV: returns timestamp, motion(0/1), temperature."""
        files = self._find_csv_files(label)[-days:]
        timestamps, motions, temps = [], [], []
        for fpath in files:
            try:
                with open(fpath, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        try:
                            timestamps.append(datetime.strptime(row["Timestamp"], "%Y-%m-%d %H:%M:%S"))
                            motions.append(1 if row["Motion"] == "active" else 0)
                            temp_val = row.get("Temperature (°C)", "")
                            temps.append(float(temp_val) if temp_val else None)
                        except (ValueError, KeyError):
                            continue
            except Exception:
                continue
        return timestamps, motions, temps

    def _open_graph_window(self, label, dev_type):
        win = tk.Toplevel(self)
        win.title(f"{device_display_name(label)} - {'Power Usage' if dev_type == 'Plug' else 'Motion/Temp'}")
        win.geometry("900x600")
        win.configure(bg=BG)

        # ── Top header + period selector ──
        top = tk.Frame(win, bg=CARD_BG, pady=10)
        top.pack(fill="x")
        tk.Label(
            top, text=f"  {device_display_name(label)}",
            fg=FG, bg=CARD_BG, font=("Segoe UI", 12, "bold")
        ).pack(side="left", padx=8)

        days_var = tk.IntVar(value=1)
        btn_frame = tk.Frame(top, bg=CARD_BG)
        btn_frame.pack(side="right", padx=12)

        def make_btn(text, d):
            tk.Button(
                btn_frame, text=text, bg="#2d3148", fg=FG,
                activebackground="#3d4168", activeforeground=FG,
                relief="flat", padx=10, pady=4, font=("Segoe UI", 9),
                cursor="hand2",
                command=lambda: [days_var.set(d), draw()]
            ).pack(side="left", padx=3)

        make_btn("Today", 1)
        make_btn("3 Days",  3)
        make_btn("7 Days",  7)

        # ── Graph area ──
        fig    = Figure(figsize=(9, 5), facecolor=BG)
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

        no_data_lbl = tk.Label(win, text="", fg=RED, bg=BG, font=("Segoe UI", 11))
        no_data_lbl.pack()

        def style_ax(ax):
            ax.set_facecolor(CARD_BG)
            ax.tick_params(colors=MUTED, labelsize=8)
            ax.xaxis.label.set_color(MUTED)
            ax.yaxis.label.set_color(MUTED)
            for spine in ax.spines.values():
                spine.set_edgecolor(BORDER)
            ax.grid(True, color=BORDER, linewidth=0.5, linestyle="--")

        def fmt_xaxis(ax, days):
            fmt = "%H:%M" if days == 1 else "%m/%d %H:%M"
            ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
            fig.autofmt_xdate(rotation=30)

        def draw():
            days = days_var.get()
            fig.clear()
            no_data_lbl.config(text="")

            if dev_type == "Plug":
                timestamps, powers, _ = self._load_plug_csv(label, days)
                if not timestamps:
                    no_data_lbl.config(text=f"No CSV data found for '{label}'.")
                    canvas.draw()
                    return
                ax = fig.add_subplot(111)
                style_ax(ax)
                ax.plot(timestamps, powers, color=BLUE, linewidth=1.5, label="Power (W)", zorder=3)
                ax.fill_between(timestamps, powers, alpha=0.15, color=BLUE)
                ax.set_ylabel("Power (W)", color=MUTED, fontsize=9)
                ax.set_title(
                    f"{device_display_name(label)}  |  Last {days} day(s)  |  "
                    f"Avg {sum(powers)/len(powers):.2f} W  |  Max {max(powers):.2f} W",
                    color=FG, fontsize=10, pad=10
                )
                ax.legend(facecolor=CARD_BG, edgecolor=BORDER, labelcolor=FG, fontsize=9)
                fmt_xaxis(ax, days)

            else:  # Motion sensor
                timestamps, motions, temps = self._load_motion_csv(label, days)
                if not timestamps:
                    no_data_lbl.config(text=f"No CSV data found for '{label}'.")
                    canvas.draw()
                    return

                # Top: motion / Bottom: temperature (2-row layout)
                ax1 = fig.add_subplot(2, 1, 1)
                ax2 = fig.add_subplot(2, 1, 2, sharex=ax1)
                style_ax(ax1)
                style_ax(ax2)

                # Motion (active=1, inactive=0) → step chart
                ax1.step(timestamps, motions, color=ORANGE, linewidth=1.2,
                         where="post", label="Motion")
                ax1.fill_between(timestamps, motions, alpha=0.2, color=ORANGE, step="post")
                ax1.set_yticks([0, 1])
                ax1.set_yticklabels(["Inactive", "Active"], color=MUTED, fontsize=8)
                ax1.set_ylabel("Motion", color=MUTED, fontsize=9)
                ax1.set_title(
                    f"{device_display_name(label)}  |  Last {days} day(s)",
                    color=FG, fontsize=10, pad=8
                )
                ax1.legend(facecolor=CARD_BG, edgecolor=BORDER, labelcolor=FG, fontsize=9)

                # Temperature (skip None values)
                temp_pairs = [(t, v) for t, v in zip(timestamps, temps) if v is not None]
                if temp_pairs:
                    t_ts, t_vals = zip(*temp_pairs)
                    ax2.plot(t_ts, t_vals, color="#a78bfa", linewidth=1.5, label="Temp (°C)")
                    ax2.fill_between(t_ts, t_vals, alpha=0.15, color="#a78bfa")
                    avg_t = sum(t_vals) / len(t_vals)
                    ax2.set_title(
                        f"Avg {avg_t:.1f}°C  |  Max {max(t_vals):.1f}°C  |  Min {min(t_vals):.1f}°C",
                        color=MUTED, fontsize=9, pad=4
                    )
                    ax2.legend(facecolor=CARD_BG, edgecolor=BORDER, labelcolor=FG, fontsize=9)
                ax2.set_ylabel("Temp (°C)", color=MUTED, fontsize=9)
                fmt_xaxis(ax2, days)

            fig.tight_layout()
            canvas.draw()

        draw()

    # ──────────────────────────────
    # Entry Point
    # ──────────────────────────────


def run_dashboard(collector_module):
    app = Dashboard(collector_module)
    app.mainloop()
