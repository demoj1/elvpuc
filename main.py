import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
import requests, json, threading, queue, os, random, hashlib, colorsys
from datetime import datetime, timezone

class ElasticHeatmap:
    def __init__(self, parent, data=None, height=30, font_size=12):
        self.parent = parent
        self.data = data or []
        self.max_count = 1
        self.font_size = font_size
        self.text_widget = None

        # Создаем холст внутри переданного родителя
        self.canvas = tk.Canvas(parent, height=height, bg="#fdfdfd", highlightthickness=0)
        self.canvas.pack(fill="x", padx=0, pady=0)

        # Элементы тултипа (создаем один раз)
        self.tip_bg = self.canvas.create_rectangle(0, 0, 0, 0, fill="#333333", state="hidden")
        self.tip_text = self.canvas.create_text(0, 0, text="", fill="white", anchor="nw", state="hidden", font=("Consolas", self.font_size))
        self.scroll_marker = self.canvas.create_line(0, 0, 0, height, fill="#FF0000", width=3, state="hidden")

        # Биндинги
        self.canvas.bind("<Configure>", lambda e: self.render())
        self.canvas.bind("<Motion>", self._update_tooltip)
        self.canvas.bind("<Leave>", self._hide_tooltip)
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        if self.data:
            self.update_data(self.data)

    def set_text_widget(self, widget):
        self.text_widget = widget

    def set_scroll_pos(self, fraction):
        """Метод для перемещения маркера. fraction — число от 0.0 до 1.0"""
        if not self.data: return

        w = self.canvas.winfo_width()
        x = w * (1.0-fraction)

        self.canvas.coords(self.scroll_marker, x, 0, x, self.canvas.winfo_height())
        self.canvas.itemconfig(self.scroll_marker, state="normal")
        self.canvas.tag_raise(self.scroll_marker)

    def _utc_to_local(self, utc_str):
        try:
            utc_dt = datetime.fromisoformat(utc_str.replace('Z', '+00:00'))
            local_dt = utc_dt.astimezone()
            return local_dt.strftime('%H:%M:%S')
        except Exception:
            return utc_str

    def update_font_size(self, new_size):
        fname = "Iosevka" if "Iosevka" in tkfont.families() else "Monospace"
        self.font_size = new_size
        new_font = (fname, self.font_size, "normal")
        self.canvas.itemconfig(self.tip_text, font=new_font)

    def update_data(self, new_data):
        """Метод для внешнего обновления данных"""
        self.data = new_data
        self.max_count = max([b.get('doc_count', 0) for b in self.data]) if self.data else 1
        if self.max_count == 0: self.max_count = 1
        self.render()

    def _on_canvas_click(self, event):
        if not self.data or not self.text_widget:
            return

        w = self.canvas.winfo_width()
        fraction = event.x / w
        target_pos = (1.0 - fraction)

        self.text_widget.yview_moveto(target_pos)

    def _get_color(self, count):
        if count == 0: return "#ffffff" # Почти черный для пустоты

        ratio = count / self.max_count
        # Сдвигаем Hue: 0.7 (фиолетовый/синий) -> 0.15 (желтый)
        hue = 0.7 * (1 - ratio * 0.8)
        # Увеличиваем яркость (Value) для эффекта свечения
        value = 0.3 + (0.7 * ratio)

        rgb = colorsys.hsv_to_rgb(hue, 0.9, value)
        return '#%02x%02x%02x' % tuple(int(c * 255) for c in rgb)

    def render(self):
        self.canvas.delete("bar")
        if not self.data: return

        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        self.step = w / len(self.data)

        for i, item in enumerate(self.data):
            color = self._get_color(item.get('doc_count', 0))
            self.canvas.create_rectangle(
                i * self.step, 0, (i + 1) * self.step, h,
                fill=color, outline=color, width=1, tags="bar"
            )

        # Поднимаем тултип в топ стека отрисовки
        self.canvas.tag_raise(self.tip_bg)
        self.canvas.tag_raise(self.tip_text)

    def _update_tooltip(self, event):
        if not self.data or not hasattr(self, 'step'): return
        idx = int(event.x / self.step)
        if 0 <= idx < len(self.data):
            item = self.data[idx]
            local_time = self._utc_to_local(item.get('key_as_string', ''))
            msg = f" {local_time} | Logs: {item['doc_count']} "

            self.canvas.itemconfig(self.tip_text, text=msg, state="normal")
            x1, y1, x2, y2 = self.canvas.bbox(self.tip_text)
            tw, th = x2 - x1, y2 - y1

            fixed_y = (self.canvas.winfo_height() - th) // 2
            tx = event.x + 20 if event.x + 20 + tw < self.canvas.winfo_width() else event.x - 20 - tw
            self.canvas.coords(self.tip_text, tx, fixed_y)
            self.canvas.coords(self.tip_bg, tx-4, fixed_y-2, tx+tw+4, fixed_y+th+2)
            self.canvas.itemconfig(self.tip_bg, state="normal")
        else:
            self._hide_tooltip()

    def _hide_tooltip(self, event=None):
        self.canvas.itemconfig(self.tip_bg, state="hidden")
        self.canvas.itemconfig(self.tip_text, state="hidden")

class ElasticLogViewerUltra:
    def __init__(self, root):
        # --- Инициализация окна и переменных ---
        self.root = root
        self.root.title("Elastic Log Viewer Pro - Ultra Configurable")
        self.root.geometry("1450x900")

        self.config_file = os.path.expanduser("~/.config/elk_config")
        self.all_logs = []
        self.data_queue = queue.Queue()
        self.is_loading = False
        self.hist_agg = []
        self.log_font_size, self.ui_font_size = tk.IntVar(), tk.IntVar()
        self.status_var = tk.StringVar(value="Ready")
        self.highlighters = {}

        self.load_config()

        # --- UI SETUP: Верхняя панель управления ---
        top = ttk.Frame(root, padding=(0, 5)); top.pack(side=tk.TOP, fill=tk.X)

        # Ряд 1: URL, Индекс и настройки размеров шрифта
        r1 = ttk.Frame(top)
        r1.pack(side=tk.TOP, fill=tk.X)

        # --- ЛЕВАЯ ЧАСТЬ (URL и Индекс) ---
        # Создаем под-фрейм для левой части и пакуем его СЛЕВА
        left_parts = ttk.Frame(r1)
        left_parts.pack(side=tk.LEFT, fill=tk.X)

        # Твоя функция _add_f теперь работает внутри left_parts
        self.url_ent = self._add_f(left_parts, "URL:", self.conf.get('url', '<url>'), 50, 0)
        self.idx_ent = self._add_f(left_parts, "Index:", self.conf.get('index', '<index-pattern>'), 25, 2)

        # --- ПРАВАЯ ЧАСТЬ (Шрифты) ---
        # Создаем под-фрейм для правой части и пакуем его СПРАВА
        right_parts = ttk.Frame(r1)
        right_parts.pack(side=tk.RIGHT, padx=5)

        # Используем grid внутри правого фрейма для компактности шрифтов
        ttk.Label(right_parts, text="Log font size:").grid(row=0, column=0, padx=(10, 2))
        tk.Spinbox(right_parts, from_=8, to=40, textvariable=self.log_font_size, width=3, command=self.update_ui_font).grid(row=0, column=1)

        ttk.Label(right_parts, text="UI font size:").grid(row=0, column=2, padx=(10, 2))
        tk.Spinbox(right_parts, from_=8, to=25, textvariable=self.ui_font_size, width=3, command=self.update_ui_font).grid(row=0, column=3)

        # Ряд 2: Кнопка поиска, Лимит и Временные диапазоны
        r2 = ttk.Frame(top, padding=(0, 5, 0, 0)); r2.pack(side=tk.TOP, fill=tk.X)
        self.btn = ttk.Button(r2, text="Search", command=self.start_fetch, width=10)
        self.btn.pack(side=tk.LEFT, padx=(5, 15))

        self.lim_ent = ttk.Entry(r2, width=6); self.lim_ent.insert(0, self.conf.get('limit', '250'))
        ttk.Label(r2, text="Limit:").pack(side=tk.LEFT); self.lim_ent.pack(side=tk.LEFT, padx=2)

        ttk.Label(r2, text="Range:").pack(side=tk.LEFT, padx=(15, 2))
        self.t_from = ttk.Entry(r2, width=12); self.t_from.insert(0, self.conf.get('t_from', 'now-15m'))
        self.t_from.pack(side=tk.LEFT, padx=2)
        ttk.Label(r2, text="to").pack(side=tk.LEFT)
        self.t_to = ttk.Entry(r2, width=12); self.t_to.insert(0, self.conf.get('t_to', 'now'))
        self.t_to.pack(side=tk.LEFT, padx=2)

        # Кнопки пресетов времени
        for label, val in [("5m", "now-5m"), ("15m", "now-15m"), ("30m", "now-30m"), ("1h", "now-1h"), ("3h", "now-3h"), ("12h", "now-12h"), ("24h", "now-24h")]:
            ttk.Button(r2, text=label, width=4, command=lambda v=val: self._set_time(v)).pack(side=tk.LEFT, padx=1)

        # Кнопки массового раскрытия/сворачивания
        ttk.Button(r2, text="Expand all", command=lambda: self.bulk_expand(True)).pack(side=tk.RIGHT, padx=2)
        ttk.Button(r2, text="Collapse all", command=lambda: self.bulk_expand(False)).pack(side=tk.RIGHT, padx=2)

        # --- UI SETUP: HeatMap ---

        self.heat_canvas = ElasticHeatmap(root, height=35)

        # Ряд 3: Поле основного запроса Elastic
        r3 = ttk.Frame(top, padding=(0, 5, 0, 0)); r3.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(r3, text="Query:").pack(side=tk.LEFT)

        scrollbar = ttk.Scrollbar(r3)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.q_ent = tk.Text(r3, height=2, undo=True, maxundo=20, wrap=tk.WORD, yscrollcommand=scrollbar.set)
        self.q_ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        scrollbar.config(command=self.q_ent.yview)
        self.q_ent.insert("1.0", self.conf.get('query', '*'))
        self.q_ent.bind("<Control-Return>", lambda e: self.start_fetch() or "break")
        self.q_ent.bind("<Command-Return>", lambda e: self.start_fetch() or "break")

        # --- UI SETUP: Текстовая область с логами ---
        self.txt_f = ttk.Frame(root); self.txt_f.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.v_sc = ttk.Scrollbar(self.txt_f);
        self.v_sc.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt = tk.Text(self.txt_f, bg="white", fg="black", width=1, height=1, padx=0, pady=0, wrap=tk.CHAR, borderwidth=0, undo=False, yscrollcommand=self.sync_scroll)
        self.txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 0));
        self.v_sc.config(command=self.txt.yview)

        self.heat_canvas.set_text_widget(self.txt)

        # --- UI SETUP: Нижняя панель (Фильтр и Статус) ---
        bot = ttk.Frame(root, padding=5); bot.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bot, text="Offline filter:").pack(side=tk.LEFT)
        self.f_var = tk.StringVar(value=self.conf.get('offline_filter', ''))
        self.f_var.trace_add("write", lambda *a: self.render_logs())
        self.f_ent = ttk.Entry(bot, textvariable=self.f_var); self.f_ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        # self.info_lbl = ttk.Label(bot, text="[Ctrl+S] Search | [Ctrl+F] Filter | Space Highlight | C-Space Clear hl", foreground="gray")
        self.info_lbl = ttk.Label(bot, text="[Ctrl+S] Search | [Ctrl+F] Filter | [F5/Ctrl+R] Refresh", foreground="gray")
        self.info_lbl.pack(side=tk.RIGHT, padx=10)
        ttk.Label(bot, textvariable=self.status_var, foreground="blue", font=("TkDefaultFont", 9, "bold")).pack(side=tk.RIGHT, padx=5)

        # --- Привязка горячих клавиш ---
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_ui_font(); self.check_queue()
        self.txt.bind("<Button-1>", self.on_text_click)
        self.txt.bind("<space>", self.add_highlighter)
        self.txt.bind("<Control-space>", self.clear_highlighters)
        self.root.bind("<Control-f>", lambda e: self.f_ent.focus_set())
        self.root.bind("<Command-f>", lambda e: self.f_ent.focus_set())
        self.root.bind("<Control-s>", lambda e: [self.q_ent.focus_set(), "break"])
        self.root.bind("<Command-s>", lambda e: [self.q_ent.focus_set(), "break"])
        self.root.bind("<Control-r>", lambda e: self.start_fetch())
        self.root.bind("<Command-r>", lambda e: self.start_fetch())
        self.root.bind("<F5>", lambda e: self.start_fetch())

        mods = ["Control", "Command"]
        for cls in ("Entry", "TEntry", "Text"):
            for m in mods:
                for key in ("a", "A"):
                    root.bind_class(cls, f"<{m}-{key}>", lambda e: (
                        e.widget.select_range(0, 'end') if not isinstance(e.widget, tk.Text)
                        else e.widget.tag_add("sel", "1.0", "end"), "break"
                    ))

                for key in ("c", "C"):
                    root.bind_class(cls, f"<{m}-{key}>", lambda e: e.widget.event_generate("<<Copy>>"))

                for key in ("v","V"):
                    root.bind_class(cls, f"<{m}-{key}>", lambda e: e.widget.event_generate("<<Paste>>"))

                for key in ("x", "X"):
                    root.bind_class(cls, f"<{m}-{key}>", lambda e: e.widget.event_generate("<<Cut>>"))

    def sync_scroll(self, *args):
        self.v_sc.set(*args)

        pos = float(args[0])

        self.heat_canvas.set_scroll_pos(pos)

    # --- Вспомогательные методы построения интерфейса ---
    def _add_f(self, p, t, d, w, c):
        ttk.Label(p, text=t).grid(row=0, column=c, padx=(5, 2))
        e = ttk.Entry(p, width=w); e.insert(0, d); e.grid(row=0, column=c+1);
        return e

    def _set_time(self, v):
        self.t_from.delete(0, tk.END); self.t_from.insert(0, v)
        self.t_to.delete(0, tk.END); self.t_to.insert(0, "now"); self.start_fetch()

    # --- Работа с конфигурацией (Load/Save) ---
    def load_config(self):
        try:
            with open(self.config_file, 'r') as f: self.conf = json.load(f)
        except: self.conf = {}
        self.log_font_size.set(self.conf.get('log_sz', 13)); self.ui_font_size.set(self.conf.get('ui_sz', 10))
        self.highlighters = self.conf.get('highlighters', {})

    def on_close(self):
        try:
            if not os.path.exists(os.path.dirname(self.config_file)): os.makedirs(os.path.dirname(self.config_file))
            with open(self.config_file, 'w') as f:
                json.dump({"url": self.url_ent.get(), "index": self.idx_ent.get(), "limit": self.lim_ent.get(),
                           "query": self.q_ent.get("1.0", "end-1c").strip(), "t_from": self.t_from.get(), "t_to": self.t_to.get(),
                           "offline_filter": self.f_var.get(), "log_sz": self.log_font_size.get(),
                           "ui_sz": self.ui_font_size.get(), "highlighters": self.highlighters}, f, indent=4)
        except: pass
        self.root.destroy()

    # --- Управление шрифтами и стилями ---
    def update_ui_font(self):
        sz, u_sz = self.log_font_size.get(), self.ui_font_size.get()
        fname = "Iosevka" if "Iosevka" in tkfont.families() else "Monospace"
        ui_f = tkfont.Font(family="TkDefaultFont", size=u_sz)
        self.txt.config(font=(fname, sz))
        self.heat_canvas.update_font_size(u_sz)
        self.txt.tag_configure("header", background="#f2f2f2", font=(fname, sz, "bold"), spacing1=10, spacing3=5)
        self.txt.tag_configure("msg", font=(fname, sz), lmargin1=20, lmargin2=20)
        ttk.Style().configure(".", font=ui_f)
        self._apply_f_rec(self.root, ui_f)
        self.render_logs()

    def _apply_f_rec(self, w, f):
        try: w.configure(font=f)
        except: pass
        for c in w.winfo_children(): self._apply_f_rec(c, f)

    # --- Атомарная подсветка (Highlighters) ---
    def apply_highlighters(self):
        # Удаляем только hi_ теги перед перекраской
        for tag in list(self.txt.tag_names()):
            if tag.startswith("hi_"): self.txt.tag_delete(tag)
        for text, color in self.highlighters.items():
            if not text: continue
            # Хеширование имени тега для стабильности (emoji/спецсимволы)
            t_name = f"hi_{hashlib.md5(text.encode('utf-8')).hexdigest()[:10]}"
            self.txt.tag_configure(t_name, background=color)
            start = "1.0"
            while True:
                # regexp=False — защита от SegFault на символах типа []()
                start = self.txt.search(text, start, tk.END, nocase=True, regexp=False)
                if not start: break
                end = f"{start}+{len(text)}c"; self.txt.tag_add(t_name, start, end); start = end

    # --- Отрисовка логов (Render Engine) ---
    def render_logs(self):
        try: pos = self.txt.yview()[0]
        except: pos = 0.0
        self.txt.config(state='normal')
        # Очистка всех тегов перед удалением контента
        for tag in list(self.txt.tag_names()):
            if tag.startswith("hi_") or tag.startswith("h_"): self.txt.tag_delete(tag)
            self.txt.delete("1.0", tk.END)

        q = self.f_var.get().lower().split(); count = 0
        for i, log in enumerate(self.all_logs):
            full = (log['time'] + " " + log['msg']).lower()
            # Логика офлайн фильтра (+ и -)
            if not all((p[1:] in full if p.startswith('+') else p[1:] not in full if p.startswith('-') else p in full) for p in q): continue
            count += 1
            # Вставка заголовка с уникальным тегом h_{i}
            self.txt.insert(tk.END, f" {'⮿' if log['expanded'] else '⎊'} {log['time']} \n", ("header", f"h_{i}"))
            disp = log['msg'] if log['expanded'] else "\n".join(log['msg'].splitlines()[:3]) + "\n... [COLLAPSED] ...\n"
            self.txt.insert(tk.END, "\n" + disp + "\n\n", "msg")

        self.apply_highlighters()
        self.heat_canvas.update_data(self.hist_agg)
        self.txt.config(state='disabled'); self.status_var.set(f"Showing: {count}/{len(self.all_logs)}")
        self.txt.yview_moveto(pos)

    # --- Обработчики пользовательских действий ---
    def add_highlighter(self, event):
        try:
            text = self.txt.get("sel.first", "sel.last").strip()
            if text and text not in self.highlighters:
                color = "#%02x%02x%02x" % (random.randint(200,255), random.randint(200,255), random.randint(150,255))
                self.highlighters[text] = color
                self.apply_highlighters()
        except: pass
        return "break"

    def clear_highlighters(self, event):
        self.highlighters = {}; self.apply_highlighters(); return "break"

    def bulk_expand(self, state):
        for log in self.all_logs: log['expanded'] = state
        self.render_logs()

    # --- Работа с сетью (Elastic API) ---
    def start_fetch(self):
        if self.is_loading: return
        self.is_loading, self.btn['state'] = True, 'disabled'; self.status_var.set("Fetching...")
        url = self.url_ent.get().strip().rstrip('/')
        p = {"url": f"{url}/{self.idx_ent.get()}/_search", "lim": self.lim_ent.get(), "q": self.q_ent.get("1.0", "end-1c").strip(), "f": self.t_from.get(), "t": self.t_to.get()}
        threading.Thread(target=self.worker, args=(p,), daemon=True).start()

    def worker(self, p):
        try:
            r = requests.post(
                p["url"],
                json={
                  "size": int(p["lim"]),
                  "sort": [{"@timestamp": "desc"}],
                  "query": {
                    "bool": {
                      "must": [{"query_string": {"query": p["q"]}}],
                      "filter": [{"range": {"@timestamp": {"gte": p["f"], "lte": p["t"]}}}]
                    }
                  },
                  "aggs": {
                    "agg": {
                      "auto_date_histogram": {
                        "field": "@timestamp",
                        "buckets": "150",
                      }
                    }
                  }
                },
                timeout=15
            ).json()

            hits = [{
                "t": h['_source'].get('@timestamp', '---'),
                "m": h['_source'].get('message', json.dumps(h['_source'], indent=2))
            } for h in r.get('hits', {}).get('hits', [])]

            self.data_queue.put(("OK", hits))
            self.hist_agg = r.get('aggregations', {}).get('agg', {}).get('buckets', [])
        except Exception as e:
            self.data_queue.put(("ERR", str(e)))

    def check_queue(self):
        try:
            while True:
                s, p = self.data_queue.get_nowait()
                self.is_loading, self.btn['state'] = False, 'normal'
                if s == "OK":
                    self.all_logs = [{"time": x['t'], "msg": x['m'], "expanded": True} for x in p]
                    self.render_logs()
                else:
                    messagebox.showerror("Error", p)
                    self.status_var.set("Error")
        except queue.Empty: pass
        self.root.after(100, self.check_queue)

    def on_text_click(self, event):
        # Определение тега h_ под кликом для Expand/Collapse
        for t in self.txt.tag_names(self.txt.index(f"@{event.x},{event.y}")):
            if t.startswith("h_"):
                idx = int(t.split("_")[1])
                self.all_logs[idx]['expanded'] = not self.all_logs[idx]['expanded']; self.render_logs(); return "break"

if __name__ == "__main__":
    app = ElasticLogViewerUltra(tk.Tk()); app.root.mainloop()
