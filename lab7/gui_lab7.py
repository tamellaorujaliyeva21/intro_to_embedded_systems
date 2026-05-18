# LAB 7 GUI CODE
# This program is the computer-side GUI for the RFID project.
# It connects to Arduino through the serial port, receives RFID tag IDs,
# saves them into an SQLite database, and shows the saved records in a table.

import sys
import sqlite3
from datetime import datetime

import serial
import serial.tools.list_ports

from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QGroupBox,
)


# Name of the database file where RFID tag information will be stored.
DATABASE_FILE = "rfid_database.db"

# Baud rate should match the baud rate used in the Arduino code.
BAUD_RATE = 9600

# Arduino sends RFID data with this prefix.
# The GUI checks for this text to understand that the line contains RFID UID data.
DATA_PREFIX = "DATA_PACKET:"


# ========================= DATABASE MANAGER =========================

class DatabaseManager:
    def __init__(self, db_file=DATABASE_FILE):
        # Save the database file name and create the database/table if needed.
        self.db_file = db_file
        self.initialize_database()

    def connect(self):
        # Opens a connection to the SQLite database.
        # SQLite stores the database locally in one file.
        return sqlite3.connect(self.db_file)

    def initialize_database(self):
        # This function creates the tags table if it does not already exist.
        conn = self.connect()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_id TEXT UNIQUE,
                rfid_uid TEXT UNIQUE NOT NULL,
                scan_count INTEGER NOT NULL DEFAULT 1,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
        """)

        conn.commit()
        conn.close()

    def add_or_update_tag(self, rfid_uid):
        # This function is called whenever a tag is scanned.
        # If the tag already exists, its scan count is increased.
        # If it is a new tag, it is inserted into the database.
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = self.connect()
        cursor = conn.cursor()

        # Check whether this RFID UID already exists in the database.
        cursor.execute(
            "SELECT id, tag_id, scan_count FROM tags WHERE rfid_uid = ?",
            (rfid_uid,)
        )

        existing_tag = cursor.fetchone()

        if existing_tag:
            # If the tag already exists, update only scan count and last seen time.
            db_id, tag_id, scan_count = existing_tag
            new_count = scan_count + 1

            cursor.execute("""
                UPDATE tags
                SET scan_count = ?, last_seen = ?
                WHERE rfid_uid = ?
            """, (new_count, now, rfid_uid))

            conn.commit()
            conn.close()

            # Return information so the GUI can show what happened.
            return {
                "status": "existing",
                "tag_id": tag_id,
                "rfid_uid": rfid_uid,
                "scan_count": new_count
            }

        else:
            # If this RFID UID is new, first insert it with a temporary tag ID.
            cursor.execute("""
                INSERT INTO tags (tag_id, rfid_uid, scan_count, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
            """, ("TEMP", rfid_uid, 1, now, now))

            # Get the automatically generated database ID.
            new_db_id = cursor.lastrowid

            # Create a cleaner tag name like TAG-001, TAG-002, etc.
            tag_id = f"TAG-{new_db_id:03d}"

            # Replace the temporary value with the real tag ID.
            cursor.execute("""
                UPDATE tags
                SET tag_id = ?
                WHERE id = ?
            """, (tag_id, new_db_id))

            conn.commit()
            conn.close()

            # Return new tag information to the GUI.
            return {
                "status": "new",
                "tag_id": tag_id,
                "rfid_uid": rfid_uid,
                "scan_count": 1
            }

    def get_all_tags(self, search_text=""):
        # Reads all saved tags from the database.
        # If search text is provided, it only returns matching rows.
        conn = self.connect()
        cursor = conn.cursor()

        if search_text:
            search_pattern = f"%{search_text}%"

            # Search by either Tag ID or RFID UID.
            cursor.execute("""
                SELECT tag_id, rfid_uid, scan_count, first_seen, last_seen
                FROM tags
                WHERE tag_id LIKE ? OR rfid_uid LIKE ?
                ORDER BY id ASC
            """, (search_pattern, search_pattern))
        else:
            # If there is no search text, show all records.
            cursor.execute("""
                SELECT tag_id, rfid_uid, scan_count, first_seen, last_seen
                FROM tags
                ORDER BY id ASC
            """)

        rows = cursor.fetchall()
        conn.close()

        return rows

    def clear_database(self):
        # Deletes all saved RFID records from the database.
        conn = self.connect()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM tags")

        # This resets the AUTOINCREMENT counter,
        # so after clearing, new tags start again from TAG-001.
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='tags'")

        conn.commit()
        conn.close()


# ========================= SERIAL READER THREAD =========================

class SerialReaderThread(QThread):
    # Signals are used to safely send information from the serial thread to the GUI.
    # This is important because GUI widgets should not be updated directly from a thread.
    tag_scanned = pyqtSignal(str)
    serial_message = pyqtSignal(str)
    connection_error = pyqtSignal(str)

    def __init__(self, port_name, baud_rate=BAUD_RATE):
        super().__init__()

        # Store selected serial port and baud rate.
        self.port_name = port_name
        self.baud_rate = baud_rate

        # This controls whether the thread should keep reading.
        self.running = False

        # This will store the actual serial connection.
        self.serial_connection = None

    def run(self):
        # This function runs in the background after thread.start() is called.
        try:
            # Try to open the selected serial port.
            self.serial_connection = serial.Serial(
                self.port_name,
                self.baud_rate,
                timeout=1
            )

            self.running = True
            self.serial_message.emit(f"Connected to {self.port_name} at {self.baud_rate} baud.")

            # Keep reading from Arduino while the connection is active.
            while self.running:
                try:
                    # Read one full line from Arduino.
                    # decode converts bytes into normal text.
                    line = self.serial_connection.readline().decode(errors="ignore").strip()

                    # If Arduino sent an empty line, ignore it.
                    if not line:
                        continue

                    # Show every Arduino line in the log.
                    self.serial_message.emit(f"Arduino: {line}")

                    # Only lines starting with DATA_PACKET contain RFID UID data.
                    if line.startswith(DATA_PREFIX):
                        uid = line.replace(DATA_PREFIX, "").strip().upper()

                        # If UID is not empty, send it to the main GUI.
                        if uid:
                            self.tag_scanned.emit(uid)

                except Exception as e:
                    # If something goes wrong while reading, inform the GUI.
                    self.connection_error.emit(f"Serial read error: {e}")
                    break

        except Exception as e:
            # This happens if the selected COM port cannot be opened.
            self.connection_error.emit(f"Could not open serial port: {e}")

        finally:
            # Make sure the serial port is closed when the thread stops.
            if self.serial_connection and self.serial_connection.is_open:
                self.serial_connection.close()

            self.serial_message.emit("Serial connection closed.")

    def stop(self):
        # Stop the thread safely.
        self.running = False
        self.wait()


# ========================= MAIN WINDOW =========================

class RFIDDatabaseGUI(QMainWindow):
    def __init__(self):
        super().__init__()

        # DatabaseManager handles all SQLite operations.
        self.db = DatabaseManager()

        # This will hold the serial reader thread after connecting.
        self.serial_thread = None

        self.setWindowTitle("RFID Tag Database Viewer")
        self.setMinimumSize(950, 650)

        # Prepare the interface and load initial data.
        self.setup_ui()
        self.load_ports()
        self.refresh_table()

    def setup_ui(self):
        # Main widget and layout that will contain all parts of the window.
        main_widget = QWidget()
        main_layout = QVBoxLayout()

        # ================= Serial Controls =================
        serial_group = QGroupBox("Serial Connection")
        serial_layout = QHBoxLayout()

        # Dropdown where available COM ports will appear.
        self.port_combo = QComboBox()

        # Button for scanning available serial ports again.
        self.refresh_ports_button = QPushButton("Refresh Ports")
        self.refresh_ports_button.clicked.connect(self.load_ports)

        # Button for starting serial communication.
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_serial)

        # Button for stopping serial communication.
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self.disconnect_serial)
        self.disconnect_button.setEnabled(False)

        # Label that shows whether we are connected or disconnected.
        self.status_label = QLabel("Status: Disconnected")

        # Add serial controls into one horizontal row.
        serial_layout.addWidget(QLabel("Port:"))
        serial_layout.addWidget(self.port_combo)
        serial_layout.addWidget(self.refresh_ports_button)
        serial_layout.addWidget(self.connect_button)
        serial_layout.addWidget(self.disconnect_button)
        serial_layout.addWidget(self.status_label)

        serial_group.setLayout(serial_layout)

        # ================= Search Controls =================
        search_group = QGroupBox("Database Navigation")
        search_layout = QHBoxLayout()

        # Search bar for filtering the database table.
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by Tag ID or RFID UID...")

        # Every time the text changes, the table refreshes automatically.
        self.search_input.textChanged.connect(self.refresh_table)

        # Button for manually refreshing the table.
        self.refresh_table_button = QPushButton("Refresh Table")
        self.refresh_table_button.clicked.connect(self.refresh_table)

        # Button for deleting all records from the database.
        self.clear_button = QPushButton("Clear Database")
        self.clear_button.clicked.connect(self.clear_database)

        search_layout.addWidget(QLabel("Search:"))
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.refresh_table_button)
        search_layout.addWidget(self.clear_button)

        search_group.setLayout(search_layout)

        # ================= Table =================
        # This table displays all saved RFID records.
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Tag ID",
            "RFID UID",
            "Scan Count",
            "First Seen",
            "Last Seen"
        ])

        # Stretch columns so the table uses the available width nicely.
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        # Make the table read-only, so the user cannot accidentally edit cells.
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # Select the whole row when one cell is clicked.
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        # Alternating row colors make the table easier to read.
        self.table.setAlternatingRowColors(True)

        # ================= Latest Scan =================
        latest_group = QGroupBox("Latest Scan")
        latest_layout = QHBoxLayout()

        # This label shows the most recently scanned RFID tag.
        self.latest_scan_label = QLabel("No tag scanned yet.")
        latest_layout.addWidget(self.latest_scan_label)

        latest_group.setLayout(latest_layout)

        # ================= Log Output =================
        log_group = QGroupBox("Serial Log")
        log_layout = QVBoxLayout()

        # This text box shows Arduino messages and program events.
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(140)

        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)

        # ================= Add everything to the window =================
        main_layout.addWidget(serial_group)
        main_layout.addWidget(search_group)
        main_layout.addWidget(self.table)
        main_layout.addWidget(latest_group)
        main_layout.addWidget(log_group)

        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

    def load_ports(self):
        # Clear old port list first.
        self.port_combo.clear()

        # Get all serial ports currently available on the computer.
        ports = serial.tools.list_ports.comports()

        if not ports:
            # If no ports are found, disable the Connect button.
            self.port_combo.addItem("No ports found")
            self.connect_button.setEnabled(False)
            return

        # Add each available port to the dropdown.
        for port in ports:
            display_text = f"{port.device} - {port.description}"

            # display_text is what the user sees,
            # port.device is the actual value used for connection.
            self.port_combo.addItem(display_text, port.device)

        self.connect_button.setEnabled(True)

    def connect_serial(self):
        # Get the selected port from the dropdown.
        port_name = self.port_combo.currentData()

        if not port_name:
            QMessageBox.warning(self, "No Port Selected", "Please select a valid serial port.")
            return

        # Create a background thread for reading Arduino data.
        self.serial_thread = SerialReaderThread(port_name)

        # Connect signals from the thread to GUI functions.
        self.serial_thread.tag_scanned.connect(self.handle_tag_scanned)
        self.serial_thread.serial_message.connect(self.add_log)
        self.serial_thread.connection_error.connect(self.handle_serial_error)

        # Start reading serial data in the background.
        self.serial_thread.start()

        # Update buttons and status after connecting.
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        self.port_combo.setEnabled(False)
        self.status_label.setText(f"Status: Connected to {port_name}")

    def disconnect_serial(self):
        # Stop serial communication if it is currently running.
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None

        # Reset buttons and status.
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.port_combo.setEnabled(True)
        self.status_label.setText("Status: Disconnected")

    def handle_tag_scanned(self, uid):
        # This function runs when a valid RFID UID is received from Arduino.
        result = self.db.add_or_update_tag(uid)

        if result["status"] == "new":
            # Message for a tag scanned for the first time.
            message = (
                f"New tag saved: {result['tag_id']} | "
                f"UID: {result['rfid_uid']} | "
                f"Count: {result['scan_count']}"
            )
        else:
            # Message for a tag that was already in the database.
            message = (
                f"Existing tag updated: {result['tag_id']} | "
                f"UID: {result['rfid_uid']} | "
                f"Count: {result['scan_count']}"
            )

        # Show latest scan result, write it in the log, and refresh the table.
        self.latest_scan_label.setText(message)
        self.add_log(message)
        self.refresh_table()

    def refresh_table(self):
        # Reload table data from the database.
        # If the search box has text, only matching rows will be shown.
        search_text = self.search_input.text().strip()
        rows = self.db.get_all_tags(search_text)

        # Set table row count based on how many records we have.
        self.table.setRowCount(len(rows))

        # Fill the table cell by cell.
        for row_index, row_data in enumerate(rows):
            for column_index, value in enumerate(row_data):
                item = QTableWidgetItem(str(value))

                # Center the text in each table cell.
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                self.table.setItem(row_index, column_index, item)

    def clear_database(self):
        # Ask for confirmation before deleting all RFID records.
        confirm = QMessageBox.question(
            self,
            "Clear Database",
            "Are you sure you want to delete all saved RFID records?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if confirm == QMessageBox.StandardButton.Yes:
            # If the user confirms, clear database and update the GUI.
            self.db.clear_database()
            self.refresh_table()
            self.latest_scan_label.setText("Database cleared.")
            self.add_log("Database cleared.")

    def add_log(self, message):
        # Add a timestamped message to the serial log box.
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(f"[{timestamp}] {message}")

    def handle_serial_error(self, error_message):
        # Show serial errors in both the log and a pop-up window.
        self.add_log(error_message)
        QMessageBox.critical(self, "Serial Error", error_message)

        # Disconnect safely after an error.
        self.disconnect_serial()

    def closeEvent(self, event):
        # This runs when the user closes the window.
        # It makes sure the serial thread is stopped before the program exits.
        self.disconnect_serial()
        event.accept()


# ========================= APPLICATION ENTRY POINT =========================

def main():
    # Create the PyQt application object.
    app = QApplication(sys.argv)

    # Create and show the main RFID GUI window.
    window = RFIDDatabaseGUI()
    window.show()

    # Start the PyQt event loop.
    sys.exit(app.exec())


# Run main() only when this file is executed directly.
if __name__ == "__main__":
    main()
