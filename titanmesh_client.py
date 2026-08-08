# titanmesh_client.py
import sys
import json
import sqlite3
import requests
import hashlib
from datetime import datetime
from typing import Dict, List, Optional
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
    QSplitter, QFrame, QMessageBox, QDialog, QFormLayout, QDialogButtonBox,
    QStackedWidget, QScrollArea, QSizePolicy, QSpacerItem, QMenu,
    QInputDialog, QStyle, QStyleFactory, QToolButton
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QPropertyAnimation, QEasingCurve
)
from PyQt6.QtGui import (
    QFont, QPalette, QColor, QIcon, QPainter, QBrush, QPen, QPixmap,
    QLinearGradient, QFontMetrics
)

# ============================================================================
# Database Manager
# ============================================================================

class DatabaseManager:
    def __init__(self, db_path: str = "titanmesh_client.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    private_key TEXT NOT NULL,
                    public_key TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact_key TEXT NOT NULL UNIQUE,
                    name TEXT,
                    last_message_time TIMESTAMP,
                    unread_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT UNIQUE,
                    conversation_id INTEGER,
                    sender_key TEXT NOT NULL,
                    content TEXT,
                    timestamp TIMESTAMP,
                    is_sent BOOLEAN NOT NULL,
                    read_status BOOLEAN DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    block_id TEXT,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                )
            """)
            conn.commit()
    
    def save_user_keys(self, private_key: str, public_key: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM user_keys")
            conn.execute(
                "INSERT INTO user_keys (private_key, public_key) VALUES (?, ?)",
                (private_key, public_key)
            )
            conn.commit()
    
    def load_user_keys(self) -> Optional[tuple]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT private_key, public_key FROM user_keys ORDER BY id DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row if row else None
    
    def get_or_create_conversation(self, contact_key: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id FROM conversations WHERE contact_key = ?",
                (contact_key,)
            )
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                cursor = conn.execute(
                    "INSERT INTO conversations (contact_key) VALUES (?)",
                    (contact_key,)
                )
                conn.commit()
                return cursor.lastrowid
    
    def update_conversation_name(self, conversation_id: int, name: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE conversations SET name = ? WHERE id = ?",
                (name, conversation_id)
            )
            conn.commit()
    
    def get_conversation_name(self, conversation_id: int) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM conversations WHERE id = ?",
                (conversation_id,)
            )
            row = cursor.fetchone()
            return row[0] if row and row[0] else None
    
    def save_message(self, message_id: str, conversation_id: int, 
                    sender_key: str, content: str, timestamp: int,
                    is_sent: bool, status: str = "pending"):
        with sqlite3.connect(self.db_path) as conn:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO messages 
                    (message_id, conversation_id, sender_key, content, timestamp, is_sent, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (message_id, conversation_id, sender_key, content, timestamp, is_sent, status)
                )
                conn.execute(
                    """UPDATE conversations 
                    SET last_message_time = ?, 
                        unread_count = unread_count + CASE WHEN ? THEN 1 ELSE 0 END
                    WHERE id = ?""",
                    (timestamp, not is_sent, conversation_id)
                )
                conn.commit()
            except sqlite3.IntegrityError:
                pass
    
    def mark_conversation_read(self, conversation_id: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE conversations SET unread_count = 0 WHERE id = ?",
                (conversation_id,)
            )
            conn.execute(
                "UPDATE messages SET read_status = 1 WHERE conversation_id = ? AND is_sent = 0",
                (conversation_id,)
            )
            conn.commit()
    
    def get_conversations(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT c.*, 
                    (SELECT content FROM messages WHERE conversation_id = c.id 
                     ORDER BY timestamp DESC LIMIT 1) as last_message
                FROM conversations c
                ORDER BY c.last_message_time DESC"""
            )
            return [dict(row) for row in cursor.fetchall()]
    
    def get_messages(self, conversation_id: int) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM messages 
                WHERE conversation_id = ?
                ORDER BY timestamp ASC""",
                (conversation_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

# ============================================================================
# API Worker Thread
# ============================================================================

class APIWorker(QThread):
    update_inbox = pyqtSignal(list)
    update_sent = pyqtSignal(list)
    update_status = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    message_sent = pyqtSignal(dict)
    
    def __init__(self, node_url: str = "http://localhost:5001"):
        super().__init__()
        self.node_url = node_url
        self.running = False
    
    def run(self):
        self.running = True
        while self.running:
            try:
                # Fetch inbox
                inbox_response = requests.get(
                    f"{self.node_url}/api/inbox", timeout=5
                )
                if inbox_response.status_code == 200:
                    inbox_data = inbox_response.json()
                    if isinstance(inbox_data, list):
                        self.update_inbox.emit(inbox_data)
                
                # Fetch sent
                sent_response = requests.get(
                    f"{self.node_url}/api/sent", timeout=5
                )
                if sent_response.status_code == 200:
                    sent_data = sent_response.json()
                    if isinstance(sent_data, list):
                        self.update_sent.emit(sent_data)
                
                # Fetch status
                status_response = requests.get(
                    f"{self.node_url}/api/status", timeout=5
                )
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    if isinstance(status_data, dict):
                        self.update_status.emit(status_data)
                    
            except requests.exceptions.RequestException as e:
                self.error_occurred.emit(f"Connection error: {str(e)}")
            
            self.sleep(5)  # Refresh every 5 seconds
    
    def stop(self):
        self.running = False
        self.wait()

# ============================================================================
# Custom Widgets
# ============================================================================

class ConversationBubble(QFrame):
    clicked = pyqtSignal(int)  # conversation_id
    
    def __init__(self, conversation_data: Dict, parent=None):
        super().__init__(parent)
        self.conversation_id = conversation_data['id']
        self.setFixedHeight(70)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameStyle(QFrame.Shape.NoFrame)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        
        # Avatar
        avatar = QLabel()
        avatar.setFixedSize(50, 50)
        avatar.setStyleSheet("""
            QLabel {
                background-color: #5692e8;
                border-radius: 25px;
                color: white;
                font-weight: bold;
                font-size: 18px;
                padding: 10px;
            }
        """)
        
        # Get display name and ensure it's a string
        name = conversation_data.get('name')
        contact_key = conversation_data.get('contact_key', 'Unknown')
        
        if name and isinstance(name, str) and name.strip():
            display_name = name
        else:
            display_name = contact_key[:12] if contact_key else 'Unknown'
        
        # Get initials - safely
        if display_name:
            # Take first character, or first two if there's a space
            parts = display_name.split()
            if len(parts) >= 2:
                initial = (parts[0][0] + parts[1][0]).upper() if parts[0] and parts[1] else '?'
            else:
                initial = display_name[:2].upper() if len(display_name) >= 2 else display_name.upper()
        else:
            initial = '??'
        
        avatar.setText(initial)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Info
        info_layout = QVBoxLayout()
        name_label = QLabel(display_name)
        name_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        name_label.setStyleSheet("color: #e8e8e8;")
        
        last_msg = conversation_data.get('last_message', '')
        if last_msg:
            font_metrics = QFontMetrics(QFont("Segoe UI", 10))
            last_msg = font_metrics.elidedText(str(last_msg), Qt.TextElideMode.ElideRight, 200)
        preview_label = QLabel(str(last_msg) if last_msg else 'No messages')
        preview_label.setFont(QFont("Segoe UI", 10))
        preview_label.setStyleSheet("color: #888888;")
        
        info_layout.addWidget(name_label)
        info_layout.addWidget(preview_label)
        
        # Unread badge
        unread_layout = QVBoxLayout()
        unread_count = conversation_data.get('unread_count', 0) or 0
        if unread_count > 0:
            badge = QLabel(str(unread_count))
            badge.setFixedSize(24, 24)
            badge.setStyleSheet("""
                QLabel {
                    background-color: #4a9eff;
                    border-radius: 12px;
                    color: white;
                    font-weight: bold;
                    font-size: 11px;
                    padding: 2px;
                }
            """)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            unread_layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)
        
        layout.addWidget(avatar)
        layout.addLayout(info_layout, 1)
        layout.addLayout(unread_layout)
    
    def mousePressEvent(self, event):
        self.clicked.emit(self.conversation_id)
        super().mousePressEvent(event)

class MessageBubble(QFrame):
    def __init__(self, content: str, timestamp: int, is_sent: bool, status: str = "confirmed", parent=None):
        super().__init__(parent)
        self.is_sent = is_sent
        self.setFrameStyle(QFrame.Shape.NoFrame)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 2, 5, 2)
        
        # Ensure content is a string
        content_str = str(content) if content else '📄 Empty message'
        
        # Message content
        content_label = QLabel(content_str)
        content_label.setWordWrap(True)
        content_label.setFont(QFont("Segoe UI", 11))
        content_label.setMaximumWidth(400)
        content_label.setStyleSheet("""
            padding: 10px;
            border-radius: 10px;
            color: white;
        """ + (
            "background-color: #2b5278;"
            if is_sent else
            "background-color: #3a3a3c;"
        ))
        
        # Timestamp and status
        try:
            time_str = datetime.fromtimestamp(int(timestamp)).strftime("%H:%M")
        except (ValueError, TypeError, OSError):
            time_str = "--:--"
        
        meta_label = QLabel(time_str)
        meta_label.setFont(QFont("Segoe UI", 8))
        meta_label.setStyleSheet("color: #888888;")
        
        if is_sent:
            status_icon = "✓✓" if status == "confirmed" else "✓"
            meta_label.setText(f"{status_icon} {time_str}")
            layout.addWidget(content_label, alignment=Qt.AlignmentFlag.AlignRight)
            layout.addWidget(meta_label, alignment=Qt.AlignmentFlag.AlignRight)
        else:
            layout.addWidget(content_label, alignment=Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(meta_label, alignment=Qt.AlignmentFlag.AlignLeft)

# ============================================================================
# Login Dialog
# ============================================================================

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TitanMesh - Login")
        self.setFixedSize(400, 550)
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a2e;
            }
            QLabel {
                color: #e8e8e8;
            }
            QLineEdit {
                background-color: #16213e;
                border: 2px solid #0f3460;
                border-radius: 8px;
                padding: 10px;
                color: #e8e8e8;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #4a9eff;
            }
            QPushButton {
                background-color: #4a9eff;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a8eef;
            }
            QPushButton#secondary {
                background-color: transparent;
                border: 1px solid #4a9eff;
                color: #4a9eff;
            }
            QPushButton#secondary:hover {
                background-color: rgba(74, 158, 255, 0.1);
            }
        """)
        
        self.db = DatabaseManager()
        self.node_url = "http://localhost:5001"
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Logo
        logo = QLabel("⚡ TitanMesh")
        logo.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        logo.setStyleSheet("color: #4a9eff;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)
        
        # Subtitle
        subtitle = QLabel("Decentralized Messaging")
        subtitle.setFont(QFont("Segoe UI", 10))
        subtitle.setStyleSheet("color: #888888;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        
        layout.addSpacing(20)
        
        # Private Key
        layout.addWidget(QLabel("Private Key"))
        self.private_key_input = QLineEdit()
        self.private_key_input.setPlaceholderText("Enter your private key...")
        self.private_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.private_key_input)
        
        # Show/Hide private key toggle
        self.show_key_btn = QPushButton("👁 Show/Hide")
        self.show_key_btn.setObjectName("secondary")
        self.show_key_btn.setFixedHeight(30)
        self.show_key_btn.clicked.connect(self.toggle_key_visibility)
        layout.addWidget(self.show_key_btn)
        
        # Public Key
        layout.addWidget(QLabel("Public Key"))
        self.public_key_input = QLineEdit()
        self.public_key_input.setPlaceholderText("Enter your public key...")
        layout.addWidget(self.public_key_input)
        
        layout.addSpacing(10)
        
        # Login button
        self.login_btn = QPushButton("Connect")
        self.login_btn.clicked.connect(self.login)
        layout.addWidget(self.login_btn)
        
        # Generate keys button
        self.generate_btn = QPushButton("Generate New Keys")
        self.generate_btn.setObjectName("secondary")
        self.generate_btn.clicked.connect(self.generate_keys)
        layout.addWidget(self.generate_btn)
        
        layout.addStretch()
        
        # Status
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #ff6b6b;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        
        # Load saved keys
        self.load_saved_keys()
    
    def toggle_key_visibility(self):
        if self.private_key_input.echoMode() == QLineEdit.EchoMode.Password:
            self.private_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.private_key_input.setEchoMode(QLineEdit.EchoMode.Password)
    
    def load_saved_keys(self):
        keys = self.db.load_user_keys()
        if keys:
            self.private_key_input.setText(keys[0])
            self.public_key_input.setText(keys[1])
    
    def generate_keys(self):
        try:
            self.status_label.setStyleSheet("color: #4a9eff;")
            self.status_label.setText("Generating keys...")
            QApplication.processEvents()
            
            response = requests.post(f"{self.node_url}/api/keys/generate", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    self.private_key_input.setText(data['private_key'])
                    self.public_key_input.setText(data['public_key'])
                    self.status_label.setStyleSheet("color: #51cf66;")
                    self.status_label.setText("✅ Keys generated successfully!")
                else:
                    self.status_label.setText("Failed to generate keys")
            else:
                self.status_label.setText(f"Server error: {response.status_code}")
        except requests.exceptions.ConnectionError:
            self.status_label.setText("❌ Cannot connect to node. Is it running?")
        except Exception as e:
            self.status_label.setText(f"❌ Error: {str(e)}")
    
    def login(self):
        private_key = self.private_key_input.text().strip()
        public_key = self.public_key_input.text().strip()
        
        if not private_key or not public_key:
            self.status_label.setStyleSheet("color: #ff6b6b;")
            self.status_label.setText("Please enter both keys")
            return
        
        try:
            self.status_label.setStyleSheet("color: #4a9eff;")
            self.status_label.setText("Connecting...")
            QApplication.processEvents()
            
            # Validate keys
            response = requests.post(
                f"{self.node_url}/api/session/set_keys",
                json={"private_key": private_key},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    # Verify the public key matches
                    if data.get('public_key') == public_key:
                        # Save keys
                        self.db.save_user_keys(private_key, public_key)
                        self.status_label.setStyleSheet("color: #51cf66;")
                        self.status_label.setText("✅ Connected!")
                        QTimer.singleShot(500, self.accept)
                    else:
                        self.status_label.setStyleSheet("color: #ff6b6b;")
                        self.status_label.setText("❌ Public key does not match private key")
                else:
                    self.status_label.setStyleSheet("color: #ff6b6b;")
                    self.status_label.setText("❌ Invalid private key")
            else:
                self.status_label.setStyleSheet("color: #ff6b6b;")
                self.status_label.setText(f"❌ Server error: {response.status_code}")
        except requests.exceptions.ConnectionError:
            self.status_label.setStyleSheet("color: #ff6b6b;")
            self.status_label.setText("❌ Cannot connect to node. Is it running?")
        except Exception as e:
            self.status_label.setStyleSheet("color: #ff6b6b;")
            self.status_label.setText(f"❌ Error: {str(e)}")
    
    def get_credentials(self):
        return {
            'private_key': self.private_key_input.text().strip(),
            'public_key': self.public_key_input.text().strip()
        }

# ============================================================================
# Main Window
# ============================================================================

class TitanMeshClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.node_url = "http://localhost:5001"
        self.db = DatabaseManager()
        self.private_key = None
        self.public_key = None
        self.current_conversation_id = None
        self.api_worker = None
        
        # Show login dialog
        self.show_login()
    
    def show_login(self):
        dialog = LoginDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            credentials = dialog.get_credentials()
            self.private_key = credentials['private_key']
            self.public_key = credentials['public_key']
            self.init_ui()
            self.start_api_worker()
        else:
            sys.exit()
    
    def init_ui(self):
        self.setWindowTitle("TitanMesh")
        self.setGeometry(100, 100, 1000, 700)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a2e;
            }
            QWidget {
                background-color: #1a1a2e;
                color: #e8e8e8;
            }
            QListWidget {
                background-color: #16213e;
                border: none;
                border-right: 1px solid #0f3460;
            }
            QListWidget::item {
                border-bottom: 1px solid #0f3460;
                padding: 5px;
            }
            QListWidget::item:hover {
                background-color: #1f3460;
            }
            QListWidget::item:selected {
                background-color: #2a4a7f;
            }
            QTextEdit {
                background-color: #16213e;
                border: 2px solid #0f3460;
                border-radius: 8px;
                padding: 10px;
                color: #e8e8e8;
                font-size: 13px;
            }
            QTextEdit:focus {
                border-color: #4a9eff;
            }
            QLineEdit {
                background-color: #16213e;
                border: 2px solid #0f3460;
                border-radius: 8px;
                padding: 10px;
                color: #e8e8e8;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #4a9eff;
            }
            QPushButton {
                background-color: #4a9eff;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a8eef;
            }
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #16213e;
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: #4a9eff;
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Conversation list panel
        self.conversation_panel = QWidget()
        self.conversation_panel.setFixedWidth(320)
        conv_layout = QVBoxLayout(self.conversation_panel)
        conv_layout.setContentsMargins(0, 0, 0, 0)
        conv_layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header.setFixedHeight(60)
        header.setStyleSheet("background-color: #16213e; border-bottom: 1px solid #0f3460;")
        header_layout = QHBoxLayout(header)
        
        # User info with truncated key
        key_display = self.public_key[:8] + '...' + self.public_key[-4:] if self.public_key else 'No Key'
        self.user_label = QLabel(f"🔑 {key_display}")
        self.user_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.user_label.setStyleSheet("color: #4a9eff;")
        header_layout.addWidget(self.user_label)
        
        # Refresh button
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedSize(40, 40)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                font-size: 16px;
            }
            QPushButton:hover {
                background-color: #1f3460;
                border-radius: 20px;
            }
        """)
        refresh_btn.clicked.connect(self.manual_refresh)
        header_layout.addWidget(refresh_btn)
        
        conv_layout.addWidget(header)
        
        # Conversation list
        self.conversation_list = QListWidget()
        self.conversation_list.itemClicked.connect(self.on_conversation_clicked)
        conv_layout.addWidget(self.conversation_list)
        
        # New conversation button
        new_conv_btn = QPushButton("+ New Conversation")
        new_conv_btn.setStyleSheet("""
            QPushButton {
                background-color: #16213e;
                border: none;
                border-top: 1px solid #0f3460;
                border-radius: 0;
                padding: 15px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #1f3460;
            }
        """)
        new_conv_btn.clicked.connect(self.new_conversation)
        conv_layout.addWidget(new_conv_btn)
        
        main_layout.addWidget(self.conversation_panel)
        
        # Chat area
        self.chat_panel = QWidget()
        chat_layout = QVBoxLayout(self.chat_panel)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)
        
        # Chat header
        self.chat_header = QWidget()
        self.chat_header.setFixedHeight(60)
        self.chat_header.setStyleSheet("background-color: #16213e; border-bottom: 1px solid #0f3460;")
        chat_header_layout = QHBoxLayout(self.chat_header)
        
        self.contact_name_label = QLabel("Select a conversation")
        self.contact_name_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.contact_name_label.setStyleSheet("color: #e8e8e8;")
        chat_header_layout.addWidget(self.contact_name_label)
        
        # Rename button
        self.rename_btn = QPushButton("✏️")
        self.rename_btn.setFixedSize(40, 40)
        self.rename_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #1f3460;
                border-radius: 20px;
            }
        """)
        self.rename_btn.clicked.connect(self.rename_conversation)
        self.rename_btn.setVisible(False)
        chat_header_layout.addWidget(self.rename_btn)
        
        chat_layout.addWidget(self.chat_header)
        
        # Messages area
        self.messages_scroll = QScrollArea()
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.messages_layout.addStretch()
        
        self.messages_scroll.setWidget(self.messages_widget)
        chat_layout.addWidget(self.messages_scroll, 1)
        
        # Input area
        input_widget = QWidget()
        input_widget.setFixedHeight(80)
        input_widget.setStyleSheet("background-color: #16213e;")
        input_layout = QHBoxLayout(input_widget)
        input_layout.setContentsMargins(10, 10, 10, 10)
        
        self.message_input = QTextEdit()
        self.message_input.setFixedHeight(60)
        self.message_input.setPlaceholderText("Type a message...")
        # Send on Enter (Shift+Enter for new line)
        self.message_input.keyPressEvent = self.message_input_key_press
        input_layout.addWidget(self.message_input)
        
        self.send_btn = QPushButton("Send")
        self.send_btn.setFixedSize(80, 60)
        self.send_btn.clicked.connect(self.send_message)
        self.send_btn.setVisible(False)
        input_layout.addWidget(self.send_btn)
        
        chat_layout.addWidget(input_widget)
        
        main_layout.addWidget(self.chat_panel, 1)
        
        # Status bar
        self.statusBar().setStyleSheet("""
            QStatusBar {
                background-color: #16213e;
                color: #888888;
                border-top: 1px solid #0f3460;
            }
        """)
        self.statusBar().showMessage("🟢 Connected to TitanMesh")
    
    def message_input_key_press(self, event):
        # Send on Enter (without Shift)
        if event.key() == Qt.Key.Key_Return and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.send_message()
        else:
            QTextEdit.keyPressEvent(self.message_input, event)
    
    def manual_refresh(self):
        self.statusBar().showMessage("🔄 Refreshing...")
        # Trigger immediate refresh by fetching data
        try:
            inbox_response = requests.get(f"{self.node_url}/api/inbox", timeout=5)
            if inbox_response.status_code == 200:
                inbox_data = inbox_response.json()
                if isinstance(inbox_data, list):
                    self.on_inbox_update(inbox_data)
            
            sent_response = requests.get(f"{self.node_url}/api/sent", timeout=5)
            if sent_response.status_code == 200:
                sent_data = sent_response.json()
                if isinstance(sent_data, list):
                    self.on_sent_update(sent_data)
        except Exception as e:
            self.statusBar().showMessage(f"🔴 Refresh error: {str(e)}")
    
    def start_api_worker(self):
        self.api_worker = APIWorker(self.node_url)
        self.api_worker.update_inbox.connect(self.on_inbox_update)
        self.api_worker.update_sent.connect(self.on_sent_update)
        self.api_worker.update_status.connect(self.on_status_update)
        self.api_worker.error_occurred.connect(self.on_error)
        self.api_worker.start()
    
    def on_inbox_update(self, messages):
        if not messages:
            return
        
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            
            # Determine conversation contact key
            contact_key = msg.get('sender_pub_key', '')
            if contact_key:
                conv_id = self.db.get_or_create_conversation(contact_key)
                self.db.save_message(
                    msg.get('message_id', ''),
                    conv_id,
                    contact_key,
                    msg.get('preview', 'Encrypted message'),
                    msg.get('timestamp', 0) or int(datetime.now().timestamp()),
                    False,
                    'received'
                )
        self.refresh_conversations()
    
    def on_sent_update(self, messages):
        if not messages:
            return
        
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            
            contact_key = msg.get('recipient_pub_key', '')
            if contact_key:
                conv_id = self.db.get_or_create_conversation(contact_key)
                self.db.save_message(
                    msg.get('message_id', ''),
                    conv_id,
                    self.public_key or '',
                    msg.get('preview', ''),
                    msg.get('timestamp', 0) or int(datetime.now().timestamp()),
                    True,
                    msg.get('status', 'pending')
                )
        self.refresh_conversations()
    
    def on_status_update(self, status):
        if not status:
            return
        self.statusBar().showMessage(
            f"🟢 Connected | Blocks: {status.get('total_blocks', 0)} | Peers: {status.get('peers', 0)}"
        )
    
    def on_error(self, error_msg):
        self.statusBar().showMessage(f"🔴 {error_msg}")
    
    def refresh_conversations(self):
        try:
            conversations = self.db.get_conversations()
            current_item = self.conversation_list.currentRow()
            
            self.conversation_list.clear()
            for conv in conversations:
                item = QListWidgetItem()
                widget = ConversationBubble(conv)
                widget.clicked.connect(self.on_conversation_clicked)
                item.setSizeHint(widget.sizeHint())
                self.conversation_list.addItem(item)
                self.conversation_list.setItemWidget(item, widget)
            
            if current_item >= 0 and current_item < self.conversation_list.count():
                self.conversation_list.setCurrentRow(current_item)
            
            # Refresh messages if a conversation is selected
            if self.current_conversation_id:
                self.load_messages(self.current_conversation_id)
        except Exception as e:
            print(f"Error refreshing conversations: {e}")
    
    def on_conversation_clicked(self, conv_id=None):
        try:
            if isinstance(conv_id, int):
                self.current_conversation_id = conv_id
            else:
                # Get conversation from list widget
                current = self.conversation_list.currentItem()
                if not current:
                    return
                widget = self.conversation_list.itemWidget(current)
                if widget:
                    self.current_conversation_id = widget.conversation_id
            
            if self.current_conversation_id:
                self.db.mark_conversation_read(self.current_conversation_id)
                
                # Get conversation info
                conversations = self.db.get_conversations()
                conv_info = next(
                    (c for c in conversations if c['id'] == self.current_conversation_id),
                    None
                )
                
                if conv_info:
                    name = conv_info.get('name')
                    contact_key = conv_info.get('contact_key', 'Unknown')
                    if name and isinstance(name, str) and name.strip():
                        display_name = name
                    else:
                        display_name = contact_key[:12] + '...' if contact_key else 'Unknown'
                    
                    self.contact_name_label.setText(display_name)
                    self.rename_btn.setVisible(True)
                    self.send_btn.setVisible(True)
                    
                    # Load messages
                    self.load_messages(self.current_conversation_id)
            
            self.refresh_conversations()
        except Exception as e:
            print(f"Error in conversation click: {e}")
    
    def load_messages(self, conversation_id: int):
        try:
            # Clear messages
            while self.messages_layout.count() > 0:
                item = self.messages_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            
            # Load messages from database
            messages = self.db.get_messages(conversation_id)
            
            for msg in messages:
                # Decrypt message if needed
                content = msg.get('content', '')
                if not msg.get('is_sent', True) and not content:
                    try:
                        # Try to decrypt the message
                        response = requests.get(
                            f"{self.node_url}/api/message/{msg['message_id']}",
                            timeout=5
                        )
                        if response.status_code == 200:
                            data = response.json()
                            content = data.get('plaintext', '🔒 Encrypted message')
                            # Update database
                            self.db.save_message(
                                msg['message_id'],
                                conversation_id,
                                msg.get('sender_key', ''),
                                content,
                                msg.get('timestamp', 0),
                                False,
                                msg.get('status', 'received')
                            )
                    except:
                        content = '🔒 Unable to decrypt message'
                
                if not content:
                    content = '📄 Empty message'
                
                bubble = MessageBubble(
                    content,
                    msg.get('timestamp', 0),
                    msg.get('is_sent', True),
                    msg.get('status', 'pending')
                )
                self.messages_layout.addWidget(bubble)
            
            # Add stretch
            self.messages_layout.addStretch()
            
            # Scroll to bottom
            QTimer.singleShot(100, self.scroll_to_bottom)
        except Exception as e:
            print(f"Error loading messages: {e}")
    
    def scroll_to_bottom(self):
        scrollbar = self.messages_scroll.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def send_message(self):
        if not self.current_conversation_id:
            return
        
        content = self.message_input.toPlainText().strip()
        if not content:
            return
        
        # Get recipient key
        conversations = self.db.get_conversations()
        conv_info = next(
            (c for c in conversations if c['id'] == self.current_conversation_id),
            None
        )
        
        if not conv_info:
            return
        
        recipient_key = conv_info['contact_key']
        
        try:
            self.send_btn.setEnabled(False)
            self.send_btn.setText("...")
            QApplication.processEvents()
            
            response = requests.post(
                f"{self.node_url}/api/send",
                json={
                    "recipient_key": recipient_key,
                    "message": content
                },
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    self.message_input.clear()
                    self.statusBar().showMessage(
                        f"✅ Message sent! (PoW: {data.get('solve_time', 0):.1f}s)", 
                        5000
                    )
                    
                    # Save to database
                    self.db.save_message(
                        data.get('message_id', ''),
                        self.current_conversation_id,
                        self.public_key or '',
                        content,
                        int(datetime.now().timestamp()),
                        True,
                        'pending'
                    )
                    
                    self.load_messages(self.current_conversation_id)
                    self.refresh_conversations()
                else:
                    QMessageBox.warning(self, "Error", "Failed to send message")
            else:
                QMessageBox.warning(self, "Error", f"Server error: {response.status_code}")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(self, "Error", "Cannot connect to node")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to send: {str(e)}")
        finally:
            self.send_btn.setEnabled(True)
            self.send_btn.setText("Send")
    
    def new_conversation(self):
        contact_key, ok = QInputDialog.getText(
            self, "New Conversation",
            "Enter recipient's public key:"
        )
        
        if ok and contact_key.strip():
            conv_id = self.db.get_or_create_conversation(contact_key.strip())
            self.refresh_conversations()
            
            # Select the new conversation
            for i in range(self.conversation_list.count()):
                item = self.conversation_list.item(i)
                widget = self.conversation_list.itemWidget(item)
                if widget and widget.conversation_id == conv_id:
                    self.conversation_list.setCurrentItem(item)
                    self.on_conversation_clicked(conv_id)
                    break
    
    def rename_conversation(self):
        if not self.current_conversation_id:
            return
        
        current_name = self.db.get_conversation_name(self.current_conversation_id)
        
        name, ok = QInputDialog.getText(
            self, "Rename Conversation",
            "Enter a name for this conversation:",
            text=current_name or ""
        )
        
        if ok and name.strip():
            self.db.update_conversation_name(self.current_conversation_id, name.strip())
            self.contact_name_label.setText(name.strip())
            self.refresh_conversations()
    
    def closeEvent(self, event):
        if self.api_worker:
            self.api_worker.stop()
        event.accept()

# ============================================================================
# Main Application
# ============================================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle(QStyleFactory.create("Fusion"))
    
    # Set dark palette
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(26, 26, 46))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Base, QColor(22, 33, 62))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(22, 33, 62))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(26, 26, 46))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Text, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.Button, QColor(22, 33, 62))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(232, 232, 232))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
    palette.setColor(QPalette.ColorRole.Link, QColor(74, 158, 255))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(74, 158, 255))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(232, 232, 232))
    app.setPalette(palette)
    
    client = TitanMeshClient()
    client.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
