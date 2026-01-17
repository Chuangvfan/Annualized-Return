import customtkinter as ctk
from tkinter import messagebox, ttk, filedialog
from datetime import date, datetime, timedelta, timezone
from scipy import optimize
from tkcalendar import DateEntry
import json
import os
import shutil
import pandas_market_calendars as mcal
import uuid  # 新增：用于给每个计划生成唯一ID

# 设置外观
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

DATA_FILE = "my_fund_data.json"


class GroupedFundApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("基金年化记账本 (定投策略升级版)")
        self.geometry("950x850")

        # 数据变量
        self.records = []
        self.drip_records = []  # 定投记录
        self.drip_plans = []  # 定投计划列表
        self.initial_capital = 0.0
        self.start_date_obj = None
        self.is_initialized = False

        # 获取北京时间
        utc_now = datetime.now(timezone.utc)
        beijing_now = utc_now.astimezone(timezone(timedelta(hours=8)))
        self.today_bj = beijing_now.date()

        # ============ UI 布局 ============
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # --- 1. 初始本金 ---
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

        # --- 2. 中间操作 ---
        self.frame_ops = ctk.CTkFrame(self)
        self.frame_ops.grid(row=1, column=0, padx=20, pady=10, sticky="ew")

        ctk.CTkLabel(self.frame_ops, text="第二步：记录买卖", font=("微软雅黑", 14, "bold")).grid(row=0, column=0,
                                                                                                 padx=10, pady=5)

        self.entry_op_date = DateEntry(self.frame_ops, width=12, background='#3B8ED0',
                                       foreground='white', borderwidth=2,
                                       date_pattern='yyyy-mm-dd', font=("Arial", 12))
        self.entry_op_date.grid(row=1, column=1, padx=5, pady=5)
        self.entry_op_date.set_date(self.today_bj)

        self.entry_op_amount = ctk.CTkEntry(self.frame_ops, placeholder_text="金额")
        self.entry_op_amount.grid(row=1, column=2, padx=10, pady=5)

        self.btn_buy = ctk.CTkButton(self.frame_ops, text="买入 (投钱)", fg_color="#27AE60", hover_color="#1E8449",
                                     command=lambda: self.add_record("buy"))
        self.btn_buy.grid(row=1, column=3, padx=5)

        self.btn_sell = ctk.CTkButton(self.frame_ops, text="卖出 (拿钱)", fg_color="#C0392B", hover_color="#922B21",
                                      command=lambda: self.add_record("sell"))
        self.btn_sell.grid(row=1, column=4, padx=5)

        self.btn_del = ctk.CTkButton(self.frame_ops, text="删除选中行", fg_color="gray", width=80,
                                     command=self.delete_selected)
        self.btn_del.grid(row=1, column=5, padx=5)

        self.btn_drip = ctk.CTkButton(self.frame_ops, text="定投管理", fg_color="#8E44AD", hover_color="#7D3C98",
                                      command=self.open_drip_setup)
        self.btn_drip.grid(row=1, column=6, padx=5)

        # --- 3. 列表展示 (带分组和滚动条) ---
        self.tree_frame = ctk.CTkFrame(self)
        self.tree_frame.grid(row=3, column=0, padx=20, pady=5, sticky="nsew")

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", rowheight=28, font=("Arial", 11))
        style.configure("Treeview.Heading", font=("微软雅黑", 11, "bold"))

        columns = ("type", "amount")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, selectmode="browse")

        self.tree.heading("#0", text="日期 / 月份分组")
        self.tree.heading("type", text="操作类型")
        self.tree.heading("amount", text="金额 (流向)")

        self.tree.column("#0", width=250, anchor="w")
        self.tree.column("type", width=150, anchor="center")
        self.tree.column("amount", width=150, anchor="center")

        self.scrollbar = ctk.CTkScrollbar(self.tree_frame, orientation="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        # --- 4. 期末计算 ---
        self.frame_calc = ctk.CTkFrame(self, border_width=2, border_color="#3498DB")
        self.frame_calc.grid(row=4, column=0, padx=20, pady=20, sticky="ew")

        ctk.CTkLabel(self.frame_calc, text="第三步：期末结算", font=("微软雅黑", 14, "bold")).grid(row=0, column=0,
                                                                                                  padx=10, pady=10)

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
        self.result_label.grid(row=2, column=0, columnspan=4, pady=10)

        # --- 5. 数据管理 ---
        self.frame_data = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_data.grid(row=5, column=0, padx=20, pady=10, sticky="ew")

        self.btn_export = ctk.CTkButton(self.frame_data, text="📤 导出备份", fg_color="#5D6D7E", hover_color="#34495E",
                                        command=self.export_backup)
        self.btn_export.pack(side="left", padx=10)
        self.btn_import = ctk.CTkButton(self.frame_data, text="📥 导入数据", fg_color="#5D6D7E", hover_color="#34495E",
                                        command=self.import_backup)
        self.btn_import.pack(side="right", padx=10)

        # 启动
        self.load_data_from_file(DATA_FILE)

        # 检查并生成今天的定投记录
        self.generate_daily_drip_records()

    # ================= 核心：月份分组渲染逻辑 =================

    def render_tree_view(self):
        """重新渲染整个列表，按月份分组"""
        for item in self.tree.get_children():
            self.tree.delete(item)

        all_items = []
        if self.is_initialized:
            all_items.append({
                "date": self.start_date_obj,
                "type": "【初始本金】",
                "amount": -self.initial_capital,
                "is_init": True
            })

        for r in self.records:
            all_items.append({
                "date": r[0],
                "type": "买入/追加" if r[1] < 0 else "卖出/取现",
                "amount": r[1],
                "is_init": False
            })

        for d in self.drip_records:
            all_items.append({
                "date": d[0],
                "type": "【定投】",
                "amount": d[1],
                "is_init": False
            })

        all_items.sort(key=lambda x: x["date"])

        current_month_key = None
        month_items = []

        def insert_month_group(month_key, items):
            if not month_key: return
            month_sum = sum(item["amount"] for item in items)
            sum_text = f"月度净流: {month_sum:+.2f}"
            p_id = self.tree.insert("", "end", text=f"📅 {month_key} ({sum_text})", open=True)
            for item in items:
                display_date = item["date"].strftime("%Y-%m-%d")
                val_tuple = (item["type"], f"{item['amount']}")
                self.tree.insert(p_id, "end", text=display_date, values=val_tuple)

        for item in all_items:
            month_key = item["date"].strftime("%Y年%m月")
            if month_key != current_month_key:
                insert_month_group(current_month_key, month_items)
                current_month_key = month_key
                month_items = []
            month_items.append(item)

        insert_month_group(current_month_key, month_items)

    # ================= 数据存取 =================

    def is_trading_day(self, check_date):
        try:
            cal = mcal.get_calendar('XSHG')
            schedule = cal.schedule(start_date=check_date - timedelta(days=30),
                                    end_date=check_date + timedelta(days=30))
            trading_days = schedule.index.date
            return check_date in trading_days
        except Exception as e:
            print(f"获取交易日历失败: {e}")
            return True

    def generate_daily_drip_records(self):
        """生成今天的定投记录（基于活跃的计划）"""
        today_str = self.today_bj.strftime("%Y-%m-%d")

        # 1. 检查今天是否已扣款
        for record in self.drip_records:
            if record[0].strftime("%Y-%m-%d") == today_str:
                return

        # 2. 检查是否为交易日
        if not self.is_trading_day(self.today_bj):
            return

        # 3. 遍历计划，只处理 ACTIVE 且 日期已开始的
        new_records_generated = False
        for plan in self.drip_plans:
            # 兼容旧数据：如果没 active 字段，默认为 True，如果有 end_date 暂且不管，只看 active
            is_active = plan.get('active', True)
            start_date = plan['start_date_obj']

            if is_active and self.today_bj >= start_date:
                # 再次检查：确保该计划今天没单独生成过（防止多计划重叠时的逻辑漏洞）
                already_generated = False
                # 这里我们假设一个计划一天只投一次。如果需要更精细的追踪，需要记录 plan_id
                # 但目前为了简单，我们检查金额和日期
                for record in self.drip_records:
                    if (record[0] == self.today_bj and
                            abs(record[1] - (-plan['amount'])) < 0.001):
                        already_generated = True
                        break

                if not already_generated:
                    self.drip_records.append((self.today_bj, -plan['amount']))
                    new_records_generated = True

        if new_records_generated:
            self.save_data()
            self.render_tree_view()

    def save_data(self):
        data = {
            "initialized": self.is_initialized,
            "initial_capital": self.initial_capital,
            "start_date": self.start_date_obj.strftime("%Y-%m-%d") if self.start_date_obj else None,
            "records": [],
            "drip_records": [],
            "drip_plans": []
        }
        for r in self.records:
            data["records"].append({"date": r[0].strftime("%Y-%m-%d"), "amount": r[1]})
        for d in self.drip_records:
            data["drip_records"].append({"date": d[0].strftime("%Y-%m-%d"), "amount": d[1]})

        for p in self.drip_plans:
            # 保存计划数据，移除 end_date，增加 active 和 id
            data["drip_plans"].append({
                "id": p.get("id", str(uuid.uuid4())),
                "name": p.get("name", "未命名计划"),
                "amount": p["amount"],
                "start_date": p["start_date"],
                "active": p.get("active", True)
            })

        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def load_data_from_file(self, filepath):
        if not os.path.exists(filepath): return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.entry_start_date.configure(state="normal")
            self.entry_init_money.configure(state="normal")
            self.btn_init.configure(state="normal", text="锁定初始值")
            self.is_initialized = False

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

            self.records = []
            for r in data.get("records", []):
                d_obj = datetime.strptime(r["date"], "%Y-%m-%d").date()
                self.records.append((d_obj, r["amount"]))

            self.drip_records = []
            for d in data.get("drip_records", []):
                d_obj = datetime.strptime(d["date"], "%Y-%m-%d").date()
                self.drip_records.append((d_obj, d["amount"]))

            self.drip_plans = []
            for p in data.get("drip_plans", []):
                start_date_obj = datetime.strptime(p["start_date"], "%Y-%m-%d").date()

                # 兼容旧数据处理
                active_status = p.get("active", True)

                # 如果是旧数据（有end_date但没有active），我们假设只要还没过期就是True
                if "end_date" in p and "active" not in p:
                    end_obj = datetime.strptime(p["end_date"], "%Y-%m-%d").date()
                    if end_obj < self.today_bj:
                        active_status = False  # 已过期的旧计划默认关闭

                self.drip_plans.append({
                    "id": p.get("id", str(uuid.uuid4())),
                    "name": p.get("name", "定投计划"),
                    "amount": p["amount"],
                    "start_date": p["start_date"],
                    "start_date_obj": start_date_obj,
                    "active": active_status
                })

            self.render_tree_view()

        except Exception as e:
            messagebox.showerror("加载失败", f"{e}")

    # ================= 用户操作 =================

    def lock_initial(self):
        try:
            d_obj = self.entry_start_date.get_date()
            m_str = self.entry_init_money.get()
            if not m_str: return
            m = float(m_str)
            if m <= 0: return

            self.start_date_obj = d_obj
            self.initial_capital = m
            self.is_initialized = True
            self.entry_start_date.configure(state="disabled")
            self.entry_init_money.configure(state="disabled")
            self.btn_init.configure(state="disabled", text="已锁定")
            self.save_data()
            self.render_tree_view()
        except ValueError:
            messagebox.showerror("错误", "金额必须是数字")

    def open_drip_setup(self):
        """打开定投管理面板（升级版）"""
        if not self.is_initialized:
            messagebox.showwarning("提示", "请先锁定初始本金！")
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("管理定投计划")
        dialog.geometry("500x500")  # 加大窗口
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        # 居中
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (500 // 2)
        y = (dialog.winfo_screenheight() // 2) - (500 // 2)
        dialog.geometry(f"+{x}+{y}")

        # --- 新建计划区域 ---
        new_frame = ctk.CTkFrame(dialog, fg_color=("gray90", "gray20"))
        new_frame.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(new_frame, text="➕ 新建计划", font=("微软雅黑", 12, "bold")).pack(anchor="w", padx=10, pady=5)

        grid_f = ctk.CTkFrame(new_frame, fg_color="transparent")
        grid_f.pack(padx=10, pady=5)

        ctk.CTkLabel(grid_f, text="名称:").grid(row=0, column=0, padx=5, sticky="e")
        name_entry = ctk.CTkEntry(grid_f, width=100, placeholder_text="如: 沪深300")
        name_entry.grid(row=0, column=1, padx=5)

        ctk.CTkLabel(grid_f, text="日金额:").grid(row=0, column=2, padx=5, sticky="e")
        amount_entry = ctk.CTkEntry(grid_f, width=80, placeholder_text="100")
        amount_entry.grid(row=0, column=3, padx=5)

        ctk.CTkLabel(grid_f, text="开始日:").grid(row=0, column=4, padx=5, sticky="e")
        start_date_entry = DateEntry(grid_f, width=10, background='#3B8ED0',
                                     foreground='white', borderwidth=2,
                                     date_pattern='yyyy-mm-dd', font=("Arial", 10))
        start_date_entry.grid(row=0, column=5, padx=5)
        start_date_entry.set_date(self.today_bj)

        def add_plan():
            try:
                amt = float(amount_entry.get())
                if amt <= 0: raise ValueError
                name = name_entry.get().strip()
                if not name: name = "定投计划"

                self.drip_plans.append({
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "amount": amt,
                    "start_date": start_date_entry.get_date().strftime("%Y-%m-%d"),
                    "start_date_obj": start_date_entry.get_date(),
                    "active": True
                })
                self.save_data()
                refresh_list()  # 刷新列表
                # 清空输入
                name_entry.delete(0, "end")
                amount_entry.delete(0, "end")
            except ValueError:
                messagebox.showerror("错误", "请输入正确的金额")

        ctk.CTkButton(new_frame, text="添加并启动", command=add_plan, fg_color="#27AE60").pack(pady=10)

        # --- 现有计划列表 ---
        ctk.CTkLabel(dialog, text="📋 现有计划 (点击开关控制启停)", font=("微软雅黑", 12, "bold")).pack(anchor="w",
                                                                                                       padx=20,
                                                                                                       pady=(10, 0))

        list_scroll = ctk.CTkScrollableFrame(dialog, height=300)
        list_scroll.pack(fill="both", expand=True, padx=10, pady=5)

        def toggle_plan(plan, switch_var):
            plan['active'] = bool(switch_var.get())
            self.save_data()
            # 更新状态标签颜色（可选）

        def delete_plan_permanent(plan):
            if messagebox.askyesno("删除", "确定彻底删除此计划吗？\n(历史已生成的扣款记录不会被删除)"):
                if plan in self.drip_plans:
                    self.drip_plans.remove(plan)
                    self.save_data()
                    refresh_list()

        def refresh_list():
            for widget in list_scroll.winfo_children():
                widget.destroy()

            if not self.drip_plans:
                ctk.CTkLabel(list_scroll, text="暂无计划").pack(pady=20)
                return

            for plan in self.drip_plans:
                p_frame = ctk.CTkFrame(list_scroll, fg_color=("white", "#333333"))
                p_frame.pack(fill="x", pady=2, padx=2)

                # 左侧信息
                info_text = f"{plan['name']}\n每日 {plan['amount']}元 | {plan['start_date']} 开始"
                ctk.CTkLabel(p_frame, text=info_text, anchor="w", justify="left").pack(side="left", padx=10, pady=5)

                # 右侧删除按钮
                ctk.CTkButton(p_frame, text="🗑️", width=40, fg_color="#C0392B",
                              command=lambda p=plan: delete_plan_permanent(p)).pack(side="right", padx=5)

                # 右侧开关
                switch_var = ctk.IntVar(value=1 if plan.get('active', True) else 0)
                sw = ctk.CTkSwitch(p_frame, text="运行中" if plan.get('active', True) else "已暂停",
                                   variable=switch_var, onvalue=1, offvalue=0, width=80,
                                   command=lambda p=plan, v=switch_var: toggle_plan_ui(p, v))
                sw.pack(side="right", padx=10)

                # 闭包辅助函数，用于更新开关文字
                def toggle_plan_ui(p, v, s=sw):
                    is_on = bool(v.get())
                    p['active'] = is_on
                    s.configure(text="运行中" if is_on else "已暂停")
                    self.save_data()

        refresh_list()

    def add_record(self, op_type):
        if not self.is_initialized:
            messagebox.showwarning("提示", "请先锁定初始本金！")
            return
        try:
            d_obj = self.entry_op_date.get_date()
            m_str = self.entry_op_amount.get()
            if not m_str: return
            m = float(m_str)
            if m <= 0: return
        except:
            return

        if op_type == "buy":
            real_val = -m
            self.records.append((d_obj, real_val))
        elif op_type == "sell":
            real_val = m
            self.records.append((d_obj, real_val))

        self.entry_op_amount.delete(0, "end")
        self.save_data()
        self.render_tree_view()

    def delete_selected(self):
        selected_id = self.tree.selection()
        if not selected_id: return
        item = self.tree.item(selected_id[0])
        item_text = item["text"]

        if "📅" in item_text:
            messagebox.showwarning("操作无效", "请选中具体的记录行进行删除，\n不能直接删除整个月份分组。")
            return

        item_values = item["values"]
        del_date_str = item_text
        if item_values[0] == "【初始本金】":
            messagebox.showwarning("提示", "初始本金不能删除")
            return

        try:
            del_amount = float(item_values[1])
            if item_values[0] == "【定投】":
                for i, d in enumerate(self.drip_records):
                    if d[0].strftime("%Y-%m-%d") == del_date_str and abs(d[1] - del_amount) < 0.001:
                        self.drip_records.pop(i)
                        break
            else:
                for i, r in enumerate(self.records):
                    if r[0].strftime("%Y-%m-%d") == del_date_str and abs(r[1] - del_amount) < 0.001:
                        self.records.pop(i)
                        break

            self.save_data()
            self.render_tree_view()
        except:
            pass

    def calculate_xirr(self):
        try:
            end_date_obj = self.entry_end_date.get_date()
            val_str = self.entry_end_val.get()
            if not val_str: return
            end_val = float(val_str)
        except:
            return

        all_transactions = []
        all_transactions.append((self.start_date_obj, -self.initial_capital))
        for r in self.records:
            all_transactions.append((r[0], r[1]))
        for d in self.drip_records:
            all_transactions.append((d[0], d[1]))
        all_transactions.append((end_date_obj, end_val))

        all_transactions.sort(key=lambda x: x[0])
        dates = [x[0] for x in all_transactions]
        amounts = [x[1] for x in all_transactions]

        if dates[-1] <= dates[0]:
            messagebox.showerror("时间错误", "结算日期必须晚于开始日期！")
            return
        if not (any(a > 0 for a in amounts) and any(a < 0 for a in amounts)):
            self.result_label.configure(text="错误：需有进有出", text_color="red")
            return

        try:
            min_date = dates[0]
            time_diffs = [(d - min_date).days / 365.0 for d in dates]

            def npv(rate):
                return sum([cf / ((1 + rate) ** t) for cf, t in zip(amounts, time_diffs)])

            try:
                res = optimize.brentq(npv, -0.9999999, 1000000.0)
            except ValueError:
                res = optimize.newton(npv, 0.1, maxiter=500)

            rate_pct = res * 100
            total_in = sum([-x for x in amounts if x < 0])
            total_back = sum([x for x in amounts if x > 0])
            profit = total_back - total_in

            color = "#C0392B" if rate_pct > 0 else "#27AE60"
            self.result_label.configure(
                text=f"年化: {rate_pct:.2f}%  (盈亏: {profit:.2f})",
                text_color=color, font=("微软雅黑", 20, "bold")
            )
        except Exception:
            self.result_label.configure(text="计算异常", text_color="red")

    def export_backup(self):
        self.save_data()
        default_name = f"fund_backup_{datetime.now().strftime('%Y%m%d')}.json"
        target_path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")],
                                                   initialfile=default_name, title="导出")
        if target_path:
            shutil.copy(DATA_FILE, target_path)
            messagebox.showinfo("成功", f"备份已保存: {target_path}")

    def import_backup(self):
        source_path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")], title="选择备份")
        if source_path:
            if messagebox.askyesno("警告", "导入将覆盖当前数据，是否继续？"):
                self.load_data_from_file(source_path)
                shutil.copy(source_path, DATA_FILE)
                messagebox.showinfo("成功", "数据已恢复！")


if __name__ == "__main__":
    app = GroupedFundApp()
    app.mainloop()
