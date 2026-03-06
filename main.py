import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
import requests, json, threading, queue, os, random, hashlib

class ElasticLogViewerUltra:
    def __init__(self, root):
        # --- Инициализация окна и переменных ---
        self.root = root
        self.root.title("Elastic Log Viewer Pro - Ultra Configurable")
        self.root.geometry("1450x900")

        self.config_file = os.path.expanduser("~/.config/elk_config")
        self.all_logs, self.data_queue, self.is_loading = [], queue.Queue(), False
        self.log_font_size, self.ui_font_size = tk.IntVar(), tk.IntVar()
        self.status_var = tk.StringVar(value="Ready")
        self.highlighters = {}

        self.load_config()

        # --- UI SETUP: Верхняя панель управления ---
        top = ttk.Frame(root, padding=5); top.pack(side=tk.TOP, fill=tk.X)

        # Ряд 1: URL, Индекс и настройки размеров шрифта
        r1 = ttk.Frame(top); r1.pack(side=tk.TOP, fill=tk.X)
        self.url_ent = self._add_f(r1, "ELK URL:", self.conf.get('url', 'ELK base url'), 45, 0)
        self.idx_ent = self._add_f(r1, "Index:", self.conf.get('index', 'Index pattern'), 20, 2)

        ttk.Label(r1, text="Log Sz:").grid(row=0, column=4, padx=(10, 2))
        tk.Spinbox(r1, from_=8, to=40, textvariable=self.log_font_size, width=3, command=self.update_ui_font).grid(row=0, column=5)
        ttk.Label(r1, text="UI Sz:").grid(row=0, column=6, padx=(10, 2))
        tk.Spinbox(r1, from_=8, to=25, textvariable=self.ui_font_size, width=3, command=self.update_ui_font).grid(row=0, column=7)

        # Ряд 2: Кнопка поиска, Лимит и Временные диапазоны
        r2 = ttk.Frame(top, padding=(0, 5, 0, 0)); r2.pack(side=tk.TOP, fill=tk.X)
        self.btn = ttk.Button(r2, text="SEARCH", command=self.start_fetch, width=10)
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
        ttk.Button(r2, text="EXPAND ALL", command=lambda: self.bulk_expand(True)).pack(side=tk.RIGHT, padx=2)
        ttk.Button(r2, text="COLLAPSE ALL", command=lambda: self.bulk_expand(False)).pack(side=tk.RIGHT, padx=2)

        # Ряд 3: Поле основного запроса Elastic
        r3 = ttk.Frame(top, padding=(0, 5, 0, 0)); r3.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(r3, text="Query:").pack(side=tk.LEFT)
        self.q_ent = ttk.Entry(r3); self.q_ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        self.q_ent.insert(0, self.conf.get('query', '*'))
        self.q_ent.bind("<Return>", lambda e: self.start_fetch())

        # --- UI SETUP: Текстовая область с логами ---
        self.txt_f = ttk.Frame(root); self.txt_f.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        v_sc = ttk.Scrollbar(self.txt_f); v_sc.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt = tk.Text(self.txt_f, bg="white", padx=15, pady=10, wrap=tk.WORD, borderwidth=0, undo=False, yscrollcommand=v_sc.set)
        self.txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); v_sc.config(command=self.txt.yview)

        # --- UI SETUP: Нижняя панель (Фильтр и Статус) ---
        bot = ttk.Frame(root, padding=5); bot.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bot, text="Offline filter:").pack(side=tk.LEFT)
        self.f_var = tk.StringVar(value=self.conf.get('offline_filter', ''))
        self.f_var.trace_add("write", lambda *a: self.render_logs())
        self.f_ent = ttk.Entry(bot, textvariable=self.f_var); self.f_ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.info_lbl = ttk.Label(bot, text="[Ctrl+S] Search | [Ctrl+F] Filter | Space Highlight | C-Space Clear hl", foreground="gray")
        self.info_lbl.pack(side=tk.RIGHT, padx=10)
        ttk.Label(bot, textvariable=self.status_var, foreground="blue", font=("TkDefaultFont", 9, "bold")).pack(side=tk.RIGHT, padx=5)

        # --- Привязка горячих клавиш ---
        self.update_ui_font(); self.check_queue()
        self.txt.bind("<Button-1>", self.on_text_click)
        self.txt.bind("<space>", self.add_highlighter)
        self.txt.bind("<Control-space>", self.clear_highlighters)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<Control-f>", lambda e: self.f_ent.focus_set())
        self.root.bind("<Control-s>", lambda e: [self.q_ent.focus_set(), "break"])

    # --- Вспомогательные методы построения интерфейса ---
    def _add_f(self, p, t, d, w, c):
        ttk.Label(p, text=t).grid(row=0, column=c, padx=(5, 2))
        e = ttk.Entry(p, width=w); e.insert(0, d); e.grid(row=0, column=c+1); e.bind("<Return>", lambda x: self.start_fetch())
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
                           "query": self.q_ent.get(), "t_from": self.t_from.get(), "t_to": self.t_to.get(),
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
            self.txt.insert(tk.END, f" {'[-] ' if log['expanded'] else '[+] '} {log['time']} \n", ("header", f"h_{i}"))
            disp = log['msg'] if log['expanded'] else "\n".join(log['msg'].splitlines()[:3]) + "\n... [COLLAPSED] ...\n"
            self.txt.insert(tk.END, disp + "\n" + " —" * 40 + "\n", "msg")

        self.apply_highlighters()
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
        p = {"url": f"{url}/{self.idx_ent.get()}/_search", "lim": self.lim_ent.get(), "q": self.q_ent.get(), "f": self.t_from.get(), "t": self.t_to.get()}
        threading.Thread(target=self.worker, args=(p,), daemon=True).start()

    def worker(self, p):
        try:
            body = {"size": int(p["lim"]), "sort": [{"@timestamp": "desc"}],
                    "query": {"bool": {"must": [{"query_string": {"query": p["q"]}}],
                    "filter": [{"range": {"@timestamp": {"gte": p["f"], "lte": p["t"]}}}]}}}
            r = requests.post(p["url"], json=body, timeout=10).json()
            hits = [{"t": h['_source'].get('@timestamp', '---'), "m": h['_source'].get('message', json.dumps(h['_source'], indent=2))} for h in r.get('hits', {}).get('hits', [])]
            self.data_queue.put(("OK", hits))
        except Exception as e: self.data_queue.put(("ERR", str(e)))

    def check_queue(self):
        try:
            while True:
                s, p = self.data_queue.get_nowait()
                self.is_loading, self.btn['state'] = False, 'normal'
                if s == "OK":
                    self.all_logs = [{"time": x['t'], "msg": x['m'], "expanded": True} for x in p]
                    self.render_logs()
                else: messagebox.showerror("Error", p)
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
