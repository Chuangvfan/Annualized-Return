import customtkinter as ctk
from tkinter import messagebox, ttk, filedialog
from datetime import date, datetime, timedelta, timezone
from scipy import optimize
from tkcalendar import DateEntry
import json
import os
import shutil

# 设置外观
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

DATA_FILE = "my_fund_data.json"


class GroupedFundApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("基金年化记账本 (月份自动分组版)")
        self.geometry("900x850")  # 稍微加宽

        # 数据变量
        self.records = []
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

        # --- 3. 列表展示 (带分组和滚动条) ---
        self.tree_frame = ctk.CTkFrame(self)
        self.tree_frame.grid(row=3, column=0, padx=20, pady=5, sticky="nsew")

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", rowheight=28, font=("Arial", 11))
        style.configure("Treeview.Heading", font=("微软雅黑", 11, "bold"))

        # 注意：这里我们使用了 #0 列作为树状层级列
        columns = ("type", "amount")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, selectmode="browse")

        # 配置列 (#0 是自带的树状列，我们用来显示日期和组名)
        self.tree.heading("#0", text="日期 / 月份分组")
        self.tree.heading("type", text="操作类型")
        self.tree.heading("amount", text="金额 (流向)")

        self.tree.column("#0", width=250, anchor="w")  # 左对齐方便看树形结构
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

    # ================= 核心：月份分组渲染逻辑 =================

    def render_tree_view(self):
        """重新渲染整个列表，按月份分组"""
        # 1. 清空当前列表
        for item in self.tree.get_children():
            self.tree.delete(item)

        # 2. 收集所有数据（包括初始本金）
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

        # 3. 按日期排序
        all_items.sort(key=lambda x: x["date"])

        # 4. 分组并插入
        current_month_key = None
        parent_node = None
        month_items = []  # 暂存当月数据用于计算合计

        # 辅助函数：插入之前的月份组
        def insert_month_group(month_key, items):
            if not month_key: return
            month_sum = sum(item["amount"] for item in items)
            sum_text = f"月度净流: {month_sum:+.2f}"

            # 插入父节点 (月份)
            # 这里的 text 就是显示在第一列 (#0) 的内容
            p_id = self.tree.insert("", "end", text=f"📅 {month_key} ({sum_text})", open=True)

            # 插入子节点 (具体记录)
            for item in items:
                display_date = item["date"].strftime("%Y-%m-%d")
                val_tuple = (item["type"], f"{item['amount']}")
                # values 对应 columns 定义的列 (type, amount)
                # text 对应 #0 列 (日期)
                self.tree.insert(p_id, "end", text=display_date, values=val_tuple)

        for item in all_items:
            month_key = item["date"].strftime("%Y年%m月")

            if month_key != current_month_key:
                # 遇到新月份，先把上一个月渲染出来
                insert_month_group(current_month_key, month_items)
                # 重置
                current_month_key = month_key
                month_items = []

            month_items.append(item)

        # 渲染最后一个月
        insert_month_group(current_month_key, month_items)

    # ================= 数据存取 =================

    def save_data(self):
        data = {
            "initialized": self.is_initialized,
            "initial_capital": self.initial_capital,
            "start_date": self.start_date_obj.strftime("%Y-%m-%d") if self.start_date_obj else None,
            "records": []
        }
        for r in self.records:
            data["records"].append({
                "date": r[0].strftime("%Y-%m-%d"),
                "amount": r[1]
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
                amount = r["amount"]
                self.records.append((d_obj, amount))

            # 加载完数据后，调用分组渲染
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
            self.render_tree_view()  # 刷新视图
        except ValueError:
            messagebox.showerror("错误", "金额必须是数字")

    def add_record(self, op_type):
        if not self.is_initialized:
            messagebox.showwarning("提示", "请先锁定初始本金！")
            return
        try:
            d_obj = self.entry_op_date.get_date()
            m_str = self.entry_op_amount.get()
            if not m_str: return
            m = float(m_str)
        except:
            return

        real_val = -m if op_type == "buy" else m

        self.records.append((d_obj, real_val))
        self.entry_op_amount.delete(0, "end")

        self.save_data()
        self.render_tree_view()  # 刷新视图

    def delete_selected(self):
        selected_id = self.tree.selection()
        if not selected_id: return

        # 获取选中项的详细信息
        item = self.tree.item(selected_id[0])

        # 如果选中的是父节点（月份），不允许删除，提示用户
        # 判断方法：父节点values一般是空的或者我们在values里没有存那么多数据，
        # 最简单的方法是看它是否有子节点，或者直接看 values 的长度/内容
        # 在我们的逻辑里，父节点的 text 是 "📅 2024年1月...", 子节点 text 是 "2024-01-01"
        item_text = item["text"]

        if "📅" in item_text:
            messagebox.showwarning("操作无效", "请选中具体的记录行进行删除，\n不能直接删除整个月份分组。")
            return

        item_values = item["values"]
        # values[0] 是 type, values[1] 是 amount
        # text 是日期

        del_date_str = item_text
        if item_values[0] == "【初始本金】":
            messagebox.showwarning("提示", "初始本金不能删除")
            return

        try:
            del_amount = float(item_values[1])
            # 在 records 列表里查找并删除
            for i, r in enumerate(self.records):
                if r[0].strftime("%Y-%m-%d") == del_date_str and abs(r[1] - del_amount) < 0.001:
                    self.records.pop(i)
                    break

            self.save_data()
            self.render_tree_view()  # 重新分组渲染
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