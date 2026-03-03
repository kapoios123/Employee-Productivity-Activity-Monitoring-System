🛡️ WorkFlow Sentinel (Employee Activity & Management System)
WorkFlow Sentinel is a comprehensive Python-based solution for workplace productivity monitoring, activity logging, and internal communication. It features a modern GUI and a robust backend using SQLite and multi-threading.

🚀 Key Features
Real-time Dashboard: Monitor active users, their IP addresses, and live status (Online/Idle/Break).

Activity Tracking: Automated detection of user inactivity via mouse and keyboard listeners.

Internal Messaging: Built-in chat system for direct communication between Admin and Clients.

Automated Reporting: Generates and sends HTML-formatted activity reports via SMTP.

Remote Desktop Integration: Quick access to AnyDesk for remote technical support.

🔧 First-Time Setup & Initialization
The application is designed to be user-friendly even during the initial configuration.

1. Database Connection (First Startup)
When you run the application for the first time:

Automatic Detection: The app attempts to locate the database file (archer.db).

Configuration Prompt: If the database is not found, an error message will appear. Simply go to the Settings menu.

Browse & Apply: Use the "Browse" button to select your .db file and click Apply.

Persistent Settings: The app creates a config.ini file locally. On your next launch, the app will remember your path and start without any prompts.

2. Dependencies
Install the required Python libraries:
--> pip install customtkinter pandas pynput Pillow pystray


💻 Technical Details
The Client App (archer_v2.py)
The client runs as a background process visible in the System Tray.

Inactivity Logic: If no input is detected for a specific threshold, the app automatically logs an "IDLE" event to the database.

Connection Resilience: Includes retry logic for database operations to handle network instability.

The Admin Panel (archer_admin.py)
The central hub for management.

Threading: Uses Python's threading module to handle heartbeats and email sending without blocking the UI.

Data Processing: Uses pandas to aggregate logs into professional reports.

📂 Project Structure
archer_admin.py: The management dashboard source code.

archer_v2.py: The client-side monitoring agent source code.

archer.db: The SQLite database schema (Initial data included).

🛠️ How to Run
Clone the repository to your local machine.

Ensure Python 3.10+ is installed.

Run the Admin Panel: python archer_admin.py

Configure the database path through the UI as described in the Setup section.
