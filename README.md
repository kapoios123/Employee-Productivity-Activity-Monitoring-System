# 🛡️ WorkFlow Sentinel (Enterprise Monitoring Suite)

WorkFlow Sentinel is a dual-application ecosystem designed for workforce management. It consists of an **Admin Dashboard** for supervisors and a **Client Agent** for employee workstations, all synchronized through a shared SQLite database.

---

## 🏗️ System Architecture

The project is split into two independent Python applications:

### 1. Admin Control Panel (`archer_admin.py`)
The "Brain" of the system.
* **Live Monitoring:** Tracks heartbeats, active status, and IP addresses of all workstations.
* **Configuration Hub:** Manage departments, email settings, and view activity logs.
* **Smart Reporting:** Automatically aggregates data using `pandas` and sends HTML reports via SMTP.
* **Support Integration:** Launch AnyDesk sessions directly from the UI.

### 2. Client Agent (`archer_v2.py`)
The "Worker" application that runs on every employee's PC.
* **System Tray Operation:** Runs discreetly in the background.
* **Idle Detection:** Uses low-level hooks (`pynput`) to detect inactivity and log idle time automatically.
* **Real-time Heartbeat:** Regularly updates the database to signal that the workstation is active.
* **Interactive Menu:** Allows users to manually set states like "Break" or "External Work".

---

## 🔧 First-Time Configuration (User Friendly)

Both applications feature an intelligent setup process to ensure they work in any environment:

### How to Connect the Database
1. **Initial Launch:** On the first run, if the application cannot find the database, it will notify you.
2. **Setup via UI:** Go to the **Settings** section within the Admin app, click **Browse**, and select your `archer.db` file.
3. **Auto-Configuration:** Once you hit **Apply**, the app generates a `config.ini` file. From that point on, both the Admin and Client will load the correct path automatically without any manual intervention.

---

## 🛠️ Installation & Requirements

Since this project is shared as source code (`.py`), you need to install the dependencies:

```bash
pip install customtkinter pandas pynput Pillow pystray



![Admin Dashboard](Αdmin1.jpg)
