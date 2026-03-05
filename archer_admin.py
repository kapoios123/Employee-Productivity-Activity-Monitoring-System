import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog
import sqlite3, pandas as pd, smtplib, threading, time, os, sys, winsound, subprocess, configparser, ctypes
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import socket
import tkinter as tk # Χρειάζεται για το αρχικό popup


# --- CONFIGURATION MANAGER ---

def get_db_path():
    config = configparser.ConfigParser()
    # Το config.ini θα αποθηκεύεται στον ίδιο φάκελο με το .py αρχείο
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
    
    db_path = None

    # 1. Προσπάθεια ανάγνωσης από το αρχείο ρυθμίσεων
    if os.path.exists(config_file):
        try:
            config.read(config_file, encoding='utf-8')
            db_path = config.get('SETTINGS', 'db_path', fallback=None)
        except:
            db_path = None

    # 2. Αν δεν υπάρχει στο config ή το αρχείο της βάσης δεν υπάρχει στον δίσκο
    if not db_path or not os.path.exists(db_path):
        root_temp = tk.Tk()
        root_temp.withdraw()
        
        messagebox.showinfo("Σύνδεση Βάσης", "Δεν βρέθηκε η βάση δεδομένων archer.db.\nΠαρακαλώ επιλέξτε το αρχείο.")
        
        selected_path = filedialog.askopenfilename(
            title="Επιλογή archer.db",
            filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")]
        )
        
        root_temp.destroy()

        if selected_path:
            save_db_path_to_ini(selected_path)
            return selected_path
        else:
            sys.exit() # Κλείσιμο αν ο χρήστης δεν επιλέξει τίποτα
            
    return db_path

def save_db_path_to_ini(new_path):
    config = configparser.ConfigParser()
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
    config['SETTINGS'] = {'db_path': new_path}
    with open(config_file, 'w', encoding='utf-8') as configfile:
        config.write(configfile)

# --- ΕΚΤΕΛΕΣΗ (ΕΞΩ ΑΠΟ ΤΙΣ ΣΥΝΑΡΤΗΣΕΙΣ) ---

# 1. Πρώτα βρίσκουμε το path της βάσης
DB_PATH = get_db_path()

# 2. Ορίζουμε το LOCK FILE (Αυτό έλειπε και σου χτύπαγε error)
LOCK_FILE_ADMIN = os.path.join(os.environ.get('TEMP', ''), 'archer_admin.lock')

# 3. Ρυθμίσεις εμφάνισης
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Μετά ξεκινάει η class ArcherAdmin...

class ArcherAdmin:
    def __init__(self, root):
        self.check_single_instance()
        self.init_db_extensions()
        self.root = root
        self.root.title("Archer Control Panel Pro - Master Edition v4.0")
        self.root.geometry("1850x900")
        
        self.logs_dept_filter = "ΟΛΑ"
        self.live_dept_filter = "ΟΛΑ"
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
            defaults = [
                ('idle_threshold', '300'), ('report_time', '16:00'),
                ('menu_options', 'ΒΛΑΒΗ, ΔΙΑΛΕΙΜΜΑ, RESTART, ΤΕΛΟΣ'),
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
        ctk.CTkLabel(l_tool, text="Φίλτρο Τμήματος:").pack(side="left", padx=10)
        self.combo_logs_dept = ctk.CTkOptionMenu(l_tool, values=["ΟΛΑ"], command=self.filter_logs_changed)
        self.combo_logs_dept.pack(side="left", padx=5)
        ctk.CTkButton(l_tool, text="🗑️ ΔΙΑΓΡΑΦΗ ΕΚΚΡΕΜΩΝ", fg_color="#c0392b", command=self.confirm_clear_unsent_events).pack(side="right", padx=10)
        self.tree_logs = self.create_tree(f_logs, ("u", "t", "s", "e", "d"), ("ΧΡΗΣΤΗΣ", "ΤΥΠΟΣ", "ΕΝΑΡΞΗ", "ΛΗΞΗ", "Min"))

        # TAB 2 LIVE STATUS
        f_status_main = ctk.CTkFrame(self.tab_users)
        f_status_main.pack(expand=True, fill="both", padx=10, pady=10)
        s_tool = ctk.CTkFrame(f_status_main, height=60)
        s_tool.pack(side="top", fill="x", padx=5, pady=5)
        ctk.CTkLabel(s_tool, text="Τμήμα:").pack(side="left", padx=5)
        self.combo_live_dept = ctk.CTkOptionMenu(s_tool, values=["ΟΛΑ"], command=self.filter_live_changed)
        self.combo_live_dept.pack(side="left", padx=5)
        self.ent_search = ctk.CTkEntry(s_tool, placeholder_text="🔍 Αναζήτηση...", width=200)
        self.ent_search.pack(side="left", padx=20)
        self.ent_search.bind("<KeyRelease>", self.update_search)
        ctk.CTkButton(s_tool, text="📡 PING ALL", fg_color="#8e44ad", width=120, command=self.manual_ping).pack(side="right", padx=10)

        mid_section = ctk.CTkFrame(f_status_main, fg_color="transparent")
        mid_section.pack(expand=True, fill="both")
        self.tree_status = self.create_tree(mid_section, 
                                            ("uid", "u", "h", "i", "t", "d", "any", "p", "s"),
                                            ("User@Host", "Username", "Hostname", "IP", "ΤΥΠΟΣ IP", "ΤΜΗΜΑ", "ANYDESK ID", "ΤΗΛ", "STATUS"))

        self.tree_status.tag_configure('online', foreground='#2ecc71')
        self.tree_status.tag_configure('archer_off', foreground='#f39c12')
        self.tree_status.tag_configure('offline', foreground='#e74c3c')

        self.form = ctk.CTkFrame(mid_section, width=280)
        self.form.pack(side="right", fill="y", padx=10, pady=10)
        ctk.CTkLabel(self.form, text="Στοιχεία Χρήστη", font=("Arial", 16, "bold")).pack(pady=10)
        self.ent_dept = ctk.CTkEntry(self.form, placeholder_text="Τμήμα"); self.ent_dept.pack(pady=5, padx=10, fill="x")
        self.ent_u = ctk.CTkEntry(self.form, placeholder_text="Username"); self.ent_u.pack(pady=5, padx=10, fill="x")
        self.ent_ip = ctk.CTkEntry(self.form, placeholder_text="IP Address"); self.ent_ip.pack(pady=5, padx=10, fill="x")
        self.ent_iptype = ctk.CTkEntry(self.form, placeholder_text="Τύπος IP", state="readonly"); self.ent_iptype.pack(pady=5, padx=10, fill="x")
        self.ent_phone = ctk.CTkEntry(self.form, placeholder_text="Εσωτ. Τηλέφωνο"); self.ent_phone.pack(pady=5, padx=10, fill="x")
        self.ent_anydesk = ctk.CTkEntry(self.form, placeholder_text="AnyDesk ID"); self.ent_anydesk.pack(pady=5, padx=10, fill="x")

        btn_frame = ctk.CTkFrame(self.form, fg_color="transparent")
        btn_frame.pack(pady=10, padx=10, fill="x")
        ctk.CTkButton(btn_frame, text="💾 ΑΠΟΘΗΚΕΥΣΗ", fg_color="#27ae60", command=self.save_user).pack(side="left", padx=5, expand=True, fill="x")
        ctk.CTkButton(btn_frame, text="🗑️ ΔΙΑΓΡΑΦΗ ΧΡΗΣΤΗ", fg_color="#c0392b", command=self.confirm_delete_user).pack(side="left", padx=5, expand=True, fill="x")
        ctk.CTkButton(self.form, text="⚡ ΣΥΝΔΕΣΗ ANYDESK", fg_color="#c0392b", command=self.connect_anydesk).pack(pady=5, padx=10, fill="x")

        self.msg_text = ctk.CTkEntry(self.form, placeholder_text="Instant Msg...", font=("Segoe UI Emoji", 12))
        self.msg_text.pack(pady=(20, 5), padx=10, fill="x")
        ctk.CTkButton(self.form, text="😊 Emoji (Win+.)", fg_color="#34495e", height=25, command=self.open_emoji_picker).pack(padx=10, fill="x")
        ctk.CTkButton(self.form, text="ΑΠΟΣΤΟΛΗ", fg_color="#1f538d", command=self.send_instant_msg).pack(pady=10, padx=10, fill="x")

        self.log_frame = ctk.CTkFrame(f_status_main, height=180)
        self.log_frame.pack(side="bottom", fill="x", padx=5, pady=5)
        self.log_area = ctk.CTkTextbox(self.log_frame, height=140, font=("Consolas", 11), fg_color="#000000")
        self.log_area.pack(expand=True, fill="both", padx=10, pady=5)
        self.log_area.configure(state="disabled")

        # TAB 3 ΑΠΑΝΤΗΣΕΙΣ
        f_replies = ctk.CTkFrame(self.tab_replies)
        f_replies.pack(expand=True, fill="both", padx=10, pady=10)
        self.tree_replies = self.create_tree(f_replies, ("t", "u", "m"), ("ΩΡΑ", "ΧΡΗΣΤΗΣ", "ΜΗΝΥΜΑ"))
        ctk.CTkButton(f_replies, text="ΚΑΘΑΡΙΣΜΟΣ ΙΣΤΟΡΙΚΟΥ", fg_color="#c0392b", command=self.clear_replies).pack(pady=10)
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
        ctk.CTkLabel(container, text="Βάση Δεδομένων", font=("Arial", 16, "bold")).pack(anchor="w", pady=(10,5))
        f_path = ctk.CTkFrame(container, fg_color="transparent")
        f_path.pack(fill="x", pady=5)
        ctk.CTkLabel(f_path, text="Αρχείο archer.db:", width=160, anchor="w").pack(side="left")
        self.ent_db_path = ctk.CTkEntry(f_path, width=500)
        self.ent_db_path.pack(side="left", padx=8)
        self.ent_db_path.insert(0, DB_PATH)
        ctk.CTkButton(f_path, text="📁 Browse", width=100, command=self.browse_db).pack(side="left")

        # Γενικές Ρυθμίσεις Client
        ctk.CTkLabel(container, text="Γενικές Ρυθμίσεις Client", font=("Arial", 16, "bold")).pack(anchor="w", pady=(25,5))
        
        f1 = ctk.CTkFrame(container, fg_color="transparent"); f1.pack(fill="x", pady=4)
        ctk.CTkLabel(f1, text="Idle Threshold (δευτερόλεπτα):", width=260, anchor="w").pack(side="left")
        self.ent_idle = ctk.CTkEntry(f1, width=120); self.ent_idle.pack(side="left", padx=10)
        
        f2 = ctk.CTkFrame(container, fg_color="transparent"); f2.pack(fill="x", pady=4)
        ctk.CTkLabel(f2, text="Ώρα Αυτόματου Report (HH:MM):", width=260, anchor="w").pack(side="left")
        self.ent_report_time = ctk.CTkEntry(f2, width=120); self.ent_report_time.pack(side="left", padx=10)

        f3 = ctk.CTkFrame(container, fg_color="transparent"); f3.pack(fill="x", pady=4)
        ctk.CTkLabel(f3, text="Επιλογές Μενού Client (κόμμα):", width=260, anchor="w").pack(side="left")
        self.ent_menu_options = ctk.CTkEntry(f3, width=500); self.ent_menu_options.pack(side="left", padx=10)

        # SMTP Email Reports
        ctk.CTkLabel(container, text="SMTP Email Reports", font=("Arial", 16, "bold")).pack(anchor="w", pady=(25,5))
        
        f4 = ctk.CTkFrame(container, fg_color="transparent"); f4.pack(fill="x", pady=4)
        ctk.CTkLabel(f4, text="SMTP Server:", width=160, anchor="w").pack(side="left")
        self.ent_smtp = ctk.CTkEntry(f4, width=400); self.ent_smtp.pack(side="left", padx=10)

        f5 = ctk.CTkFrame(container, fg_color="transparent"); f5.pack(fill="x", pady=4)
        ctk.CTkLabel(f5, text="Sender Email:", width=160, anchor="w").pack(side="left")
        self.ent_sender = ctk.CTkEntry(f5, width=400); self.ent_sender.pack(side="left", padx=10)

        f6 = ctk.CTkFrame(container, fg_color="transparent"); f6.pack(fill="x", pady=4)
        ctk.CTkLabel(f6, text="App Password:", width=160, anchor="w").pack(side="left")
        self.ent_pass = ctk.CTkEntry(f6, width=400, show="•"); self.ent_pass.pack(side="left", padx=10)

        # Email Ανά Τμήμα
        ctk.CTkLabel(container, text="Email Ανά Τμήμα", font=("Arial", 16, "bold")).pack(anchor="w", pady=(25,8))
        self.dept_email_frame = ctk.CTkFrame(container, fg_color="transparent")
        self.dept_email_frame.pack(fill="x", pady=5)

        # Κουμπιά
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(pady=30)
        ctk.CTkButton(btn_frame, text="💾 ΑΠΟΘΗΚΕΥΣΗ ΡΥΘΜΙΣΕΩΝ", 
                      fg_color="#27ae60", height=45, font=("Arial", 14, "bold"),
                      command=self.save_all_settings).pack(side="left", padx=10)
        
        ctk.CTkButton(btn_frame, text="🔄 Επαναφόρτωση Ρυθμίσεων", 
                      fg_color="#34495e", height=45,
                      command=self.reload_settings).pack(side="left", padx=10)

        self.load_settings()
        self.refresh_dept_emails_ui()

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
                            text="Δεν υπάρχουν ακόμα τμήματα.\nΠροσθέστε χρήστες με τμήμα από το Live Status.",
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
            ctk.CTkLabel(self.dept_email_frame, text=f"Σφάλμα: {str(e)}", text_color="red").pack(pady=20)

    def refresh_dept_list(self):
        if hasattr(self, 'dept_email_frame'):
            self.refresh_dept_emails_ui()

    def reload_settings(self):
        self.load_settings()
        self.refresh_dept_emails_ui()
        messagebox.showinfo("Επαναφόρτωση", "Οι ρυθμίσεις φορτώθηκαν ξανά από τη βάση.")

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
            for dept, entry in self.dept_email_entries.items():
                email = entry.get().strip()
                if email:
                    conn.execute("INSERT OR REPLACE INTO dept_emails (department, email) VALUES (?, ?)", (dept, email))
            conn.commit()
            conn.close()
            messagebox.showinfo("✅ Επιτυχία", "Οι ρυθμίσεις αποθηκεύτηκαν!")
            self.refresh_dept_emails_ui()
        except Exception as e:
            messagebox.showerror("Σφάλμα", f"Αποτυχία αποθήκευσης:\n{str(e)}")

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
            self.ent_idle.insert(0, settings.get('idle_threshold', '300'))
            self.ent_report_time.insert(0, settings.get('report_time', '16:00'))
            self.ent_menu_options.insert(0, settings.get('menu_options', 'ΒΛΑΒΗ, ΔΙΑΛΕΙΜΜΑ, RESTART, ΤΕΛΟΣ'))
            self.ent_smtp.insert(0, settings.get('smtp_server', 'smtp.gmail.com'))
            self.ent_sender.insert(0, settings.get('sender_email', ''))
            self.ent_pass.insert(0, settings.get('sender_pass', ''))
        except: pass

    def confirm_delete_user(self):
        u = self.ent_u.get().strip().lower()
        if not u:
            messagebox.showwarning("Προσοχή", "Δεν είναι επιλεγμένος χρήστης.")
            return
        if messagebox.askyesno("ΕΠΙΒΕΒΑΙΩΣΗ ΔΙΑΓΡΑΦΗΣ", f"Θέλετε σίγουρα να ΔΙΑΓΡΑΨΕΤΕ τον χρήστη\n{u.upper()};\n\nΗ ενέργεια είναι μη αναστρέψιμη!"):
            try:
                conn = sqlite3.connect(DB_PATH)
                for table in ["user_config", "heartbeats", "events", "admin_messages", "user_messages"]:
                    conn.execute(f"DELETE FROM {table} WHERE username = ?", (u,))
                conn.commit()
                conn.close()
                messagebox.showinfo("OK", f"Ο χρήστης {u} διαγράφηκε πλήρως.")
                self.refresh_data()
                self.refresh_dept_list()
                for e in [self.ent_dept, self.ent_u, self.ent_ip, self.ent_iptype, self.ent_phone, self.ent_anydesk]:
                    e.delete(0, 'end')
            except Exception as ex:
                messagebox.showerror("Σφάλμα", str(ex))

    def save_user(self):
        u = self.ent_u.get().lower().strip()
        if not u:
            messagebox.showwarning("Προσοχή", "Δεν δόθηκε username.")
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
            # Στην πραγματικότητα, το hostname θα πρέπει να έρχεται από τον client, αλλά εδώ δεν έχουμε πρόσβαση.
            # Για νέο χρήστη, μπορούμε να βάλουμε προσωρινά "UNKNOWN" ή να το αφήσουμε κενό.
            hostname = "UNKNOWN"  # ή μπορείς να το αφήσεις κενό
            user_id = f"{u}@{hostname}"
        
        # Τώρα κάνουμε INSERT OR REPLACE με τα σωστά δεδομένα
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
        
        messagebox.showinfo("OK", "Αποθηκεύτηκε")
        self.refresh_data()
        self.refresh_dept_list()

    def connect_anydesk(self):
        import shutil
        possible = [r"C:\Program Files (x86)\AnyDesk\AnyDesk.exe", r"C:\Program Files\AnyDesk\AnyDesk.exe", shutil.which("anydesk.exe")]
        exe_path = next((p for p in possible if p and os.path.exists(p)), None)
        
        # Παίρνουμε την τιμή και καθαρίζουμε τυχόν NaN ή κενά
        target = self.ent_anydesk.get().strip()
        if not target or target.lower() == "nan" or target == "-":
            target = self.ent_ip.get().strip() # Δοκιμή με την IP αν το AnyDesk ID λείπει

        if target and target.lower() != "nan" and target != "-" and exe_path:
            subprocess.Popen([exe_path, target])
        else:
            messagebox.showwarning("AnyDesk Error", "Δεν βρέθηκε έγκυρο ID ή IP για σύνδεση.")

    def send_instant_msg(self):
        u, m = self.ent_u.get().strip(), self.msg_text.get().strip()
        if u and m:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("INSERT INTO user_messages (username, message) VALUES (?, ?)", (u, m))
            conn.commit(); conn.close()
            self.msg_text.delete(0, 'end')
            messagebox.showinfo("OK", "Εστάλη")

    def clear_replies(self):
        if messagebox.askyesno("Επιβεβαίωση", "Θέλετε να διαγράψετε όλο το ιστορικό απαντήσεων;"):
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
        if not quiet: self.add_to_log("Έναρξη Ping σε όλα τα μηχανήματα...")
        def run():
            try:
                conn = sqlite3.connect(DB_PATH)
                ips = [row[0] for row in conn.execute("SELECT ip_address FROM user_config").fetchall() if row[0]]
                conn.close()
                for ip in ips:
                    self.ping_results[ip] = self.ping_machine(ip)
                self.root.after(0, self.refresh_data)
                if not quiet: self.root.after(0, lambda: self.add_to_log("Το Ping ολοκληρώθηκε.", "SUCCESS"))
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
        alert.title(f"Συνομιλία με {user}"); alert.geometry("500x550"); alert.attributes("-topmost", True)
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
            history_box.insert("end", f"--- ΝΕΟ ΜΗΝΥΜΑ ---\n[{user.upper()}]: {text}\n")
            history_box.see("end")
        except: pass
        history_box.configure(state="disabled")
        reply_ent = ctk.CTkEntry(alert, width=400, placeholder_text="Απάντηση...", font=("Segoe UI Emoji", 12))
        reply_ent.pack(pady=5, padx=20); reply_ent.focus()
        def send_reply():
            if reply_ent.get().strip():
                conn = sqlite3.connect(DB_PATH)
                conn.execute("INSERT INTO user_messages (username, message) VALUES (?, ?)", (user, reply_ent.get().strip()))
                conn.commit(); conn.close(); alert.destroy()
        btn_f = ctk.CTkFrame(alert, fg_color="transparent"); btn_f.pack(pady=20)
        ctk.CTkButton(btn_f, text="ΑΠΟΣΤΟΛΗ", width=140, fg_color="#27ae60", command=send_reply).pack(side="left", padx=10)
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
            depts = ["ΟΛΑ"] + [d for d in depts_df['department'].tolist() if d]
            self.combo_logs_dept.configure(values=depts)
            self.combo_live_dept.configure(values=depts)

            live_q = """
                SELECT user_id, username, hostname, ip_address, ip_type, department, anydesk_id, phone 
                FROM user_config
            """
            # Διάβασμα από τη βάση ΚΑΙ μετά fillna
            live_df = pd.read_sql_query(live_q, conn) 
            live_df = live_df.fillna("")

            for i in self.tree_status.get_children(): self.tree_status.delete(i)
            currently_online = set()
            for _, u in live_df.iterrows():
                dept = str(u['department']).upper() if u['department'] else "ΑΓΝΩΣΤΟ"
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
                self.add_to_log(f"Ο χρήστης {u_off.upper()} αποσυνδέθηκε!", "ALERT")
                winsound.Beep(500, 200)
            joined = currently_online - self.previously_online
            for u_on in joined:
                if self.previously_online: self.add_to_log(f"Ο χρήστης {u_on.upper()} συνδέθηκε.", "SUCCESS")
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
        if messagebox.askyesno("Επιβεβαίωση", "Θέλετε να διαγράψετε ΟΛΑ τα εκκρεμή (μη απεσταλμένα) συμβάντα;\n\nΔεν θα σταλούν ποτέ σε report."):
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.execute("DELETE FROM events WHERE is_sent = 0")
                conn.commit()
                conn.close()
                messagebox.showinfo("OK", "Τα εκκρεμή συμβάντα διαγράφηκαν.")
                self.refresh_data()
            except Exception as ex:
                messagebox.showerror("Σφάλμα", str(ex))

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
        print("🔴 ΕΝΤΟΠΙΣΤΗΚΕ ΚΡΙΣΙΜΟ ΣΦΑΛΜΑ:")
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
