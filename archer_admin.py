import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog
import sqlite3, pandas as pd, smtplib, threading, time, os, sys, winsound, subprocess, configparser, ctypes
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import socket

# --- CONFIGURATION MANAGER ---
def get_db_path():
    config = configparser.ConfigParser()
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
    default_path = r'\\10.0.111.7\Analosima\archer\archer.db'
    if os.path.exists(config_file):
        try:
            config.read(config_file)
            return config.get('SETTINGS', 'db_path', fallback=default_path)
        except: return default_path
    return default_path

def save_db_path_to_ini(new_path):
    config = configparser.ConfigParser()
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
    config['SETTINGS'] = {'db_path': new_path}
    with open(config_file, 'w') as configfile:
        config.write(configfile)

DB_PATH = get_db_path()
LOCK_FILE_ADMIN = os.path.join(os.environ.get('TEMP', ''), 'archer_admin.lock')

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class ArcherAdmin:
    def __init__(self, root):
        self.check_single_instance()
        self.init_db_extensions()
        self.root = root
        self.root.title("Archer Control Panel Pro - Master Edition v4.0")
        self.root.geometry("1850x900")
        
        self.logs_dept_filter = "ALL"
        self.live_dept_filter = "ALL"
        self.search_query = ""
        self.last_msg_id = 0
        self.previously_online = set()
        self.ping_results = {}
        
        self.get_initial_msg_id()
        self.setup_styles()
        self.setup_ui()
        self.refresh_data()
        
        threading.Thread(target=self.scheduler_worker, daemon=True).start()
        threading.Thread(target=self.auto_ping_worker, daemon=True).start()

    def check_single_instance(self):
        if os.path.exists(LOCK_FILE_ADMIN):
            try: os.remove(LOCK_FILE_ADMIN)
            except: sys.exit()
        with open(LOCK_FILE_ADMIN, 'w') as f: f.write("locked")

    def init_db_extensions(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            cols = [('anydesk_id', 'TEXT'), ('phone', 'TEXT'), ('ip_type', 'TEXT')]
            for col_name, col_type in cols:
                try: conn.execute(f"ALTER TABLE user_config ADD COLUMN {col_name} {col_type}")
                except: pass
            conn.execute("CREATE TABLE IF NOT EXISTS dept_emails (department TEXT PRIMARY KEY, email TEXT)")
            conn.execute("CREATE TABLE IF NOT EXISTS user_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, message TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE IF NOT EXISTS admin_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, message TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
            # ΝΕΟΣ ΠΙΝΑΚΑΣ: επιλογές μενού ανά τμήμα
            conn.execute("CREATE TABLE IF NOT EXISTS dept_menu_options (department TEXT PRIMARY KEY, menu_options TEXT)")
            defaults = [
                ('idle_threshold', '300'), ('report_time', '16:00'),
                ('menu_options', 'UNLOAD, BREAK, RESTART, MACHINE ISSUE'),
                ('smtp_server', 'smtp.gmail.com'), ('sender_email', 'your@email.com'), ('sender_pass', 'password')
            ]
            for k, v in defaults:
                conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
            conn.commit()
            conn.close()
        except Exception as e: print(f"DB Init Error: {e}")

    def get_initial_msg_id(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            res = conn.execute("SELECT MAX(id) FROM admin_messages").fetchone()
            if res and res[0]: self.last_msg_id = res[0]
            conn.close()
        except: pass

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", font=("Segoe UI Emoji", 10), rowheight=30)
        style.configure("Treeview.Heading", background="#1f538d", foreground="white", font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[('selected', '#3498db')])

    def setup_ui(self):
        self.tabview = ctk.CTkTabview(self.root)
        self.tabview.pack(expand=True, fill="both", padx=10, pady=10)
        
        self.tab_logs = self.tabview.add("Evets")
        self.tab_users = self.tabview.add("Live Status")
        self.tab_replies = self.tabview.add("Messages")
        self.tab_config = self.tabview.add("Settings")

        # TAB 1 ΣΥΜΒΑΝΤΑ
        f_logs = ctk.CTkFrame(self.tab_logs)
        f_logs.pack(expand=True, fill="both", padx=10, pady=10)
        l_tool = ctk.CTkFrame(f_logs, height=50)
        l_tool.pack(side="top", fill="x", padx=5, pady=5)
        ctk.CTkLabel(l_tool, text="Department Filter:").pack(side="left", padx=10)
        self.combo_logs_dept = ctk.CTkOptionMenu(l_tool, values=["ALL"], command=self.filter_logs_changed)
        self.combo_logs_dept.pack(side="left", padx=5)
        ctk.CTkButton(l_tool, text="🗑️ Delete Pending Events", fg_color="#c0392b", command=self.confirm_clear_unsent_events).pack(side="right", padx=10)
        self.tree_logs = self.create_tree(f_logs, ("u", "t", "s", "e", "d"), ("USER", "TYPE", "START", "END", "DURATION/MIN"))

        # TAB 2 LIVE STATUS
        f_status_main = ctk.CTkFrame(self.tab_users)
        f_status_main.pack(expand=True, fill="both", padx=10, pady=10)
        s_tool = ctk.CTkFrame(f_status_main, height=60)
        s_tool.pack(side="top", fill="x", padx=5, pady=5)
        ctk.CTkLabel(s_tool, text="Τμήμα:").pack(side="left", padx=5)
        self.combo_live_dept = ctk.CTkOptionMenu(s_tool, values=["ΟΛΑ"], command=self.filter_live_changed)
        self.combo_live_dept.pack(side="left", padx=5)
        self.ent_search = ctk.CTkEntry(s_tool, placeholder_text="🔍 Search...", width=200)
        self.ent_search.pack(side="left", padx=20)
        self.ent_search.bind("<KeyRelease>", self.update_search)
        ctk.CTkButton(s_tool, text="📡 PING ALL", fg_color="#8e44ad", width=120, command=self.manual_ping).pack(side="right", padx=10)

        mid_section = ctk.CTkFrame(f_status_main, fg_color="transparent")
        mid_section.pack(expand=True, fill="both")
        self.tree_status = self.create_tree(mid_section, 
                                            ("uid", "u", "h", "i", "t", "d", "any", "p", "s"),
                                            ("User@Host", "Username", "Hostname", "IP", "IP TYPE", "DEPARTMENT", "ANYDESK ID", "INT PHONE", "STATUS"))

        self.tree_status.tag_configure('online', foreground='#2ecc71')
        self.tree_status.tag_configure('archer_off', foreground='#f39c12')
        self.tree_status.tag_configure('offline', foreground='#e74c3c')

        self.form = ctk.CTkFrame(mid_section, width=280)
        self.form.pack(side="right", fill="y", padx=10, pady=10)
        ctk.CTkLabel(self.form, text="USER INFO", font=("Arial", 16, "bold")).pack(pady=10)
        self.ent_dept = ctk.CTkEntry(self.form, placeholder_text="DEPARTMENT"); self.ent_dept.pack(pady=5, padx=10, fill="x")
        self.ent_u = ctk.CTkEntry(self.form, placeholder_text="Username"); self.ent_u.pack(pady=5, padx=10, fill="x")
        self.ent_ip = ctk.CTkEntry(self.form, placeholder_text="IP Address"); self.ent_ip.pack(pady=5, padx=10, fill="x")
        self.ent_iptype = ctk.CTkEntry(self.form, placeholder_text="IP TYPE", state="readonly"); self.ent_iptype.pack(pady=5, padx=10, fill="x")
        self.ent_phone = ctk.CTkEntry(self.form, placeholder_text="INT PHONE"); self.ent_phone.pack(pady=5, padx=10, fill="x")
        self.ent_anydesk = ctk.CTkEntry(self.form, placeholder_text="AnyDesk ID"); self.ent_anydesk.pack(pady=5, padx=10, fill="x")

        btn_frame = ctk.CTkFrame(self.form, fg_color="transparent")
        btn_frame.pack(pady=10, padx=10, fill="x")
        ctk.CTkButton(btn_frame, text="💾 SAVE", fg_color="#27ae60", command=self.save_user).pack(side="left", padx=5, expand=True, fill="x")
        ctk.CTkButton(btn_frame, text="🗑️ DELETE USER", fg_color="#c0392b", command=self.confirm_delete_user).pack(side="left", padx=5, expand=True, fill="x")
        ctk.CTkButton(self.form, text="⚡ ANYDESK CONNECT", fg_color="#c0392b", command=self.connect_anydesk).pack(pady=5, padx=10, fill="x")

        self.msg_text = ctk.CTkEntry(self.form, placeholder_text="Instant Msg...", font=("Segoe UI Emoji", 12))
        self.msg_text.pack(pady=(20, 5), padx=10, fill="x")
        ctk.CTkButton(self.form, text="😊 Emoji (Win+.)", fg_color="#34495e", height=25, command=self.open_emoji_picker).pack(padx=10, fill="x")
        ctk.CTkButton(self.form, text="SEND", fg_color="#1f538d", command=self.send_instant_msg).pack(pady=10, padx=10, fill="x")

        self.log_frame = ctk.CTkFrame(f_status_main, height=180)
        self.log_frame.pack(side="bottom", fill="x", padx=5, pady=5)
        self.log_area = ctk.CTkTextbox(self.log_frame, height=140, font=("Consolas", 11), fg_color="#000000")
        self.log_area.pack(expand=True, fill="both", padx=10, pady=5)
        self.log_area.configure(state="disabled")

        # TAB 3 ΑΠΑΝΤΗΣΕΙΣ
        f_replies = ctk.CTkFrame(self.tab_replies)
        f_replies.pack(expand=True, fill="both", padx=10, pady=10)
        self.tree_replies = self.create_tree(f_replies, ("t", "u", "m"), ("Time", "USER", "MESSAGE"))
        ctk.CTkButton(f_replies, text="CLEAN HISTORY", fg_color="#c0392b", command=self.clear_replies).pack(pady=10)
        self.tree_status.column("uid", width=180, minwidth=120, stretch=False, anchor="w")   # User@Host
        self.tree_status.column("u",   width=100, minwidth=80,  stretch=False, anchor="center") # Username
        self.tree_status.column("h",   width=120, minwidth=90,  stretch=False, anchor="center") # Hostname
        self.tree_status.column("i",   width=110, minwidth=90,  stretch=False, anchor="center") # IP
        self.tree_status.column("t",   width=90,  minwidth=70,  stretch=False, anchor="center") # ΤΥΠΟΣ IP
        self.tree_status.column("d",   width=110, minwidth=90,  stretch=False, anchor="center") # ΤΜΗΜΑ
        self.tree_status.column("any", width=100, minwidth=80,  stretch=False, anchor="center") # ANYDESK
        self.tree_status.column("p",   width=70,  minwidth=60,  stretch=False, anchor="center") # ΤΗΛ
        self.tree_status.column("s",   width=120, minwidth=100, stretch=False, anchor="center") # STATUS

        self.setup_config_tab()

    def setup_config_tab(self):
        container = ctk.CTkScrollableFrame(self.tab_config, fg_color="transparent")
        container.pack(expand=True, fill="both", padx=20, pady=10)

        # Βάση Δεδομένων
        ctk.CTkLabel(container, text="Database", font=("Arial", 16, "bold")).pack(anchor="w", pady=(10,5))
        f_path = ctk.CTkFrame(container, fg_color="transparent")
        f_path.pack(fill="x", pady=5)
        ctk.CTkLabel(f_path, text="file archer.db:", width=160, anchor="w").pack(side="left")
        self.ent_db_path = ctk.CTkEntry(f_path, width=500)
        self.ent_db_path.pack(side="left", padx=8)
        self.ent_db_path.insert(0, DB_PATH)
        ctk.CTkButton(f_path, text="📁 Browse", width=100, command=self.browse_db).pack(side="left")

        # Γενικές Ρυθμίσεις Client
        ctk.CTkLabel(container, text="General Settings Client", font=("Arial", 16, "bold")).pack(anchor="w", pady=(25,5))
        
        f1 = ctk.CTkFrame(container, fg_color="transparent"); f1.pack(fill="x", pady=4)
        ctk.CTkLabel(f1, text="Idle Threshold (δευτερόλεπτα):", width=260, anchor="w").pack(side="left")
        self.ent_idle = ctk.CTkEntry(f1, width=120); self.ent_idle.pack(side="left", padx=10)
        
        f2 = ctk.CTkFrame(container, fg_color="transparent"); f2.pack(fill="x", pady=4)
        ctk.CTkLabel(f2, text="Auto Email Report (HH:MM):", width=260, anchor="w").pack(side="left")
        self.ent_report_time = ctk.CTkEntry(f2, width=120); self.ent_report_time.pack(side="left", padx=10)

        f3 = ctk.CTkFrame(container, fg_color="transparent"); f3.pack(fill="x", pady=4)
        ctk.CTkLabel(f3, text="Menu options Global (,) - DEFAULT:", width=260, anchor="w").pack(side="left")
        self.ent_menu_options = ctk.CTkEntry(f3, width=500); self.ent_menu_options.pack(side="left", padx=10)

        # SMTP Email Reports
        ctk.CTkLabel(container, text="SMTP Email Reports", font=("Arial", 16, "bold")).pack(anchor="w", pady=(25,5))
        
        f4 = ctk.CTkFrame(container, fg_color="transparent"); f4.pack(fill="x", pady=4)
        ctk.CTkLabel(f4, text="SMTP Server:", width=160, anchor="w").pack(side="left")
        self.ent_smtp = ctk.CTkEntry(f4, width=400); self.ent_smtp.pack(side="left", padx=10)

        f5 = ctk.CTkFrame(container, fg_color="transparent"); f5.pack(fill="x", pady=4)
        ctk.CTkLabel(f5, text="Sender Email:", width=160, anchor="w").pack(side="left")
        self.ent_sender = ctk.CTkEntry(f4, width=400); self.ent_sender.pack(side="left", padx=10)

        f6 = ctk.CTkFrame(container, fg_color="transparent"); f6.pack(fill="x", pady=4)
        ctk.CTkLabel(f6, text="App Password:", width=160, anchor="w").pack(side="left")
        self.ent_pass = ctk.CTkEntry(f6, width=400, show="•"); self.ent_pass.pack(side="left", padx=10)

        # Email Ανά Τμήμα
        ctk.CTkLabel(container, text="Email per Department", font=("Arial", 16, "bold")).pack(anchor="w", pady=(25,8))
        self.dept_email_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.dept_email_frame.pack(fill="x", pady=5)

        # ΝΕΟ: Επιλογές Μενού Ανά Τμήμα
        ctk.CTkLabel(container, text="MENU per Department", font=("Arial", 16, "bold")).pack(anchor="w", pady=(25,8))
        self.dept_menu_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.dept_menu_frame.pack(fill="x", pady=5)

        # Κουμπιά
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(pady=30)
        ctk.CTkButton(btn_frame, text="💾 Save Settings", 
                      fg_color="#27ae60", height=45, font=("Arial", 14, "bold"),
                      command=self.save_all_settings).pack(side="left", padx=10)
        
        ctk.CTkButton(btn_frame, text="🔄 Apply Changes", 
                      fg_color="#34495e", height=45,
                      command=self.reload_settings).pack(side="left", padx=10)

        self.load_settings()
        self.refresh_dept_emails_ui()
        self.refresh_dept_menu_ui()   # ΝΕΟ

    # ====================== EMAIL ΑΝΑ ΤΜΗΜΑ ======================
    def refresh_dept_emails_ui(self):
        for widget in self.dept_email_frame.winfo_children():
            widget.destroy()
        try:
            conn = sqlite3.connect(DB_PATH)
            depts = pd.read_sql_query("""
                SELECT DISTINCT TRIM(department) as dept 
                FROM user_config 
                WHERE department IS NOT NULL AND TRIM(department) != '' 
                ORDER BY dept
            """, conn)['dept'].tolist()

            self.dept_email_entries = {}

            if not depts:
                ctk.CTkLabel(self.dept_email_frame, 
                            text="No Departments.\nAdd users on Departments manually on Live status.",
                            text_color="orange", justify="center").pack(pady=40)
            else:
                for d in depts:
                    f = ctk.CTkFrame(self.dept_email_frame, fg_color="transparent")
                    f.pack(fill="x", pady=4)
                    ctk.CTkLabel(f, text=f" {d}:", width=200, anchor="w", font=("Arial", 12, "bold")).pack(side="left")
                    e = ctk.CTkEntry(f, width=420, placeholder_text="email@company.com")
                    res = conn.execute("SELECT email FROM dept_emails WHERE TRIM(department)=?", (d,)).fetchone()
                    if res and res[0]:
                        e.insert(0, res[0])
                    e.pack(side="left", padx=15)
                    self.dept_email_entries[d] = e
            conn.close()
        except Exception as e:
            ctk.CTkLabel(self.dept_email_frame, text=f"Error: {str(e)}", text_color="red").pack(pady=20)

    # ====================== ΜΕΝΟΥ ΑΝΑ ΤΜΗΜΑ (ΝΕΟ) ======================
    def refresh_dept_menu_ui(self):
        for widget in self.dept_menu_frame.winfo_children():
            widget.destroy()
        try:
            conn = sqlite3.connect(DB_PATH)
            depts = pd.read_sql_query("""
                SELECT DISTINCT TRIM(department) as dept 
                FROM user_config 
                WHERE department IS NOT NULL AND TRIM(department) != '' 
                ORDER BY dept
            """, conn)['dept'].tolist()

            self.dept_menu_entries = {}

            if not depts:
                ctk.CTkLabel(self.dept_menu_frame, 
                            text="No Departments.\nAdd users on Departments manually on Live status.",
                            text_color="orange", justify="center").pack(pady=40)
            else:
                for d in depts:
                    f = ctk.CTkFrame(self.dept_menu_frame, fg_color="transparent")
                    f.pack(fill="x", pady=4)
                    ctk.CTkLabel(f, text=f" {d}:", width=200, anchor="w", font=("Arial", 12, "bold")).pack(side="left")
                    e = ctk.CTkEntry(f, width=420, placeholder_text="π.χ. ΒΛΑΒΗ, ΔΙΑΛΕΙΜΜΑ, RESTART")
                    res = conn.execute("SELECT menu_options FROM dept_menu_options WHERE TRIM(department)=?", (d,)).fetchone()
                    if res and res[0]:
                        e.insert(0, res[0])
                    e.pack(side="left", padx=15)
                    self.dept_menu_entries[d] = e
            conn.close()
        except Exception as e:
            ctk.CTkLabel(self.dept_menu_frame, text=f"Error: {str(e)}", text_color="red").pack(pady=20)

    def refresh_dept_list(self):
        if hasattr(self, 'dept_email_frame'):
            self.refresh_dept_emails_ui()
        if hasattr(self, 'dept_menu_frame'):
            self.refresh_dept_menu_ui()

    def reload_settings(self):
        self.load_settings()
        self.refresh_dept_emails_ui()
        self.refresh_dept_menu_ui()
        messagebox.showinfo("Restart Archer", "Settings loaded from DB")

    def save_all_settings(self):
        new_db_path = self.ent_db_path.get().strip()
        try:
            save_db_path_to_ini(new_db_path)
            conn = sqlite3.connect(new_db_path)
            settings = {
                'idle_threshold': self.ent_idle.get().strip(),
                'report_time': self.ent_report_time.get().strip(),
                'menu_options': self.ent_menu_options.get().strip(),
                'smtp_server': self.ent_smtp.get().strip(),
                'sender_email': self.ent_sender.get().strip(),
                'sender_pass': self.ent_pass.get().strip()
            }
            for key, value in settings.items():
                if value:
                    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            # Αποθήκευση email ανά τμήμα
            for dept, entry in self.dept_email_entries.items():
                email = entry.get().strip()
                if email:
                    conn.execute("INSERT OR REPLACE INTO dept_emails (department, email) VALUES (?, ?)", (dept, email))
                else:
                    conn.execute("DELETE FROM dept_emails WHERE department=?", (dept,))
            # ΝΕΟ: Αποθήκευση μενού ανά τμήμα
            for dept, entry in self.dept_menu_entries.items():
                menu = entry.get().strip()
                if menu:
                    conn.execute("INSERT OR REPLACE INTO dept_menu_options (department, menu_options) VALUES (?, ?)", (dept, menu))
                else:
                    conn.execute("DELETE FROM dept_menu_options WHERE department=?", (dept,))
            conn.commit()
            conn.close()
            messagebox.showinfo("✅ SUCCESS", "Settings Saved!")
            self.refresh_dept_emails_ui()
            self.refresh_dept_menu_ui()
        except Exception as e:
            messagebox.showerror("Error", f"Saving Error:\n{str(e)}")

    # ====================== ΥΠΟΛΟΙΠΕΣ ΜΕΘΟΔΟΙ ======================
    def browse_db(self):
        file = filedialog.askopenfilename(title="Επιλέξτε archer.db", filetypes=[("SQLite Database", "*.db")])
        if file:
            self.ent_db_path.delete(0, 'end')
            self.ent_db_path.insert(0, file)

    def load_settings(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            settings = dict(conn.execute("SELECT key, value FROM settings").fetchall())
            conn.close()
            self.ent_idle.delete(0, 'end')
            self.ent_idle.insert(0, settings.get('idle_threshold', '300'))
            self.ent_report_time.delete(0, 'end')
            self.ent_report_time.insert(0, settings.get('report_time', '16:00'))
            self.ent_menu_options.delete(0, 'end')
            self.ent_menu_options.insert(0, settings.get('menu_options', 'ΒΛΑΒΗ, ΔΙΑΛΕΙΜΜΑ, RESTART, ΤΕΛΟΣ'))
            self.ent_smtp.delete(0, 'end')
            self.ent_smtp.insert(0, settings.get('smtp_server', 'smtp.gmail.com'))
            self.ent_sender.delete(0, 'end')
            self.ent_sender.insert(0, settings.get('sender_email', ''))
            self.ent_pass.delete(0, 'end')
            self.ent_pass.insert(0, settings.get('sender_pass', ''))
        except: pass

    def confirm_delete_user(self):
        u = self.ent_u.get().strip().lower()
        if not u:
            messagebox.showwarning("Alert", "Chooce a user.")
            return
        if messagebox.askyesno("Confirmation", f"Do you really want to delete user\n{u.upper()};\n\nCant be reveresed!"):
            try:
                conn = sqlite3.connect(DB_PATH)
                for table in ["user_config", "heartbeats", "events", "admin_messages", "user_messages"]:
                    conn.execute(f"DELETE FROM {table} WHERE username = ?", (u,))
                conn.commit()
                conn.close()
                messagebox.showinfo("ok", f"User {u} deleted.")
                self.refresh_data()
                self.refresh_dept_list()
                for e in [self.ent_dept, self.ent_u, self.ent_ip, self.ent_iptype, self.ent_phone, self.ent_anydesk]:
                    e.delete(0, 'end')
            except Exception as ex:
                messagebox.showerror("Error", str(ex))

    def save_user(self):
        u = self.ent_u.get().lower().strip()
        if not u:
            messagebox.showwarning("Alert", "No username.")
            return
        
        # Παίρνουμε τα τρέχοντα δεδομένα του χρήστη από τη βάση (αν υπάρχει)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT hostname, user_id FROM user_config WHERE username = ?", (u,))
        existing = cursor.fetchone()
        
        if existing:
            # Κρατάμε το υπάρχον hostname, δεν το αλλάζουμε
            hostname = existing[0]
            # Αν υπάρχει user_id, το κρατάμε, αλλιώς το δημιουργούμε
            if existing[1]:
                user_id = existing[1]
            else:
                user_id = f"{u}@{hostname}" if hostname else f"{u}@UNKNOWN"
        else:
            # Νέος χρήστης: παίρνουμε hostname από τη φόρμα ή από την IP ή βάζουμε UNKNOWN
            hostname = "UNKNOWN"
            user_id = f"{u}@{hostname}"
        
        conn.execute("""
            INSERT OR REPLACE INTO user_config 
            (username, hostname, user_id, ip_address, department, anydesk_id, phone)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (u, hostname, user_id,
              self.ent_ip.get().strip(), 
              self.ent_dept.get().upper().strip(),
              self.ent_anydesk.get().strip(), 
              self.ent_phone.get().strip()))
        conn.commit()
        conn.close()
        
        messagebox.showinfo("OK", "SAVED")
        self.refresh_data()
        self.refresh_dept_list()

    def connect_anydesk(self):
        import shutil
        possible = [r"C:\Program Files (x86)\AnyDesk\AnyDesk.exe", r"C:\Program Files\AnyDesk\AnyDesk.exe", shutil.which("anydesk.exe")]
        exe_path = next((p for p in possible if p and os.path.exists(p)), None)
        target = self.ent_anydesk.get().strip() or self.ent_ip.get().strip()
        if target and target != "-" and exe_path:
            subprocess.Popen([exe_path, target])

    def send_instant_msg(self):
        u, m = self.ent_u.get().strip(), self.msg_text.get().strip()
        if u and m:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("INSERT INTO user_messages (username, message) VALUES (?, ?)", (u, m))
            conn.commit(); conn.close()
            self.msg_text.delete(0, 'end')
            messagebox.showinfo("OK", "Sent")

    def clear_replies(self):
        if messagebox.askyesno("confirmation", "Would you like to delete all the message history?"):
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DELETE FROM admin_messages")
            conn.commit(); conn.close()
            self.refresh_data()

    def filter_logs_changed(self, choice): self.logs_dept_filter = choice; self.refresh_data()
    def filter_live_changed(self, choice): self.live_dept_filter = choice; self.refresh_data()

    def ping_machine(self, ip):
        if not ip or ip == "-": return False
        try:
            res = subprocess.run(['ping', '-n', '1', '-w', '800', ip], capture_output=True, text=True)
            return res.returncode == 0
        except: return False

    def auto_ping_worker(self):
        while True:
            self.manual_ping(quiet=True)
            time.sleep(120)

    def manual_ping(self, quiet=False):
        if not quiet: self.add_to_log("Ping process started...")
        def run():
            try:
                conn = sqlite3.connect(DB_PATH)
                ips = [row[0] for row in conn.execute("SELECT ip_address FROM user_config").fetchall() if row[0]]
                conn.close()
                for ip in ips:
                    self.ping_results[ip] = self.ping_machine(ip)
                self.root.after(0, self.refresh_data)
                if not quiet: self.root.after(0, lambda: self.add_to_log("Ping process completed.", "SUCCESS"))
            except: pass
        threading.Thread(target=run, daemon=True).start()

    def open_emoji_picker(self):
        self.msg_text.focus_set()
        ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xBE, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0xBE, 0, 2, 0)
        ctypes.windll.user32.keybd_event(0x5B, 0, 2, 0)

    def add_to_log(self, message, level="INFO"):
        self.log_area.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = "ℹ️"
        if level == "ALERT": prefix = "⚠️ [DISCONNECT]"
        elif level == "SUCCESS": prefix = "✅ [CONNECTED]"
        self.log_area.insert("1.0", f"[{ts}] {prefix} {message}\n")
        self.log_area.configure(state="disabled")

    def create_tree(self, parent, cols, heads):
        f = ctk.CTkFrame(parent); f.pack(expand=True, fill="both", side="left", padx=2, pady=2)
        t = ttk.Treeview(f, columns=cols, show='headings'); t.pack(side="left", expand=True, fill="both")
        for c, h in zip(cols, heads): t.heading(c, text=h); t.column(c, anchor="center")
        t.bind("<<TreeviewSelect>>", self.on_tree_select)
        return t

    def update_search(self, event):
        self.search_query = self.ent_search.get().lower()
        self.refresh_data()

    def show_custom_alert(self, user, text):
        alert = ctk.CTkToplevel(self.root)
        alert.title(f"Chat with {user}"); alert.geometry("500x550"); alert.attributes("-topmost", True)
        alert.configure(fg_color="#1a1a1a")
        ctk.CTkLabel(alert, text=f"💬 CHAT: {user.upper()}", font=("Segoe UI Emoji", 16, "bold"), text_color="#3498db").pack(pady=15)
        history_box = ctk.CTkTextbox(alert, width=460, height=200, font=("Segoe UI Emoji", 11))
        history_box.pack(pady=5, padx=20)
        try:
            conn = sqlite3.connect(DB_PATH)
            query = """SELECT 'ΕΓΩ' as s, message, timestamp FROM user_messages WHERE username=? 
                       UNION ALL SELECT ? as s, message, timestamp FROM admin_messages WHERE username=? ORDER BY timestamp DESC LIMIT 6"""
            history = pd.read_sql_query(query, conn, params=(user, user, user))
            conn.close()
            for _, row in history[::-1].iterrows():
                history_box.insert("end", f"[{row['s'].upper()}]: {row['message']}\n")
            history_box.insert("end", f"--- New Message ---\n[{user.upper()}]: {text}\n")
            history_box.see("end")
        except: pass
        history_box.configure(state="disabled")
        reply_ent = ctk.CTkEntry(alert, width=400, placeholder_text="Reply...", font=("Segoe UI Emoji", 12))
        reply_ent.pack(pady=5, padx=20); reply_ent.focus()
        def send_reply():
            if reply_ent.get().strip():
                conn = sqlite3.connect(DB_PATH)
                conn.execute("INSERT INTO user_messages (username, message) VALUES (?, ?)", (user, reply_ent.get().strip()))
                conn.commit(); conn.close(); alert.destroy()
        btn_f = ctk.CTkFrame(alert, fg_color="transparent"); btn_f.pack(pady=20)
        ctk.CTkButton(btn_f, text="Send", width=140, fg_color="#27ae60", command=send_reply).pack(side="left", padx=10)
        alert.bind('<Return>', lambda e: send_reply())

    def refresh_data(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, message FROM admin_messages WHERE id > ? ORDER BY id ASC", (self.last_msg_id,))
            new_msgs = cursor.fetchall()
            for m_id, user, text in new_msgs:
                self.last_msg_id = m_id
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
                self.show_custom_alert(user, text)

            depts_df = pd.read_sql_query("SELECT DISTINCT department FROM user_config", conn)
            depts = ["ALL"] + [d for d in depts_df['department'].tolist() if d]
            self.combo_logs_dept.configure(values=depts)
            self.combo_live_dept.configure(values=depts)

            live_q = """
                SELECT user_id, username, hostname, ip_address, ip_type, department, anydesk_id, phone 
                FROM user_config
            """
            live_df = pd.read_sql_query(live_q, conn)

            for i in self.tree_status.get_children(): self.tree_status.delete(i)
            currently_online = set()
            for _, u in live_df.iterrows():
                dept = str(u['department']).upper() if u['department'] else "UNKNOWN"
                user = str(u['username']).lower()
                uid  = u['user_id'] or f"{user}@UNKNOWN"
                host = u['hostname'] or "UNKNOWN"
                ip   = u['ip_address'] or "-"
                ipt  = u['ip_type'] or "Unknown"

                if self.live_dept_filter != "ΟΛΑ" and dept != self.live_dept_filter: continue
                if self.search_query and not any(self.search_query in str(v).lower() for v in [uid, user, host, ip, dept, ipt]):
                    continue
                
                cursor.execute("SELECT last_seen FROM heartbeats WHERE username=? AND last_seen > datetime('now','-40 seconds')", (user,))
                is_archer_on = cursor.fetchone()
                
                is_pc_on = self.ping_results.get(ip, False)

                if is_archer_on:
                    st, tag = ("✅ ONLINE", "online")
                    currently_online.add(user)
                elif is_pc_on:
                    st, tag = ("🟠 PC ON (Archer OFF)", "archer_off")
                else:
                    st, tag = ("❌ OFFLINE", "offline")

                self.tree_status.insert("", "end", values=(uid, user, host, ip, ipt, dept, 
                                                          u['anydesk_id'] or "-", 
                                                          u['phone'] or "-", st), tags=(tag,))

            dropped = self.previously_online - currently_online
            for u_off in dropped:
                self.add_to_log(f"User {u_off.upper()} disconnected!", "ALERT")
                winsound.Beep(500, 200)
            joined = currently_online - self.previously_online
            for u_on in joined:
                if self.previously_online: self.add_to_log(f"User {u_on.upper()} connected.", "SUCCESS")
            self.previously_online = currently_online

            l_q = """
                SELECT e.username, e.event_type, e.start_time, e.end_time 
                FROM events e LEFT JOIN user_config u ON e.username = u.username 
                WHERE e.is_sent=0
            """
            if self.logs_dept_filter != "ΟΛΑ":
                l_q += f" AND u.department='{self.logs_dept_filter}'"
            df_l = pd.read_sql_query(l_q + " ORDER BY e.start_time DESC", conn)
            for i in self.tree_logs.get_children(): self.tree_logs.delete(i)
            for _, r in df_l.iterrows():
                dur = "-"
                if r['end_time']:
                    try:
                        t1 = datetime.strptime(r['start_time'], "%Y-%m-%d %H:%M:%S")
                        t2 = datetime.strptime(r['end_time'], "%Y-%m-%d %H:%M:%S")
                        dur = round((t2 - t1).total_seconds() / 60, 1)
                    except: pass
                self.tree_logs.insert("", "end", values=(r['username'], r['event_type'], r['start_time'], r['end_time'] or "-", dur))

            df_r = pd.read_sql_query("SELECT timestamp, username, message FROM admin_messages ORDER BY timestamp DESC", conn)
            for i in self.tree_replies.get_children(): self.tree_replies.delete(i)
            for _, r in df_r.iterrows():
                self.tree_replies.insert("", "end", values=list(r))
            
            conn.close()
        except Exception as e:
            print(f"Refresh Error: {e}")
        self.root.after(12000, self.refresh_data)

    def on_tree_select(self, event):
        sel = self.tree_status.selection()
        if not sel:
            return

        item = self.tree_status.item(sel[0])['values']
        # item = (user_id, username, hostname, ip, ipt, dept, anydesk, phone, status)
        
        self.ent_dept.delete(0, 'end')
        self.ent_dept.insert(0, item[5] if item[5] != "ΑΓΝΩΣΤΟ" else "")

        self.ent_u.delete(0, 'end')
        self.ent_u.insert(0, item[1])  # username

        self.ent_ip.delete(0, 'end')
        self.ent_ip.insert(0, item[3])

        self.ent_iptype.configure(state="normal")
        self.ent_iptype.delete(0, 'end')
        self.ent_iptype.insert(0, item[4])
        self.ent_iptype.configure(state="readonly")

        self.ent_phone.delete(0, 'end')
        self.ent_phone.insert(0, item[7] if item[7] != "-" else "")

        self.ent_anydesk.delete(0, 'end')
        self.ent_anydesk.insert(0, item[6] if item[6] != "-" else "")

    def scheduler_worker(self):
        sent_today = False
        while True:
            now = datetime.now().strftime("%H:%M")
            try:
                conn = sqlite3.connect(DB_PATH)
                s = dict(conn.execute("SELECT key, value FROM settings").fetchall())
                conn.close()
                if now == s.get('report_time') and not sent_today:
                    self.send_split_reports(s)
                    sent_today = True
                if now == "00:00": sent_today = False
            except: pass
            time.sleep(45)

    def confirm_clear_unsent_events(self):
        if messagebox.askyesno("Confirmation", "You want to delete all the pending events;\n\nReport wont be sent."):
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.execute("DELETE FROM events WHERE is_sent = 0")
                conn.commit()
                conn.close()
                messagebox.showinfo("OK", "Pending events deleted.")
                self.refresh_data()
            except Exception as ex:
                messagebox.showerror("Error", str(ex))

    def send_split_reports(self, s):
        try:
            conn = sqlite3.connect(DB_PATH)
            df = pd.read_sql_query("""
                SELECT e.username, e.event_type, e.start_time, e.end_time, 
                       IFNULL(u.department, 'UNKNOWN') as department 
                FROM events e LEFT JOIN user_config u ON e.username = u.username 
                WHERE e.is_sent=0
            """, conn)
            if df.empty: return
            dept_map = dict(conn.execute("SELECT department, email FROM dept_emails").fetchall())
            server = smtplib.SMTP(s['smtp_server'], 587)
            server.starttls()
            server.login(s['sender_email'], s['sender_pass'])
            for dept in df['department'].unique():
                dest = dept_map.get(dept)
                if dest:
                    msg = MIMEMultipart()
                    msg['Subject'] = f"Archer Report - {dept} - {datetime.now().strftime('%d/%m/%Y')}"
                    html = f"<h3>Daily Activity Report: {dept}</h3>" + df[df['department']==dept].to_html(index=False)
                    msg.attach(MIMEText(html, 'html'))
                    server.sendmail(s['sender_email'], dest, msg.as_string())
            server.quit()
            conn.execute("UPDATE events SET is_sent=1 WHERE is_sent=0")
            conn.commit()
            conn.close()
        except: pass

if __name__ == "__main__":
    import traceback
    
    try:
        root = ctk.CTk()
        app = ArcherAdmin(root)
        root.mainloop()
    except Exception:
        print("\n" + "="*50)
        print("🔴 critical error:")
        print("="*50)
        traceback.print_exc()
        print("="*50)
        input("\nΠάτα Enter για να κλείσει το παράθυρο...")
    finally:
        try:
            if os.path.exists(LOCK_FILE_ADMIN):
                os.remove(LOCK_FILE_ADMIN)
        except:
            pass