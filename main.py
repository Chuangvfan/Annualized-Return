import customtkinter as ctk
from tkinter import messagebox, ttk, filedialog
from datetime import date, datetime, timedelta, timezone
from scipy import optimize
from tkcalendar import DateEntry
import json
import os
import shutil
import uuid
import pandas as pd  # 引入pandas处理日期的加减（月度/周度）

# 尝试导入金融日历库
try:
    import pandas_market_calendars as mcal

    HAS_MCAL = True
except ImportError:
    HAS_MCAL = False
    print("提示: 未检测到 pandas_market_calendars，将无法自动剔除节假日。")

# 设置外观
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

DATA_FILE = "my_fund_data.json"


class GroupedFundApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("基金年化记账本 (增强版：多周期定投+自动顺延)")
        self.geometry("1100x900")

        # 数据变量
        self.records = []
        self.drip_records = []
        self.drip_plans = []
        self.initial_capital = 0.0
        self.start_date_obj = None
        self.is_initialized = False

        # --- 1. 初始化多市场日历 ---
        self.calendars = {}
        if HAS_MCAL:
            try:
                print("正在初始化交易日历，请稍候...")
                self.calendars['CN'] = mcal.get_calendar('XSHG')  # A股
                self.calendars['US'] = mcal.get_calendar('NYSE')  # 美股
                print("日历加载完成。")
            except Exception as e:
                print(f"日历初始化部分失败: {e}")

        # 获取北京时间
        utc_now = datetime.now(timezone.utc)
        beijing_now = utc_now.astimezone(timezone(timedelta(hours=8)))
        self.today_bj = beijing_now.date()

        # ============ UI 布局 ============
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # --- 顶部：初始本金 ---
        self.frame_init = ctk.CTkFrame(self, fg_color=("#E0E0E0", "#2B2B2B"))
        self.frame_init.grid(row=0, column=0, padx=20, pady=10, sticky="ew")

        ctk.CTkLabel(self.frame_init, text="第一步：设置初始投入", font=("微软雅黑", 14, "bold")).grid(row=0, column=0,
                                                                                                      padx=10, pady=5)

        self.entry_start_date = DateEntry(self.frame_init, width=12, background='#3B8ED0',
                                          foreground='white', borderwidth=2,
                                          date_pattern='yyyy-mm-dd', font=("Arial", 12))
        self.entry_start_date.grid(row=1, column=1, padx=5, pady=10)
        self.entry_start_date.set_date(date(self.today_bj.year, 1, 1))

        self.entry_init_money = ctk.CTkEntry(self.frame_init, placeholder_text="年初本金")
        self.entry_init_money.grid(row=1, column=2, padx=10, pady=10)

        self.btn_init = ctk.CTkButton(self.frame_init, text="锁定初始值", command=self.lock_initial)
        self.btn_init.grid(row=1, column=3, padx=10, pady=10)

        # --- 中部：操作区域 ---
        self.frame_ops = ctk.CTkFrame(self)
        self.frame_ops.grid(row=1, column=0, padx=20, pady=10, sticky="ew")

        ctk.CTkLabel(self.frame_ops, text="第二步：记录买卖", font=("微软雅黑", 14, "bold")).grid(row=0, column=0,
                                                                                                 padx=10, pady=5)

        self.entry_op_date = DateEntry(self.frame_ops, width=12, background='#3B8ED0',
                                       foreground='white', borderwidth=2,
                                       date_pattern='yyyy-mm-dd', font=("Arial", 12))
        self.entry_op_date.grid(row=1, column=1, padx=5, pady=5)
        self.entry_op_date.set_date(self.today_bj)

        self.entry_op_amount = ctk.CTkEntry(self.frame_ops, placeholder_text="金额", width=100)
        self.entry_op_amount.grid(row=1, column=2, padx=5, pady=5)

        self.entry_op_remark = ctk.CTkEntry(self.frame_ops, placeholder_text="备注 (选填)", width=150)
        self.entry_op_remark.grid(row=1, column=3, padx=5, pady=5)

        self.btn_buy = ctk.CTkButton(self.frame_ops, text="买入 (投钱)", fg_color="#27AE60", hover_color="#1E8449",
                                     width=80, command=lambda: self.add_record("buy"))
        self.btn_buy.grid(row=1, column=4, padx=5)

        self.btn_sell = ctk.CTkButton(self.frame_ops, text="卖出 (拿钱)", fg_color="#C0392B", hover_color="#922B21",
                                      width=80, command=lambda: self.add_record("sell"))
        self.btn_sell.grid(row=1, column=5, padx=5)

        self.btn_del = ctk.CTkButton(self.frame_ops, text="删除选中", fg_color="gray", width=80,
                                     command=self.delete_selected)
        self.btn_del.grid(row=1, column=6, padx=5)

        self.btn_drip = ctk.CTkButton(self.frame_ops, text="定投管理", fg_color="#8E44AD", hover_color="#7D3C98",
                                      width=80, command=self.open_drip_setup)
        self.btn_drip.grid(row=1, column=7, padx=5)

        # --- 列表展示 ---
        self.tree_frame = ctk.CTkFrame(self)
        self.tree_frame.grid(row=3, column=0, padx=20, pady=5, sticky="nsew")

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", rowheight=28,
                        font=("Arial", 11), borderwidth=0)
        style.configure("Treeview.Heading", background="#3a3a3a", foreground="white", font=("微软雅黑", 11, "bold"),
                        borderwidth=1)
        style.map("Treeview", background=[('selected', '#1f538d')], foreground=[('selected', 'white')])

        columns = ("type", "amount", "remark")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, selectmode="browse")

        self.tree.heading("#0", text="日期 / 月份分组")
        self.tree.heading("type", text="操作类型")
        self.tree.heading("amount", text="金额 (流向)")
        self.tree.heading("remark", text="备注")

        self.tree.column("#0", width=220, anchor="w")
        self.tree.column("type", width=100, anchor="center")
        self.tree.column("amount", width=120, anchor="center")
        self.tree.column("remark", width=200, anchor="w")

        self.scrollbar = ctk.CTkScrollbar(self.tree_frame, orientation="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        # --- 底部：期末计算 ---
        self.frame_calc = ctk.CTkFrame(self, border_width=2, border_color="#3498DB")
        self.frame_calc.grid(row=4, column=0, padx=20, pady=20, sticky="ew")

        header_f = ctk.CTkFrame(self.frame_calc, fg_color="transparent")
        header_f.grid(row=0, column=0, columnspan=5, sticky="ew", padx=10, pady=5)

        ctk.CTkLabel(header_f, text="第三步：期末结算", font=("微软雅黑", 14, "bold")).pack(side="left")

        stats_frame = ctk.CTkFrame(header_f, fg_color="transparent")
        stats_frame.pack(side="right")

        self.lbl_total_principal = ctk.CTkLabel(stats_frame, text="累计投入: 0.00", font=("Arial", 12),
                                                text_color="gray")
        self.lbl_total_principal.pack(side="left", padx=10)

        self.lbl_current_cash = ctk.CTkLabel(stats_frame, text="剩余现金: 0.00", font=("Arial", 13, "bold"),
                                             text_color="#F39C12")
        self.lbl_current_cash.pack(side="left", padx=10)

        self.entry_end_date = DateEntry(self.frame_calc, width=12, background='#3B8ED0',
                                        foreground='white', borderwidth=2,
                                        date_pattern='yyyy-mm-dd', font=("Arial", 12))
        self.entry_end_date.grid(row=1, column=1, padx=5)
        self.entry_end_date.set_date(self.today_bj)

        self.entry_end_val = ctk.CTkEntry(self.frame_calc, placeholder_text="当前总市值 (必填)")
        self.entry_end_val.grid(row=1, column=2, padx=10)

        self.btn_run = ctk.CTkButton(self.frame_calc, text="计算年化", height=40, font=("bold", 14),
                                     command=self.calculate_xirr)
        self.btn_run.grid(row=1, column=3, padx=10)

        self.result_label = ctk.CTkLabel(self.frame_calc, text="准备就绪", font=("微软雅黑", 16))
        self.result_label.grid(row=2, column=0, columnspan=5, pady=10)

        # --- 数据管理 ---
        self.frame_data = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_data.grid(row=5, column=0, padx=20, pady=10, sticky="ew")

        self.btn_export = ctk.CTkButton(self.frame_data, text="📤 导出备份", fg_color="#5D6D7E", hover_color="#34495E",
                                        command=self.export_backup)
        self.btn_export.pack(side="left", padx=10)
        self.btn_import = ctk.CTkButton(self.frame_data, text="📥 导入数据", fg_color="#5D6D7E", hover_color="#34495E",
                                        command=self.import_backup)
        self.btn_import.pack(side="right", padx=10)

        # 启动逻辑
        self.load_data_from_file(DATA_FILE)
        self.generate_daily_drip_records()
        self.update_summary_labels()

    # ================= 渲染与统计 =================

    def render_tree_view(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        all_items = []
        if self.is_initialized:
            all_items.append({
                "date": self.start_date_obj,
                "type": "【初始本金】",
                "amount": -self.initial_capital,
                "remark": "---",
                "is_init": True
            })

        for r in self.records:
            all_items.append({
                "date": r[0],
                "type": "买入/追加" if r[1] < 0 else "卖出/取现",
                "amount": r[1],
                "remark": r[2],
                "is_init": False
            })

        for d in self.drip_records:
            all_items.append({
                "date": d[0],
                "type": "【定投】",
                "amount": d[1],
                "remark": d[2],
                "is_init": False
            })

        all_items.sort(key=lambda x: x["date"])

        current_month_key = None
        month_items = []

        def insert_month_group(month_key, items):
            if not month_key: return
            month_sum = sum(item["amount"] for item in items)
            sum_text = f"月度净流: {month_sum:+.2f}"
            p_id = self.tree.insert("", "end", text=f"📅 {month_key} ({sum_text})", open=True, tags=('group',))
            for item in items:
                display_date = item["date"].strftime("%Y-%m-%d")
                val_tuple = (item["type"], f"{item['amount']}", item["remark"])
                self.tree.insert(p_id, "end", text=display_date, values=val_tuple)

        for item in all_items:
            month_key = item["date"].strftime("%Y年%m月")
            if month_key != current_month_key:
                insert_month_group(current_month_key, month_items)
                current_month_key = month_key
                month_items = []
            month_items.append(item)

        insert_month_group(current_month_key, month_items)
        self.update_summary_labels()

    def update_summary_labels(self):
        total_invested = 0.0
        if self.is_initialized:
            total_invested += self.initial_capital

        current_cash = 0.0
        if self.is_initialized:
            current_cash += self.initial_capital

        for r in self.records:
            if r[1] < 0: total_invested += abs(r[1])
            current_cash += r[1]

        for d in self.drip_records:
            if d[1] < 0: total_invested += abs(d[1])
            current_cash += d[1]

        self.lbl_total_principal.configure(text=f"累计投入: {total_invested:,.2f}")
        self.lbl_current_cash.configure(text=f"剩余现金: {current_cash:,.2f}")

    # ================= 业务逻辑：增强版自动定投 =================

    def generate_daily_drip_records(self):
        """
        核心逻辑重写：
        1. 支持 日/周/月 频率。
        2. 计算名义日期，如果名义日期非交易日，则顺延至下一个交易日。
        3. 顺延不影响下一次名义日期的计算（例如：周五顺延到下周一，下一次定投依然是下周五）。
        """
        if not self.drip_plans: return
        active_plans = [p for p in self.drip_plans if p.get('active', True)]
        if not active_plans: return

        earliest_start = min(p['start_date_obj'] for p in active_plans)
        if earliest_start > self.today_bj: return

        # --- 批量获取日历 (缓存) ---
        # 我们多取一点时间，防止顺延到未来
        search_end_date = self.today_bj + timedelta(days=15)

        trading_days_map = {}
        sorted_trading_days_list = {}  # 用于快速查找"下一个交易日"

        for market_code in ['CN', 'US']:
            trading_days_map[market_code] = set()
            sorted_trading_days_list[market_code] = []
            if market_code in self.calendars:
                try:
                    schedule = self.calendars[market_code].schedule(start_date=earliest_start, end_date=search_end_date)
                    # 转换为 Python date 对象
                    dates = [ts.date() for ts in schedule.index]
                    trading_days_map[market_code] = set(dates)
                    sorted_trading_days_list[market_code] = sorted(dates)
                except Exception as e:
                    print(f"获取 {market_code} 日历失败: {e}")

        # --- 现有记录哈希，防止重复 ---
        existing_hashes = set()
        for r in self.drip_records:
            existing_hashes.add((r[0], round(r[1], 2), r[2]))

        new_cnt = 0

        for plan in active_plans:
            market = plan.get('market', 'CN')
            frequency = plan.get('frequency', 'daily')  # daily, weekly, monthly
            ignored_dates = set(plan.get('ignored_dates', []))

            # 名义上的计划执行日期
            nominal_date = plan['start_date_obj']
            target_val = -plan['amount']
            remark_text = f"计划:{plan['name']}"

            # 辅助函数：查找 target_date 或之后的第一个交易日
            def find_execution_date(target_date, mkt):
                # 降级模式：如果没有日历，就当天
                if not HAS_MCAL or mkt not in sorted_trading_days_list:
                    return target_date

                days_list = sorted_trading_days_list[mkt]
                for d in days_list:
                    if d >= target_date:
                        return d
                return target_date  # 如果超出了日历范围（极少见），就返回当天

            # 循环直到 名义日期 超过今天
            # 注意：这里判断的是 nominal_date，因为如果是月定投，名义日期没到下个月就不该投
            # 但是执行日期(execution_date)必须 <= today_bj 才能入账

            while nominal_date <= self.today_bj:

                # 1. 计算顺延后的实际交易日
                execution_date = find_execution_date(nominal_date, market)

                # 2. 如果顺延后的日期还没到今天，或者刚好是今天，则尝试记录
                #    如果顺延到了明天，那今天就还不能记
                if execution_date <= self.today_bj:

                    # 检查是否被用户忽略 (检查的是名义日期，因为用户通常是想忽略这一期)
                    # 或者是 实际执行日期
                    nominal_str = nominal_date.strftime("%Y-%m-%d")
                    exec_str = execution_date.strftime("%Y-%m-%d")

                    if nominal_str not in ignored_dates and exec_str not in ignored_dates:
                        record_key = (execution_date, round(target_val, 2), remark_text)

                        if record_key not in existing_hashes:
                            self.drip_records.append((execution_date, target_val, remark_text))
                            existing_hashes.add(record_key)
                            new_cnt += 1

                # 3. 计算下一个【名义】日期 (保持节奏，不受顺延影响)
                if frequency == 'daily':
                    nominal_date += timedelta(days=1)
                elif frequency == 'weekly':
                    nominal_date += timedelta(weeks=1)
                elif frequency == 'monthly':
                    # 使用 pandas DateOffset 处理月度增加 (自动处理大小月)
                    next_ts = pd.Timestamp(nominal_date) + pd.DateOffset(months=1)
                    nominal_date = next_ts.date()
                else:
                    nominal_date += timedelta(days=1)  # 默认日

        if new_cnt > 0:
            self.drip_records.sort(key=lambda x: x[0])
            self.save_data()
            self.render_tree_view()
            messagebox.showinfo("定投助手", f"已自动补录 {new_cnt} 条记录 (包含顺延处理)")

    def save_data(self):
        data = {
            "initialized": self.is_initialized,
            "initial_capital": self.initial_capital,
            "start_date": self.start_date_obj.strftime("%Y-%m-%d") if self.start_date_obj else None,
            "records": [{"date": r[0].strftime("%Y-%m-%d"), "amount": r[1], "remark": r[2]} for r in self.records],
            "drip_records": [{"date": d[0].strftime("%Y-%m-%d"), "amount": d[1], "remark": d[2]} for d in
                             self.drip_records],
            "drip_plans": []
        }
        for p in self.drip_plans:
            data["drip_plans"].append({
                "id": p.get("id", str(uuid.uuid4())),
                "name": p.get("name"),
                "market": p.get("market", "CN"),
                "frequency": p.get("frequency", "daily"),  # 保存频率
                "amount": p["amount"],
                "start_date": p["start_date"],
                "active": p.get("active", True),
                "ignored_dates": p.get("ignored_dates", [])
            })

        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def load_data_from_file(self, filepath):
        if not os.path.exists(filepath): return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.is_initialized = False
            self.entry_start_date.configure(state="normal")
            self.entry_init_money.configure(state="normal")
            self.btn_init.configure(state="normal", text="锁定初始值")

            if data.get("initialized"):
                self.is_initialized = True
                self.initial_capital = data["initial_capital"]
                self.start_date_obj = datetime.strptime(data["start_date"], "%Y-%m-%d").date()
                self.entry_start_date.set_date(self.start_date_obj)
                self.entry_init_money.delete(0, "end")
                self.entry_init_money.insert(0, str(self.initial_capital))
                self.entry_start_date.configure(state="disabled")
                self.entry_init_money.configure(state="disabled")
                self.btn_init.configure(state="disabled", text="已锁定")

            self.records = [(datetime.strptime(r["date"], "%Y-%m-%d").date(), r["amount"], r.get("remark", "")) for r in
                            data.get("records", [])]
            self.drip_records = [(datetime.strptime(d["date"], "%Y-%m-%d").date(), d["amount"], d.get("remark", "")) for
                                 d in data.get("drip_records", [])]

            self.drip_plans = []
            for p in data.get("drip_plans", []):
                self.drip_plans.append({
                    "id": p.get("id", str(uuid.uuid4())),
                    "name": p.get("name", "定投计划"),
                    "market": p.get("market", "CN"),
                    "frequency": p.get("frequency", "daily"),  # 读取频率，默认daily
                    "amount": p["amount"],
                    "start_date": p["start_date"],
                    "start_date_obj": datetime.strptime(p["start_date"], "%Y-%m-%d").date(),
                    "active": p.get("active", True),
                    "ignored_dates": p.get("ignored_dates", [])
                })

            self.render_tree_view()
        except Exception as e:
            messagebox.showerror("加载失败", f"文件损坏: {e}")

    # ================= 用户交互 =================

    def lock_initial(self):
        try:
            d_obj = self.entry_start_date.get_date()
            m = float(self.entry_init_money.get())
            if m <= 0: raise ValueError
            self.start_date_obj = d_obj
            self.initial_capital = m
            self.is_initialized = True
            self.entry_start_date.configure(state="disabled")
            self.entry_init_money.configure(state="disabled")
            self.btn_init.configure(state="disabled", text="已锁定")
            self.save_data()
            self.render_tree_view()
        except ValueError:
            messagebox.showerror("错误", "请输入正数")

    def open_drip_setup(self):
        if not self.is_initialized:
            messagebox.showwarning("提示", "请先锁定初始本金！")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("定投计划管理")
        dialog.geometry("600x650")  # 稍微加大一点
        dialog.grab_set()

        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 600) // 2
        y = (dialog.winfo_screenheight() - 650) // 2
        dialog.geometry(f"+{x}+{y}")

        new_frame = ctk.CTkFrame(dialog, fg_color=("gray90", "#3a3a3a"))
        new_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(new_frame, text="➕ 新建计划", font=("微软雅黑", 12, "bold")).pack(anchor="w", padx=10, pady=5)

        # 第一行输入
        grid_f = ctk.CTkFrame(new_frame, fg_color="transparent")
        grid_f.pack(padx=10, pady=5)

        ctk.CTkLabel(grid_f, text="名称:").grid(row=0, column=0, padx=5, sticky="e")
        name_entry = ctk.CTkEntry(grid_f, width=100, placeholder_text="如: 标普500")
        name_entry.grid(row=0, column=1, padx=5)

        ctk.CTkLabel(grid_f, text="市场:").grid(row=0, column=2, padx=5, sticky="e")
        market_var = ctk.StringVar(value="CN")
        market_combo = ctk.CTkComboBox(grid_f, width=80, values=["CN", "US"], variable=market_var)
        market_combo.grid(row=0, column=3, padx=5)

        # 第二行输入
        ctk.CTkLabel(grid_f, text="频率:").grid(row=1, column=0, padx=5, sticky="e", pady=5)
        freq_var = ctk.StringVar(value="daily")
        # 映射显示名到内部值
        freq_display_map = {"每日": "daily", "每周": "weekly", "每月": "monthly"}
        freq_value_map = {v: k for k, v in freq_display_map.items()}

        freq_combo = ctk.CTkComboBox(grid_f, width=100, values=["每日", "每周", "每月"],
                                     command=lambda x: freq_var.set(freq_display_map[x]))
        freq_combo.set("每日")  # 默认显示
        freq_combo.grid(row=1, column=1, padx=5, pady=5)

        ctk.CTkLabel(grid_f, text="金额:").grid(row=1, column=2, padx=5, sticky="e", pady=5)
        amount_entry = ctk.CTkEntry(grid_f, width=80, placeholder_text="100")
        amount_entry.grid(row=1, column=3, padx=5, pady=5)

        # 第三行输入
        ctk.CTkLabel(grid_f, text="首次扣款日:").grid(row=2, column=0, padx=5, sticky="e", pady=5)
        start_date_entry = DateEntry(grid_f, width=12, date_pattern='yyyy-mm-dd')
        start_date_entry.grid(row=2, column=1, columnspan=2, sticky="w", padx=5, pady=5)
        start_date_entry.set_date(self.today_bj)

        ctk.CTkLabel(grid_f, text="(周/月定投以此日为基准)").grid(row=2, column=3, padx=5, sticky="w")

        def add_plan():
            try:
                amt = float(amount_entry.get())
                if amt <= 0: raise ValueError
                name = name_entry.get().strip() or "未命名"
                market = market_var.get()
                freq = freq_var.get()  # daily, weekly, monthly

                self.drip_plans.append({
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "market": market,
                    "frequency": freq,
                    "amount": amt,
                    "start_date": start_date_entry.get_date().strftime("%Y-%m-%d"),
                    "start_date_obj": start_date_entry.get_date(),
                    "active": True,
                    "ignored_dates": []
                })
                self.save_data()
                self.generate_daily_drip_records()
                refresh_list()

                # 清空部分
                name_entry.delete(0, "end")
                amount_entry.delete(0, "end")
            except ValueError:
                messagebox.showerror("错误", "金额格式错误")

        ctk.CTkButton(new_frame, text="添加计划并运行", command=add_plan, fg_color="#27AE60").pack(pady=10)

        ctk.CTkLabel(dialog, text="📋 计划列表", font=("微软雅黑", 12, "bold")).pack(anchor="w", padx=20, pady=(10, 0))
        list_scroll = ctk.CTkScrollableFrame(dialog, height=350)
        list_scroll.pack(fill="both", expand=True, padx=10, pady=5)

        def toggle_plan(plan, var):
            plan['active'] = bool(var.get())
            self.save_data()
            if plan['active']: self.generate_daily_drip_records()

        def delete_plan(plan):
            if messagebox.askyesno("确认", "删除计划不会删除已生成的记录，确认删除？"):
                self.drip_plans.remove(plan)
                self.save_data()
                refresh_list()

        def refresh_list():
            for w in list_scroll.winfo_children(): w.destroy()
            if not self.drip_plans:
                ctk.CTkLabel(list_scroll, text="暂无计划").pack(pady=20)
                return

            for plan in self.drip_plans:
                p_frame = ctk.CTkFrame(list_scroll, fg_color=("white", "#2b2b2b"))
                p_frame.pack(fill="x", pady=2, padx=2)

                m_flag = "🇺🇸美股" if plan.get('market') == "US" else "🇨🇳A股"
                f_map = {"daily": "每日", "weekly": "每周", "monthly": "每月"}
                freq_str = f_map.get(plan.get('frequency', 'daily'), "每日")

                info = f"[{m_flag}] {plan['name']} | {freq_str} {plan['amount']}元\n起始日: {plan['start_date']}"
                ctk.CTkLabel(p_frame, text=info, anchor="w", justify="left", font=("Arial", 12)).pack(side="left",
                                                                                                      padx=10, pady=5)

                # 修改为文字按钮，透明背景
                ctk.CTkButton(p_frame, text="删除", width=50,
                              fg_color="transparent", border_width=1, border_color="gray",
                              text_color=("gray10", "gray90"),
                              hover_color=("gray80", "gray30"),
                              command=lambda p=plan: delete_plan(p)).pack(side="right", padx=5)

                sv = ctk.IntVar(value=1 if plan.get('active', True) else 0)
                ctk.CTkSwitch(p_frame, text="运行", variable=sv, width=60,
                              command=lambda p=plan, v=sv: toggle_plan(p, v)).pack(side="right", padx=5)

        refresh_list()

    def add_record(self, op_type):
        if not self.is_initialized:
            messagebox.showwarning("提示", "请先锁定本金")
            return
        try:
            m = float(self.entry_op_amount.get())
            if m <= 0: raise ValueError
            val = -m if op_type == "buy" else m
            self.records.append((self.entry_op_date.get_date(), val, self.entry_op_remark.get().strip()))
            self.entry_op_amount.delete(0, "end")
            self.entry_op_remark.delete(0, "end")
            self.save_data()
            self.render_tree_view()
        except:
            pass

    # ================= 修复后的删除逻辑 =================

    def delete_selected(self):
        selected_id = self.tree.selection()
        if not selected_id: return
        item = self.tree.item(selected_id[0])
        if 'group' in item.get('tags', []): return

        values = item["values"]
        if not values: return
        item_date_str = item["text"]

        if values[0] == "【初始本金】": return

        del_amt = float(values[1])
        # 兼容性处理，防止values长度不足
        del_remark = values[2] if len(values) > 2 else ""

        try:
            if values[0] == "【定投】":
                target_idx = -1
                for i, r in enumerate(self.drip_records):
                    r_remark = r[2] if len(r) > 2 else ""

                    if (r[0].strftime("%Y-%m-%d") == item_date_str and
                            abs(r[1] - del_amt) < 0.001 and
                            r_remark == del_remark):
                        target_idx = i
                        break

                if target_idx != -1:
                    msg = "您正在删除一条自动定投记录。\n\n下次启动时，是否永久不再补录这一天？\n(针对节假日或资金不足的情况建议选‘是’)"
                    should_ignore = messagebox.askyesno("删除确认", msg)

                    if should_ignore:
                        plan_name = del_remark.replace("计划:", "")
                        for p in self.drip_plans:
                            if p['name'] == plan_name:
                                if 'ignored_dates' not in p: p['ignored_dates'] = []
                                # 这里保存的是界面上显示的日期（可能是顺延后的实际日期）
                                # 为了稳健，我们应该同时忽略名义日期吗？
                                # 简化策略：只忽略这一天。如果因为顺延导致第二天又补录，用户再删一次即可。
                                if item_date_str not in p['ignored_dates']:
                                    p['ignored_dates'].append(item_date_str)
                                break
                    self.drip_records.pop(target_idx)
            else:
                for i, r in enumerate(self.records):
                    if (r[0].strftime("%Y-%m-%d") == item_date_str and
                            abs(r[1] - del_amt) < 0.001):
                        self.records.pop(i)
                        break

            self.save_data()
            self.render_tree_view()
        except Exception as e:
            messagebox.showerror("系统错误", f"删除失败: {str(e)}")
            print(f"删除异常: {e}")

    # ================= 优化后的 XIRR 计算 =================

    def calculate_xirr(self):
        try:
            end_val = float(self.entry_end_val.get())
            end_date = self.entry_end_date.get_date()
            txs = [(self.start_date_obj, -self.initial_capital)]
            txs += [(r[0], r[1]) for r in self.records]
            txs += [(d[0], d[1]) for d in self.drip_records]
            txs.append((end_date, end_val))
            txs.sort(key=lambda x: x[0])

            if txs[-1][0] <= txs[0][0]:
                messagebox.showerror("错误", "结束日期必须晚于开始日期")
                return

            dates = [t[0] for t in txs]
            amounts = [t[1] for t in txs]
            years = [(d - dates[0]).days / 365.0 for d in dates]

            def xnpv(rate):
                if rate <= -1.0: return float('inf')
                return sum([a / ((1 + rate) ** y) for a, y in zip(amounts, years)])

            try:
                res = optimize.brentq(xnpv, -0.999, 100)
            except:
                try:
                    res = optimize.newton(xnpv, 0.1, maxiter=50)
                except:
                    self.result_label.configure(text="计算失败: 数据可能不收敛", text_color="red")
                    return

            rate_pct = res * 100
            total_inv = sum([-a for a in amounts if a < 0])
            profit = sum([a for a in amounts if a > 0]) - total_inv

            color = "#C0392B" if rate_pct > 0 else "#27AE60"
            self.result_label.configure(text=f"年化: {rate_pct:.2f}% | 盈亏: {profit:,.2f}", text_color=color)
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
        except Exception as e:
            self.result_label.configure(text=f"计算出错: {e}", text_color="red")

    def export_backup(self):
        self.save_data()
        fn = f"backup_{datetime.now().strftime('%Y%m%d')}.json"
        path = filedialog.asksaveasfilename(initialfile=fn, defaultextension=".json")
        if path: shutil.copy(DATA_FILE, path)

    def import_backup(self):
        path = filedialog.askopenfilename()
        if path:
            self.load_data_from_file(path)
            self.save_data()


if __name__ == "__main__":
    app = GroupedFundApp()
    app.mainloop()
