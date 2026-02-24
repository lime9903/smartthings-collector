"""
SmartThings 데스크탑 대시보드 (tkinter)
- smartthings_collector.dashboard_state를 직접 참조
- 3초마다 UI 자동 갱신
"""

import tkinter as tk
from tkinter import ttk
import logging
import csv
import os
import glob
from datetime import datetime, timedelta
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib import rcParams

# Windows 한글 폰트 설정
rcParams["font.family"] = "Malgun Gothic"  # 맑은 고딕 (Windows 기본 한글 폰트)
rcParams["axes.unicode_minus"] = False     # 마이너스 부호 깨짐 방지

# SMP 기기 매핑 (label → 기기 설명)
DEVICE_ALIAS = {
    "SMP02": "지인 PC",
    "SMP03": "스마트 TV",
    "SMP04": "가습기",
    "SMP05": "냉장고",
    "SMP16": "프린터",
    "SMP17": "미팅 랩탑 충전용",
    "SMP18": "지인 모니터",
    "SMP19": "준희 모니터",
    "SMP20": "준희 PC",
    "SMP21": "해원 모니터",
    "SMP22": "스피커",
    "SMP23": "해원 PC",
}

def get_alias(label: str) -> str:
    """label을 대문자로 정규화 후 별칭 반환. 없으면 label 그대로."""
    return DEVICE_ALIAS.get(label.upper(), label)

def device_display_name(label: str) -> str:
    """SMP 레이블을 사람이 읽기 쉬운 이름으로 변환. 매핑 없으면 그대로 반환."""
    key = label.upper()
    name = DEVICE_ALIAS.get(key)
    return f"{name} ({label})" if name else label

class Dashboard(tk.Tk):
    def __init__(self, collector_module):
        super().__init__()
        self.collector = collector_module
        self.title("SmartThings 데이터 수집기")
        self.geometry("1000x680")
        self.configure(bg="#0f1117")
        self.resizable(True, True)
        self._build_ui()
        # 수집기 콜백 등록: 수집 완료 시 UI 갱신
        collector_module.on_data_updated = self._on_collected
        # 앱 시작 시 1회 갱신
        self._refresh()

    # ──────────────────────────────
    # UI 구성
    # ──────────────────────────────
    def _build_ui(self):
        BG      = "#0f1117"
        CARD_BG = "#1a1d27"
        BORDER  = "#2d3148"
        FG      = "#e2e8f0"
        MUTED   = "#64748b"
        GREEN   = "#22c55e"
        RED     = "#ef4444"
        BLUE    = "#60a5fa"
        YELLOW  = "#fbbf24"

        # ── 헤더 ──
        header = tk.Frame(self, bg=CARD_BG, pady=12)
        header.pack(fill="x")

        self.dot = tk.Label(
            header, text="●", fg=YELLOW, bg=CARD_BG, font=("Segoe UI", 12)
        )
        self.dot.pack(side="left", padx=(16, 6))

        tk.Label(
            header, text="SmartThings 데이터 수집기",
            fg=FG, bg=CARD_BG, font=("Segoe UI", 13, "bold")
        ).pack(side="left")

        self.lbl_token = tk.Label(
            header, text="토큰 만료: 로딩 중...",
            fg=MUTED, bg=CARD_BG, font=("Segoe UI", 10)
        )
        self.lbl_token.pack(side="right", padx=16)

        # ── 요약 카드 4개 ──
        card_frame = tk.Frame(self, bg=BG, pady=16)
        card_frame.pack(fill="x", padx=16)

        self.lbl_total   = self._make_card(card_frame, "전체 기기", "-", BLUE)
        self.lbl_success = self._make_card(card_frame, "수집 성공", "-", GREEN)
        self.lbl_fail    = self._make_card(card_frame, "수집 실패", "-", RED)
        self.lbl_status  = self._make_card(card_frame, "수집 상태", "-", YELLOW)

        # ── 구분선 ──
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16)

        # ── 테이블 제목 ──
        tk.Label(
            self, text="기기별 수집 현황",
            fg=MUTED, bg=BG, font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=16, pady=(12, 4))

        # ── Treeview 테이블 ──
        table_frame = tk.Frame(self, bg=BG)
        table_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Custom.Treeview",
            background=CARD_BG,
            foreground=FG,
            fieldbackground=CARD_BG,
            rowheight=30,
            font=("Segoe UI", 10),
            borderwidth=0,
        )
        style.configure("Custom.Treeview.Heading",
            background="#13151f",
            foreground=MUTED,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
        )
        style.map("Custom.Treeview",
            background=[("selected", "#1e2235")],
            foreground=[("selected", FG)],
        )

        cols = ("label", "alias", "location", "power", "energy", "status", "updated")
        self.tree = ttk.Treeview(
            table_frame, columns=cols, show="headings",
            style="Custom.Treeview", selectmode="browse"
        )
        headers = {
            "label":    ("기기명",       100),
            "alias":    ("기기 설명",    150),
            "location": ("위치",         140),
            "power":    ("전력 (W)",      100),
            "energy":   ("에너지 (Wh)",   130),
            "status":   ("상태",           70),
            "updated":  ("마지막 수집",   155),
        }
        for col, (head, width) in headers.items():
            self.tree.heading(col, text=head)
            anchor = "center" if col in ("power", "energy", "status") else "w"
            self.tree.column(col, width=width, anchor=anchor)

        self.tree.tag_configure("success", foreground=GREEN)
        self.tree.tag_configure("fail",    foreground=RED)

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_device_click)

        # ── 하단 상태바 ──
        statusbar = tk.Frame(self, bg="#13151f", pady=5)
        statusbar.pack(fill="x", side="bottom")
        tk.Label(
            statusbar, text="수집 완료 시 자동 갱신 (60초 간격)",
            fg=MUTED, bg="#13151f", font=("Segoe UI", 9)
        ).pack(side="left", padx=12)
        self.lbl_refreshed = tk.Label(
            statusbar, text="-", fg=MUTED, bg="#13151f", font=("Segoe UI", 9)
        )
        self.lbl_refreshed.pack(side="right", padx=12)

    def _make_card(self, parent, label_text, value_text, color):
        CARD_BG = "#1a1d27"
        BORDER  = "#2d3148"
        MUTED   = "#64748b"

        frame = tk.Frame(
            parent, bg=CARD_BG, bd=1, relief="flat",
            highlightbackground=BORDER, highlightthickness=1
        )
        frame.pack(side="left", expand=True, fill="both", padx=6)

        tk.Label(
            frame, text=label_text, fg=MUTED, bg=CARD_BG,
            font=("Segoe UI", 9), pady=8
        ).pack()
        lbl = tk.Label(
            frame, text=value_text, fg=color, bg=CARD_BG,
            font=("Segoe UI", 24, "bold"), pady=4
        )
        lbl.pack(pady=(0, 10))
        return lbl

    # ──────────────────────────────
    # 데이터 갱신 (3초마다)
    # ──────────────────────────────
    # ──────────────────────────────
    # 그래프 창
    # ──────────────────────────────
    def _on_device_click(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        if not values:
            return
        display = values[0]  # 예: "지인 모니터 (SMP18)" 또는 "SMP07"
        # 괄호 안의 원본 label 추출
        if "(" in display and display.endswith(")"):
            label = display[display.rfind("(")+1:-1]
        else:
            label = display
        self._open_graph_window(label)

    def _find_csv_files(self, label):
        """해당 label의 CSV 파일 목록을 날짜순으로 반환."""
        base = "C:/smartthings_data/csv_data"
        pattern = os.path.join(base, "**", f"{label}_*.csv")
        files = sorted(glob.glob(pattern, recursive=True))
        return files

    def _load_csv_data(self, label, days=1):
        """최근 N일치 CSV에서 timestamp, power, energy를 읽어 반환."""
        files = self._find_csv_files(label)
        if not files:
            return [], [], []

        # 최근 N일 파일만 사용
        files = files[-days:]

        timestamps, powers, energies = [], [], []
        for fpath in files:
            try:
                with open(fpath, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        try:
                            ts  = datetime.strptime(row["Timestamp"], "%Y-%m-%d %H:%M:%S")
                            pw  = float(row["Power (W)"])
                            en  = float(row["Energy (Wh)"])
                            timestamps.append(ts)
                            powers.append(pw)
                            energies.append(en)
                        except (ValueError, KeyError):
                            continue
            except Exception:
                continue
        return timestamps, powers, energies

    def _open_graph_window(self, label):
        """기기 그래프 창을 엽니다."""
        win = tk.Toplevel(self)
        win.title(f"{device_display_name(label)} - 전력 사용량")
        win.geometry("900x600")
        win.configure(bg="#0f1117")

        BG      = "#0f1117"
        CARD_BG = "#1a1d27"
        BORDER  = "#2d3148"
        FG      = "#e2e8f0"
        MUTED   = "#64748b"

        # ── 상단: 기간 선택 ──
        top = tk.Frame(win, bg=CARD_BG, pady=10)
        top.pack(fill="x")
        tk.Label(top, text=f"  {device_display_name(label)}  전력 사용량", fg=FG, bg=CARD_BG,
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=8)

        days_var = tk.IntVar(value=1)
        btn_frame = tk.Frame(top, bg=CARD_BG)
        btn_frame.pack(side="right", padx=12)

        def make_btn(text, days):
            b = tk.Button(
                btn_frame, text=text, bg="#2d3148", fg=FG,
                activebackground="#3d4168", activeforeground=FG,
                relief="flat", padx=10, pady=4, font=("Segoe UI", 9),
                cursor="hand2",
                command=lambda d=days: [days_var.set(d), draw()]
            )
            b.pack(side="left", padx=3)
            return b

        make_btn("오늘", 1)
        make_btn("3일", 3)
        make_btn("7일", 7)

        # ── 그래프 영역 ──
        fig = Figure(figsize=(9, 5), facecolor=BG)
        ax  = fig.add_subplot(111)
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

        self._style_axes(ax, BG, CARD_BG, MUTED)

        no_data_label = tk.Label(
            win, text="", fg="#ef4444", bg=BG, font=("Segoe UI", 11)
        )
        no_data_label.pack()

        def draw():
            days = days_var.get()
            timestamps, powers, energies = self._load_csv_data(label, days)

            ax.clear()
            self._style_axes(ax, BG, CARD_BG, MUTED)

            if not timestamps:
                no_data_label.config(text=f"'{label}' 의 CSV 데이터를 찾을 수 없습니다.")
                canvas.draw()
                return

            no_data_label.config(text="")
            ax.plot(timestamps, powers, color="#60a5fa", linewidth=1.5,
                    label="전력 (W)", zorder=3)
            ax.fill_between(timestamps, powers, alpha=0.15, color="#60a5fa")

            # x축 포맷
            if days == 1:
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
            else:
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
            fig.autofmt_xdate(rotation=30)

            ax.set_ylabel("전력 (W)", color=MUTED, fontsize=9)
            ax.set_title(
                f"{device_display_name(label)}  |  최근 {days}일  |  평균 {sum(powers)/len(powers):.2f} W  |  최대 {max(powers):.2f} W",
                color=FG, fontsize=10, pad=10
            )
            ax.legend(facecolor=CARD_BG, edgecolor=BORDER, labelcolor=FG, fontsize=9)
            fig.tight_layout()
            canvas.draw()

        draw()

    @staticmethod
    def _style_axes(ax, bg, card_bg, muted):
        ax.set_facecolor(card_bg)
        ax.tick_params(colors=muted, labelsize=8)
        ax.xaxis.label.set_color(muted)
        ax.yaxis.label.set_color(muted)
        for spine in ax.spines.values():
            spine.set_edgecolor("#2d3148")
        ax.grid(True, color="#2d3148", linewidth=0.5, linestyle="--")

    def _on_collected(self):
        """수집기 스레드에서 호출됨 → 메인 스레드로 안전하게 전달."""
        self.after(0, self._refresh)

    def _refresh(self):
        try:
            state = self.collector.dashboard_state

            self.lbl_total.config(text=str(state.get("total", 0)))
            self.lbl_success.config(text=str(state.get("success", 0)))
            self.lbl_fail.config(text=str(state.get("fail", 0)))
            self.lbl_status.config(text=state.get("status", "초기화 중"))

            status = state.get("status", "")
            self.dot.config(fg="#22c55e" if status == "수집 중" else "#fbbf24")

            expires = state.get("token_expires")
            self.lbl_token.config(
                text=f"토큰 만료: {expires}" if expires else "토큰 정보 없음"
            )

            # 테이블 갱신
            self.tree.delete(*self.tree.get_children())
            for d in state.get("devices", []):
                power  = f"{d['power']} W" if d["power"] != "-" else "-"
                try:
                    energy = f"{float(d['energy']):.1f} Wh" if d["energy"] != "-" else "-"
                except (ValueError, TypeError):
                    energy = "-"
                tag = "success" if d["status"] == "성공" else "fail"
                self.tree.insert("", "end", values=(
                    d["label"], get_alias(d["label"]), d["location"], power, energy, d["status"], d["updated"]
                ), tags=(tag,))

            self.lbl_refreshed.config(
                text=f"마지막 갱신: {datetime.now().strftime('%H:%M:%S')}"
            )
        except Exception as e:
            logging.error(f"UI 갱신 오류: {e}")

        # 폴링 없음 - 수집기 콜백에 의해서만 갱신됨


def run_dashboard(collector_module):
    """tkinter 대시보드를 실행합니다. 메인 스레드에서 호출해야 합니다."""
    app = Dashboard(collector_module)
    app.mainloop()
