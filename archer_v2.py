import customtkinter as ctk
import sqlite3, os, threading, time, uuid, sys, socket, pandas as pd, configparser, ctypes
from datetime import datetime, timedelta
from pynput import mouse, keyboard
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as item
import winsound
import subprocess
import re


# --- CONFIGURATION MANAGER ---
def get_db_path():
    config = configparser.ConfigParser()
    # Το αρχείο ρυθμίσεων θα είναι στον ίδιο φάκελο με το script
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
    
    db_path = None

    # 1. Προσπάθεια ανάγνωσης από το config.ini
    if os.path.exists(config_file):
        try:
            config.read(config_file, encoding='utf-8')
            db_path = config.get('SETTINGS', 'db_path', fallback=None)
        except:
            db_path = None

    # 2. Αν δεν υπάρχει στο config ή το αρχείο που δείχνει το config δεν υπάρχει πια
    if not db_path or not os.path.exists(db_path):
        # Δημιουργία κρυφού παραθύρου για το διάλογο
        temp_root = ctypes.windll.user32.GetForegroundWindow() # Για να έρθει μπροστά το παράθυρο
        import tkinter as tk
        from tkinter import filedialog, messagebox
        
        root_temp = tk.Tk()
        root_temp.withdraw()
        root_temp.attributes("-topmost", True)
        
        messagebox.showinfo("Archer System", "Παρακαλώ επιλέξτε το αρχείο της βάσης δεδομένων (archer.db).")
        
        selected_file = filedialog.askopenfilename(
            title="Επιλογή archer.db",
            filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")]
        )
        
        root_temp.destroy()

        if selected_file:
            save_db_path_to_ini(selected_file)
            return selected_file
        else:
            # Αν ο χρήστης πατήσει Cancel, το πρόγραμμα κλείνει
            messagebox.showerror("Error", "Η εφαρμογή δεν μπορεί να ξεκινήσει χωρίς βάση δεδομένων.")
            sys.exit()
            
    return db_path

def save_db_path_to_ini(new_path):
    config = configparser.ConfigParser()
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
    if not config.has_section('SETTINGS'):
        config.add_section('SETTINGS')
    config.set('SETTINGS', 'db_path', str(new_path))
    with open(config_file, 'w', encoding='utf-8') as configfile:
        config.write(configfile)

# Εκτέλεση της αναζήτησης
DB_PATH = get_db_path()
LOCK_FILE = os.path.join(os.environ.get('TEMP', ''), 'archer_client.lock')

ctk.set_appearance_mode("dark")

class ArcherClient:
    def __init__(self, root):
        self.check_single_instance()
        self.root = root
        self.username = os.getlogin().lower()
        self.hostname = socket.gethostname().upper()
        self.user_id = f"{self.username}@{self.hostname}"
        self.current_event_id = None
        self.last_activity = time.time()
        self.idle_threshold = 300
        self.menu_win = None
        
        # Συντεταγμένες για drag
        self.x = 0
        self.y = 0
        
        # Προστασία από Alt+F4
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        
        self.auto_register()
        self.setup_ui()
        
        # Threads λειτουργίας
        threading.Thread(target=self.setup_tray, daemon=True).start()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        threading.Thread(target=self.inactivity_checker, daemon=True).start()
        
        # Listeners για ανίχνευση δραστηριότητας
        mouse.Listener(on_move=self.reset_activity, on_click=self.reset_activity).start()
        keyboard.Listener(on_press=self.reset_activity).start()

    def is_locked(self):
        """Ελέγχει αν τα Windows είναι κλειδωμένα (Workstation Locked)"""
        try:
            user32 = ctypes.windll.user32
            return user32.GetForegroundWindow() == 0
        except:
            return False

    def check_single_instance(self):
        if os.path.exists(LOCK_FILE):
            try: os.remove(LOCK_FILE)
            except: sys.exit()
        with open(LOCK_FILE, 'w') as f: f.write("locked")

    def is_ip_static(self):
        """
        Βελτιωμένη ανίχνευση τύπου IP (Static/Dynamic) μέσω ipconfig /all.
        Επιστρέφει "Static", "Dynamic" ή "Unknown".
        """
        try:
            output = subprocess.check_output(
                ["ipconfig", "/all"],
                stderr=subprocess.STDOUT,
                text=True,
                encoding='cp437',
                errors='ignore'
            )
            match = re.search(r'DHCP Enabled\s*\.\s*:\s*(\w+)', output, re.IGNORECASE)
            if match:
                value = match.group(1).strip().lower()
                if value == "yes":
                    return "Dynamic"
                elif value == "no":
                    return "Static"
            if "DHCP Enabled" in output:
                lines = output.splitlines()
                for line in lines:
                    if "DHCP Enabled" in line:
                        if "Yes" in line:
                            return "Dynamic"
                        elif "No" in line:
                            return "Static"
        except Exception as e:
            print(f"IP detection via ipconfig failed: {e}")

        try:
            ps_cmd = r'Get-NetIPInterface | Where-Object {$_.InterfaceAlias -notlike "*Loopback*"} | Select-Object Dhcp | ConvertTo-Csv -NoTypeInformation'
            result = subprocess.run(
                ["powershell", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore'
            )
            if result.returncode == 0:
                lines = result.stdout.splitlines()
                if len(lines) >= 2:
                    dhcp_value = lines[1].strip().strip('"')
                    if dhcp_value.lower() == "enabled":
                        return "Dynamic"
                    elif dhcp_value.lower() == "disabled":
                        return "Static"
        except Exception as e:
            print(f"IP detection via PowerShell failed: {e}")

        return "Unknown"

    def auto_register(self):
        """Αρχική εγγραφή του χρήστη στη βάση."""
        try:
            hostname = socket.gethostname().upper()
            ip_addr = socket.gethostbyname(hostname)
            ip_type = self.is_ip_static()
            user_id = f"{self.username}@{hostname}"

            conn = sqlite3.connect(DB_PATH)
            conn.execute("""
                INSERT OR IGNORE INTO user_config 
                (username, hostname, user_id, ip_address, department, ip_type) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (self.username, hostname, user_id, ip_addr, "NEW", ip_type))
            
            conn.execute("""
                UPDATE user_config 
                SET ip_address = ?, ip_type = ?, hostname = ?, user_id = ?
                WHERE username = ? AND (hostname IS NULL OR hostname = '')
            """, (ip_addr, ip_type, hostname, user_id, self.username))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Auto-register error: {e}")

    def setup_tray(self):
        img = Image.new('RGB', (64, 64), color=(31, 83, 141))
        d = ImageDraw.Draw(img); d.rectangle((16, 16, 48, 48), fill=(255, 255, 255))
        menu = (item('Open Controls', self.show_app), item('Exit', self.quit_app))
        self.tray_icon = pystray.Icon("Archer", img, f"Archer: {self.username}", menu)
        self.tray_icon.run()

    def show_app(self): self.root.after(0, self.root.deiconify)
    def quit_app(self): self.tray_icon.stop(); self.root.quit()

    def setup_ui(self):
        self.root.overrideredirect(True) 
        self.root.geometry("45x45+20+20")
        self.root.attributes("-topmost", True)
        
        self.btn = ctk.CTkButton(self.root, text="⋮", width=40, height=40, corner_radius=10)
        self.btn.pack(expand=True, fill="both")

        # Αριστερό κλικ → άνοιγμα μενού
        self.btn.bind("<Button-1>", lambda e: self.toggle_menu())

        # Δεξί κλικ → έναρξη μετακίνησης (drag)
        self.btn.bind("<Button-3>", self.start_drag)
        self.btn.bind("<B3-Motion>", self.do_drag)

    # ========== ΝΕΕΣ ΜΕΘΟΔΟΙ ΓΙΑ ΤΜΗΜΑ & ΜΕΝΟΥ ==========
    def get_user_department(self):
        """Διαβάζει το τμήμα του χρήστη από τη βάση."""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT department FROM user_config WHERE username=?", (self.username,))
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                return row[0].strip().upper()
        except Exception as e:
            print(f"Error getting department: {e}")
        return None  # αν δεν βρεθεί, επιστρέφει None

    def get_menu_options(self):
        """
        Επιστρέφει λίστα με τα event options.
        Προτεραιότητα:
        1. Αν υπάρχει εγγραφή στο dept_menu_options για το τμήμα του χρήστη, χρησιμοποιεί αυτή.
        2. Αλλιώς χρησιμοποιεί το default menu_options από settings.
        """
        dept = self.get_user_department()
        options = []
        try:
            conn = sqlite3.connect(DB_PATH)
            if dept:
                cursor = conn.cursor()
                cursor.execute("SELECT menu_options FROM dept_menu_options WHERE department=?", (dept,))
                row = cursor.fetchone()
                if row and row[0]:
                    options = [x.strip() for x in row[0].split(',')]
            # Αν δεν βρέθηκε ή δεν υπάρχει τμήμα, χρησιμοποιούμε το default
            if not options:
                cursor = conn.cursor()
                cursor.execute("SELECT value FROM settings WHERE key='menu_options'")
                row = cursor.fetchone()
                if row and row[0]:
                    options = [x.strip() for x in row[0].split(',')]
            conn.close()
        except Exception as e:
            print(f"Error loading menu options: {e}")
            # Fallback σε βασικές επιλογές
            options = ["ΒΛΑΒΗ", "ΔΙΑΛΕΙΜΜΑ", "RESTART", "ΤΕΛΟΣ"]
        # Πάντα προσθέτουμε "ΜΗΝΥΜΑ ΣΤΟΝ ADMIN" στην αρχή
        return ["ΜΗΝΥΜΑ ΣΤΟΝ ADMIN"] + options

    def toggle_menu(self):
        if self.menu_win and self.menu_win.winfo_exists():
            self.menu_win.destroy()
            return
        
        options = self.get_menu_options()  # ΝΕΟ: φόρτωση από βάση βάσει τμήματος

        self.menu_win = ctk.CTkToplevel(self.root)
        self.menu_win.overrideredirect(True); self.menu_win.attributes("-topmost", True)
        
        menu_w, menu_h = 200, len(options) * 40
        screen_w = self.menu_win.winfo_screenwidth()
        screen_h = self.menu_win.winfo_screenheight()
        pos_x, pos_y = self.root.winfo_x() + 50, self.root.winfo_y()
        
        if pos_x + menu_w > screen_w: pos_x = self.root.winfo_x() - menu_w - 5
        if pos_y + menu_h > screen_h: pos_y = screen_h - menu_h - 10
        
        self.menu_win.geometry(f"{menu_w}x{menu_h}+{pos_x}+{pos_y}")

        for opt in options:
            color = "#27ae60" if "ΜΗΝΥΜΑ ΣΤΟΝ ADMIN" in opt else "#3b3b3b"
            t_color = "black" if "ΜΗΝΥΜΑ ΣΤΟΝ ADMIN" in opt else "white"
            btn = ctk.CTkButton(self.menu_win, text=opt, corner_radius=0, height=40, anchor="w",
                                fg_color=color, text_color=t_color,
                                command=lambda x=opt: self.select_option(x))
            btn.pack(fill="x")
        
        self.menu_win.bind("<FocusOut>", lambda e: self.menu_win.destroy())

    def select_option(self, opt):
        if self.menu_win: self.menu_win.destroy()
        if "ΜΗΝΥΜΑ ΣΤΟΝ ADMIN" in opt: self.show_chat_popup()
        else: self.start_event(opt)

    def show_chat_popup(self, incoming_msg=None):
        pop = ctk.CTkToplevel(self.root)
        pop.title("Archer Chat"); pop.geometry("400x480")
        pop.attributes("-topmost", True); pop.configure(fg_color="#1a1a1a")
        
        pop.update_idletasks()
        x = (pop.winfo_screenwidth() // 2) - 200
        y = (pop.winfo_screenheight() // 2) - 240
        pop.geometry(f"400x480+{x}+{y}")

        ctk.CTkLabel(pop, text="💬 ΕΠΙΚΟΙΝΩΝΙΑ ΜΕ ADMIN", font=("Segoe UI", 14, "bold"), text_color="#3498db").pack(pady=10)
        chat_history = ctk.CTkTextbox(pop, width=360, height=220, font=("Segoe UI", 11))
        chat_history.pack(pady=5, padx=20)

        try:
            conn = sqlite3.connect(DB_PATH)
            query = """
                SELECT 'ADMIN' as s, message as m, timestamp FROM user_messages WHERE username=? 
                UNION ALL 
                SELECT 'ΕΓΩ', message, timestamp FROM admin_messages WHERE username=? 
                ORDER BY timestamp DESC LIMIT 6
            """
            history = pd.read_sql_query(query, conn, params=(self.username, self.username))
            conn.close()
            for _, row in history[::-1].iterrows():
                chat_history.insert("end", f"[{row['s']}]: {row['m']}\n")
            if incoming_msg: 
                chat_history.insert("end", f"--- ΝΕΟ ΜΗΝΥΜΑ ---\n[ADMIN]: {incoming_msg}\n")
            chat_history.see("end")
        except: pass
        chat_history.configure(state="disabled")

        entry = ctk.CTkEntry(pop, width=350, placeholder_text="Γράψτε εδώ..."); entry.pack(pady=5, padx=20); entry.focus()
        
        def send():
            msg = entry.get().strip()
            if msg:
                self.db_op("INSERT INTO admin_messages (username, message) VALUES (?, ?)", (self.username, msg))
                pop.destroy()
        
        btn_frame = ctk.CTkFrame(pop, fg_color="transparent"); btn_frame.pack(pady=15)
        ctk.CTkButton(btn_frame, text="ΑΠΟΣΤΟΛΗ", width=120, fg_color="#27ae60", command=send).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="ΚΛΕΙΣΙΜΟ", width=120, fg_color="#2c3e50", command=pop.destroy).pack(side="left", padx=10)
        pop.bind("<Return>", lambda e: send())
        if incoming_msg: winsound.Beep(1000, 400)

    def start_event(self, etype):
        if self.current_event_id: return
        self.root.withdraw()
        self.current_event_id = str(uuid.uuid4())[:8]
        start_dt = datetime.now()
        if etype == "ΑΔΡΑΝΕΙΑ": start_dt = start_dt - timedelta(seconds=self.idle_threshold)
        self.db_op("INSERT INTO events (id, username, event_type, start_time, is_sent) VALUES (?, ?, ?, ?, 0)", 
                   (self.current_event_id, self.username, etype, start_dt.strftime("%Y-%m-%d %H:%M:%S")))
        self.open_blocker(etype)

    def open_blocker(self, title):
        self.blocker = ctk.CTkToplevel(self.root)
        self.blocker.attributes("-fullscreen", True, "-topmost", True)
        self.blocker.configure(fg_color="black")
        self.blocker.protocol("WM_DELETE_WINDOW", lambda: None)
        ctk.CTkLabel(self.blocker, text=title, font=("Arial", 45, "bold"), text_color="#e74c3c").place(relx=0.5, rely=0.4, anchor="center")
        ctk.CTkButton(self.blocker, text="ΕΠΙΣΤΡΟΦΗ", width=200, height=50, command=self.stop_event).place(relx=0.5, rely=0.6, anchor="center")

    def stop_event(self):
        if self.current_event_id:
            self.db_op("UPDATE events SET end_time = ? WHERE id = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), self.current_event_id))
            self.current_event_id = None
        if hasattr(self, 'blocker'): self.blocker.destroy()
        self.root.deiconify()

    def heartbeat_loop(self):
        # Τελευταία ενημέρωση IP – αρχικοποιούμε ώστε να γίνει άμεσα
        self.last_ip_update = 0
        # Επιθυμητό διάστημα ενημέρωσης: 10 λεπτά (600 δευτερόλεπτα)
        ip_update_interval = 600

        while True:
            try:
                conn = sqlite3.connect(DB_PATH)
                
                # Heartbeat (απλή καταγραφή παρουσίας)
                conn.execute("INSERT OR REPLACE INTO heartbeats (username, last_seen) VALUES (?, CURRENT_TIMESTAMP)", 
                             (self.username,))

                # Ανάγνωση idle threshold από ρυθμίσεις
                res = conn.execute("SELECT value FROM settings WHERE key='idle_threshold'").fetchone()
                if res: 
                    self.idle_threshold = int(res[0])

                # Έλεγχος για νέα μηνύματα από admin
                cursor = conn.cursor()
                cursor.execute("SELECT id, message FROM user_messages WHERE username=? OR username='ALL' ORDER BY id ASC", 
                               (self.username,))
                row = cursor.fetchone()
                if row:
                    msg_id, msg_text = row[0], row[1]
                    self.root.after(0, lambda mt=msg_text: self.show_chat_popup(mt))
                    conn.execute("DELETE FROM user_messages WHERE id=?", (msg_id,))

                # Ενημέρωση IP και τύπου IP κάθε 10 λεπτά
                current_time = time.time()
                if current_time - self.last_ip_update >= ip_update_interval:
                    hostname = socket.gethostname().upper()
                    ip_addr = socket.gethostbyname(hostname)
                    ip_type = self.is_ip_static()
                    conn.execute("""
                        UPDATE user_config 
                        SET ip_address = ?, ip_type = ?
                        WHERE username = ?
                    """, (ip_addr, ip_type, self.username))
                    
                    self.last_ip_update = current_time

                conn.commit()
                conn.close()
            except Exception as e:
                print(f"Heartbeat error: {e}")
            
            time.sleep(10)

    def inactivity_checker(self):
        while True:
            if self.is_locked():
                self.last_activity = time.time()
            
            if time.time() - self.last_activity > self.idle_threshold and not self.current_event_id:
                self.root.after(0, lambda: self.start_event("ΑΔΡΑΝΕΙΑ"))
            time.sleep(5)

    def db_op(self, q, p):
        try:
            conn = sqlite3.connect(DB_PATH); conn.execute(q, p); conn.commit(); conn.close()
        except: pass

    def reset_activity(self, *args): 
        self.last_activity = time.time()
    
    def start_drag(self, e): 
        self.x, self.y = e.x, e.y
        
    def do_drag(self, e): 
        self.root.geometry(f"+{e.x_root - self.x}+{e.y_root - self.y}")

if __name__ == "__main__":
    root = ctk.CTk()
    app = ArcherClient(root)

    root.mainloop()

