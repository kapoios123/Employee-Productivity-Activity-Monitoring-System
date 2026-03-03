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
