import sys
import ctypes
import os
import sqlite3
import json
import time
import threading
import subprocess
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                               QWidget, QPushButton, QLabel, QTableWidget, QTableWidgetItem,
                               QFileDialog, QTextEdit, QProgressBar, QSplitter, QHeaderView,
                               QGroupBox, QLineEdit, QMessageBox, QFrame)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QMimeData, QMutex, QMutexLocker
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QColor, QIcon, QPixmap
import qtawesome as qta

# Default Photoshop executable path (fallback)
DEFAULT_PHOTOSHOP_PATH = r"C:\Program Files\Adobe\Adobe Photoshop 2025\Photoshop.exe"


class StatusWidget(QWidget):
    """Custom widget for status display with icon and color"""
    
    def __init__(self, status):
        super().__init__()
        self.setStatus(status)
    
    def setStatus(self, status):
        # Clear existing layout
        if self.layout():
            while self.layout().count():
                child = self.layout().takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
        else:
            layout = QHBoxLayout()
            layout.setContentsMargins(8, 4, 8, 4)
            layout.setSpacing(6)
            self.setLayout(layout)
        
        # Create icon and label based on status (no border, radius, padding)
        if status == 'completed':
            icon = qta.icon('fa5s.check-circle', color='#4CAF50')
            label = QLabel('Completed')
            label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif status == 'processing':
            icon = qta.icon('fa5s.spinner', color='#FF9800')
            label = QLabel('Processing')
            label.setStyleSheet("color: #FF9800; font-weight: bold;")
        elif status == 'saving image':
            icon = qta.icon('fa5s.save', color='#2196F3')
            label = QLabel('Saving Image')
            label.setStyleSheet("color: #2196F3; font-weight: bold;")
        elif status == 'error':
            icon = qta.icon('fa5s.times-circle', color='#F44336')
            label = QLabel('Error')
            label.setStyleSheet("color: #F44336; font-weight: bold;")
        elif status == 'stopped':
            icon = qta.icon('fa5s.pause-circle', color='#9E9E9E')
            label = QLabel('Stopped')
            label.setStyleSheet("color: #9E9E9E; font-weight: bold;")
        else:  # draft
            icon = qta.icon('fa5s.file-alt', color='#607D8B')
            label = QLabel('Draft')
            label.setStyleSheet("color: #607D8B; font-weight: bold;")
        
        # Add icon and label to layout
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(16, 16))
        
        self.layout().addWidget(icon_label)
        self.layout().addWidget(label)
        self.layout().addStretch()


class DatabaseManager:
    def __init__(self, db_path="database.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table for file paths
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'draft'
            )
        ''')
        
        # Table for settings
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # Table for processing status
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processing_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER,
                jsx_path TEXT,
                output_path TEXT,
                status TEXT DEFAULT 'pending',
                created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_date TIMESTAMP,
                FOREIGN KEY (file_id) REFERENCES file_paths (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_file_path(self, file_path):
        """Add file path to database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO file_paths (file_path) VALUES (?)", (file_path,))
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None  # File already exists
        finally:
            conn.close()
    
    def get_file_paths(self):
        """Get all file paths from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, file_path, status FROM file_paths ORDER BY id")
        result = cursor.fetchall()
        conn.close()
        return result
    
    def update_file_status(self, file_id, status):
        """Update file processing status"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE file_paths SET status = ? WHERE id = ?", (status, file_id))
        conn.commit()
        conn.close()
    
    def set_setting(self, key, value):
        """Set application setting"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()
    
    def get_setting(self, key, default=None):
        """Get application setting"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else default
    
    def add_processing_record(self, file_id, jsx_path, output_path):
        """Add processing record"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO processing_status (file_id, jsx_path, output_path, status) 
            VALUES (?, ?, ?, 'processing')
        """, (file_id, jsx_path, output_path))
        conn.commit()
        record_id = cursor.lastrowid
        conn.close()
        return record_id
    
    def update_processing_status(self, record_id, status):
        """Update processing record status"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE processing_status 
            SET status = ?, completed_date = CURRENT_TIMESTAMP 
            WHERE id = ?
        """, (status, record_id))
        conn.commit()
        conn.close()


class JSXGenerator:
    @staticmethod
    def generate_jsx_content(psd_path, output_path):
        """Generate JSX script content for Photoshop automation"""
        psd_filename = Path(psd_path).stem
        output_file = Path(output_path) / f"{psd_filename}.jpg"
        
        jsx_content = f'''
// PSD to JPG Converter Script
// Generated automatically by PSD to IMG Converter

try {{
    // Open the PSD file
    var psdFile = new File("{psd_path.replace(chr(92), '/')}");
    if (!psdFile.exists) {{
        throw new Error("PSD file not found: " + psdFile.fsName);
    }}
    
    // Create progress file to indicate script is running
    var progressFile = new File("{str(output_file).replace(chr(92), '/')}.progress");
    progressFile.open("w");
    progressFile.write("Script started at " + new Date().toString());
    progressFile.close();
    
    // Open the document
    var doc = app.open(psdFile);
    
    // Update progress
    progressFile.open("w");
    progressFile.write("Document opened at " + new Date().toString());
    progressFile.close();
    
    // Set resolution to 300 PPI while maintaining original dimensions
    doc.resizeImage(undefined, undefined, 300, ResampleMethod.PRESERVEDETAILS);
    
    // Update progress
    progressFile.open("w");
    progressFile.write("Resolution set at " + new Date().toString());
    progressFile.close();
    
    // JPG Save Options
    var jpgSaveOptions = new JPEGSaveOptions();
    jpgSaveOptions.quality = 12; // Maximum quality (no compression)
    jpgSaveOptions.embedColorProfile = true;
    jpgSaveOptions.formatOptions = FormatOptions.STANDARDBASELINE;
    jpgSaveOptions.matte = MatteType.NONE;
    
    // Output file
    var outputFile = new File("{str(output_file).replace(chr(92), '/')}");
    
    // Update progress
    progressFile.open("w");
    progressFile.write("Starting save at " + new Date().toString());
    progressFile.close();
    
    // Save as JPG
    doc.saveAs(outputFile, jpgSaveOptions, true, Extension.LOWERCASE);
    
    // Update progress
    progressFile.open("w");
    progressFile.write("File saved at " + new Date().toString());
    progressFile.close();
    
    // Close ONLY the current document, NOT Photoshop
    doc.close(SaveOptions.DONOTSAVECHANGES);
    
    // Clean up progress file
    if (progressFile.exists) {{
        progressFile.remove();
    }}
    
    // Success indicator - create a flag file to indicate completion
    var flagFile = new File("{str(output_file).replace(chr(92), '/')}.completed");
    flagFile.open("w");
    flagFile.write("completed at " + new Date().toString());
    flagFile.close();
    
}} catch (error) {{
    // Clean up progress file if exists
    try {{
        var progressFile = new File("{str(output_file).replace(chr(92), '/')}.progress");
        if (progressFile.exists) {{
            progressFile.remove();
        }}
    }} catch (e) {{
        // Ignore cleanup errors
    }}
    
    // Error indicator - create an error file
    var errorFile = new File("{str(output_file).replace(chr(92), '/')}.error");
    errorFile.open("w");
    errorFile.write("Error: " + error.message + " at " + new Date().toString());
    errorFile.close();
    
    // Close document if it was opened
    try {{
        if (doc) doc.close(SaveOptions.DONOTSAVECHANGES);
    }} catch (e) {{
        // Ignore close errors
    }}
}}
'''
        return jsx_content


class ProcessingWorker(QThread):
    progress_updated = Signal(str)
    file_completed = Signal(int, str)
    processing_finished = Signal()
    error_occurred = Signal(str)
    
    def __init__(self, db_manager, files_to_process, output_path, photoshop_path=None):
        super().__init__()
        self.db_manager = db_manager
        self.files_to_process = files_to_process
        self.output_path = output_path
        self.should_stop = False
        self.jsx_generator = JSXGenerator()
        self.mutex = QMutex()
        # Use provided path or fall back to default
        self.photoshop_path = photoshop_path or DEFAULT_PHOTOSHOP_PATH
    
    def stop_processing(self):
        with QMutexLocker(self.mutex):
            self.should_stop = True
            print("🛑 [WORKER] Stop signal received")
    
    def is_stopped(self):
        with QMutexLocker(self.mutex):
            return self.should_stop
    
    def run(self):
        """Main processing loop"""
        try:
            print(f"🚀 [WORKER] Starting processing of {len(self.files_to_process)} files")
            
            for file_id, file_path, status in self.files_to_process:
                if self.is_stopped():
                    print("🛑 [WORKER] Processing stopped by user")
                    self.progress_updated.emit("Processing stopped by user")
                    break
                
                if status == 'completed':
                    print(f"⏭️ [WORKER] Skipping completed file: {Path(file_path).name}")
                    continue
                
                print(f"📁 [WORKER] Processing: {Path(file_path).name}")
                self.progress_updated.emit(f"Processing: {Path(file_path).name}")
                
                # Update status to processing
                self.db_manager.update_file_status(file_id, 'processing')
                # Emit signal to update UI immediately
                self.file_completed.emit(file_id, 'processing')
                
                # Generate JSX script
                jsx_filename = f"convert_{file_id}_{int(time.time())}.jsx"
                jsx_path = Path("script") / jsx_filename
                
                try:
                    # Ensure script folder exists
                    jsx_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    jsx_content = self.jsx_generator.generate_jsx_content(file_path, self.output_path)
                    
                    with open(jsx_path, 'w', encoding='utf-8') as f:
                        f.write(jsx_content)
                    
                    print(f"📝 [WORKER] JSX generated: {jsx_filename}")
                    
                    # Add processing record
                    record_id = self.db_manager.add_processing_record(file_id, str(jsx_path), self.output_path)
                    
                    self.progress_updated.emit(f"JSX generated: {jsx_filename}")
                    
                    # Execute JSX through Photoshop
                    print(f"🖼️ [WORKER] Executing JSX via Photoshop...")
                    self.progress_updated.emit(f"Executing JSX via Photoshop...")
                    
                    try:
                        # Run JSX script in Photoshop and wait for it to complete
                        jsx_path_abs = jsx_path.absolute()
                        
                        print(f"💻 [WORKER] Starting Photoshop process...")
                        # Run JSX script and wait for completion
                        # Launch Photoshop with the generated JSX script
                        process = subprocess.Popen([
                            self.photoshop_path,
                            str(jsx_path_abs)
                        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        
                        # Wait for Photoshop to finish executing the script
                        stdout, stderr = process.communicate()
                        
                        print(f"✅ [WORKER] Photoshop script execution completed")
                        self.progress_updated.emit(f"Photoshop script execution completed")
                    
                    except Exception as e:
                        error_msg = f"Error running Photoshop: {str(e)}"
                        print(f"❌ [WORKER] {error_msg}")
                        self.error_occurred.emit(error_msg)
                        self.db_manager.update_file_status(file_id, 'error')
                        continue
                    
                    # Wait for output file to be created
                    expected_output = Path(self.output_path) / f"{Path(file_path).stem}.jpg"
                    flag_file = Path(str(expected_output) + ".completed")
                    error_file = Path(str(expected_output) + ".error")
                    progress_file = Path(str(expected_output) + ".progress")
                    
                    print(f"⏳ [WORKER] Waiting for Photoshop to process: {expected_output.name}")
                    self.progress_updated.emit(f"Waiting for Photoshop to process: {expected_output.name}")
                    
                    # Monitor for completion or error flags - NO TIMEOUT
                    success = False
                    last_progress = ""
                    
                    while True:
                        if self.is_stopped():
                            print("🛑 [WORKER] Processing stopped by user during monitoring")
                            self.progress_updated.emit("Processing stopped by user")
                            break
                        
                        # Check for progress updates
                        if progress_file.exists():
                            try:
                                with open(progress_file, 'r') as f:
                                    current_progress = f.read().strip()
                                if current_progress != last_progress:
                                    print(f"📊 [PHOTOSHOP] {current_progress}")
                                    self.progress_updated.emit(f"Photoshop: {current_progress}")
                                    last_progress = current_progress
                            except:
                                pass
                        
                        if flag_file.exists():
                            # Update status to saving image
                            self.db_manager.update_file_status(file_id, 'saving image')
                            self.file_completed.emit(file_id, 'saving image')
                            print(f"💾 [WORKER] Saving image: {Path(file_path).name}")
                            self.progress_updated.emit(f"Saving image: {Path(file_path).name}")
                            
                            # Success - clean up flag file
                            try:
                                flag_file.unlink()
                            except:
                                pass
                            success = True
                            print(f"🎉 [WORKER] Export completed successfully")
                            self.progress_updated.emit(f"Export completed successfully")
                            break
                        
                        if error_file.exists():
                            # Error occurred
                            try:
                                with open(error_file, 'r') as f:
                                    error_msg = f.read()
                                error_file.unlink()
                            except:
                                error_msg = "Unknown error occurred"
                            
                            print(f"❌ [PHOTOSHOP] Error: {error_msg}")
                            self.error_occurred.emit(f"Photoshop error: {error_msg}")
                            self.db_manager.update_file_status(file_id, 'error')
                            self.file_completed.emit(file_id, 'error')
                            success = False
                            break
                        
                        # Check stop condition more frequently
                        if self.is_stopped():
                            break
                            
                        # Wait 1 second before checking again
                        time.sleep(1)
                    
                    if success and expected_output.exists():
                        # Output detected and completed successfully
                        # Clean up progress file if exists
                        try:
                            if progress_file.exists():
                                progress_file.unlink()
                        except:
                            pass
                        
                        # Clean up JSX immediately after success
                        try:
                            jsx_path.unlink()
                            print(f"🧹 [WORKER] JSX cleaned up: {jsx_filename}")
                            self.progress_updated.emit(f"JSX cleaned up: {jsx_filename}")
                        except Exception as e:
                            print(f"⚠️ [WORKER] Warning: Could not delete JSX: {e}")
                            self.progress_updated.emit(f"Warning: Could not delete JSX: {e}")
                        
                        # Update status
                        self.db_manager.update_file_status(file_id, 'completed')
                        self.db_manager.update_processing_status(record_id, 'completed')
                        self.file_completed.emit(file_id, 'completed')
                        print(f"✅ [WORKER] Completed: {Path(file_path).name}")
                        self.progress_updated.emit(f"Completed: {Path(file_path).name}")
                        
                        # Small delay before next file to ensure cleanup
                        time.sleep(1)
                    else:
                        # Stopped by user or error
                        # Clean up progress file if exists
                        try:
                            if progress_file.exists():
                                progress_file.unlink()
                        except:
                            pass
                        
                        if self.is_stopped():
                            print(f"🔄 [WORKER] File stopped: {Path(file_path).name}")
                            self.db_manager.update_file_status(file_id, 'stopped')
                            self.db_manager.update_processing_status(record_id, 'stopped')
                            self.file_completed.emit(file_id, 'stopped')
                        else:
                            print(f"❌ [WORKER] File error: {Path(file_path).name}")
                            self.db_manager.update_file_status(file_id, 'error')
                            self.db_manager.update_processing_status(record_id, 'error')
                            self.file_completed.emit(file_id, 'error')
                            self.error_occurred.emit(f"Error processing: {expected_output.name}")
                        
                        # Clean up JSX even on error/stop
                        try:
                            jsx_path.unlink()
                        except:
                            pass
                
                except Exception as e:
                    error_msg = f"Error processing {Path(file_path).name}: {str(e)}"
                    print(f"❌ [WORKER] {error_msg}")
                    self.db_manager.update_file_status(file_id, 'error')
                    self.error_occurred.emit(error_msg)
                
                # Small delay between files
                if not self.is_stopped():
                    time.sleep(0.5)
            
            print("🏁 [WORKER] Processing finished")
            self.processing_finished.emit()
            
        except Exception as e:
            error_msg = f"Critical error in processing: {str(e)}"
            print(f"💥 [WORKER] {error_msg}")
            self.error_occurred.emit(error_msg)


class DropArea(QFrame):
    files_dropped = Signal(list)
    
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setFrameStyle(QFrame.Box | QFrame.Raised)
        self.setLineWidth(1)
        self.setMinimumHeight(100)
        self.drag_active = False
        
        # Set object name for specific styling
        self.setObjectName("DropAreaFrame")
        
        # Apply custom styling for DnD area only using object name selector
        self.setStyleSheet("""
            QFrame#DropAreaFrame {
                border: 2px dashed #cccccc;
                border-radius: 8px;
                background-color: transparent;
            }
            QFrame#DropAreaFrame:hover {
                border-color: #4CAF50;
                background-color: rgba(76, 175, 80, 0.1);
            }
        """)
        
        layout = QVBoxLayout()
        self.label = QLabel("Drag & Drop PSD files here\nor click to browse")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        self.setLayout(layout)
    
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            self.drag_active = True
            self.setStyleSheet("""
                QFrame#DropAreaFrame {
                    border: 2px dashed #4CAF50;
                    border-radius: 8px;
                    background-color: rgba(76, 175, 80, 0.2);
                }
            """)
            event.acceptProposedAction()
    
    def dragLeaveEvent(self, event):
        self.drag_active = False
        self.setStyleSheet("""
            QFrame#DropAreaFrame {
                border: 2px dashed #cccccc;
                border-radius: 8px;
                background-color: transparent;
            }
            QFrame#DropAreaFrame:hover {
                border-color: #4CAF50;
                background-color: rgba(76, 175, 80, 0.1);
            }
        """)
    
    def dropEvent(self, event: QDropEvent):
        self.drag_active = False
        self.setStyleSheet("""
            QFrame#DropAreaFrame {
                border: 2px dashed #cccccc;
                border-radius: 8px;
                background-color: transparent;
            }
            QFrame#DropAreaFrame:hover {
                border-color: #4CAF50;
                background-color: rgba(76, 175, 80, 0.1);
            }
        """)
        
        files = []
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith('.psd'):
                files.append(file_path)
        
        if files:
            self.files_dropped.emit(files)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            files, _ = QFileDialog.getOpenFileNames(
                self, "Select PSD Files", "", "PSD Files (*.psd)"
            )
            if files:
                self.files_dropped.emit(files)


class PSDToIMGConverter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db_manager = DatabaseManager()
        self.processing_worker = None
        # config holder and path
        self.config_path = Path(__file__).parent / 'config.json'
        self.photoshop_path = DEFAULT_PHOTOSHOP_PATH
        # load existing config before building UI so values can be shown
        self.load_config()
        self.init_ui()
        self.load_data()

    def load_config(self):
        """Load JSON configuration (photoshop path, etc.)"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    pp = cfg.get('photoshop_path')
                    if pp:
                        self.photoshop_path = pp
        except Exception as e:
            print(f"⚠️ [CONFIG] Could not load config: {e}")

    def save_config(self):
        """Persist current configuration to JSON"""
        try:
            cfg = {
                'photoshop_path': self.photoshop_path
            }
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2)
            print(f"✅ [CONFIG] Saved config to {self.config_path}")
        except Exception as e:
            print(f"❌ [CONFIG] Failed saving config: {e}")
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("PSD to IMG Converter")
        self.setGeometry(100, 100, 900, 700)
        
        # Set window always on top
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        
        # Control buttons section (moved to top)
        controls_layout = QHBoxLayout()
        
        self.clear_button = QPushButton("Clear All")
        self.clear_button.setIcon(qta.icon('fa5s.trash'))
        self.clear_button.clicked.connect(self.clear_all)
        self.clear_button.setMinimumHeight(40)
        controls_layout.addWidget(self.clear_button)
        
        controls_layout.addStretch()
        
        # Single dynamic processing button (bigger, on the right)
        self.processing_button = QPushButton("Start Processing")
        self.processing_button.setIcon(qta.icon('fa5s.play'))
        self.processing_button.clicked.connect(self.toggle_processing)
        self.processing_button.setMinimumHeight(50)
        self.processing_button.setMinimumWidth(180)
        self.processing_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        controls_layout.addWidget(self.processing_button)
        
        main_layout.addLayout(controls_layout)
        
        # Path selection section
        path_group = QGroupBox("Folder Selection")
        path_layout = QVBoxLayout()
        
        # Source folder selection
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("Source Folder:"))
        self.source_path_edit = QLineEdit()
        self.source_path_edit.setPlaceholderText("Select source folder containing PSD files...")
        self.source_path_edit.setReadOnly(True)
        source_layout.addWidget(self.source_path_edit)
        
        self.paste_source_btn = QPushButton("Paste")
        self.paste_source_btn.setIcon(qta.icon('fa5s.paste'))
        self.paste_source_btn.clicked.connect(self.paste_source_folder)
        source_layout.addWidget(self.paste_source_btn)
        
        self.select_source_btn = QPushButton("Select Source Folder")
        self.select_source_btn.setIcon(qta.icon('fa5s.folder-open'))
        self.select_source_btn.clicked.connect(self.select_source_folder)
        source_layout.addWidget(self.select_source_btn)
        
        path_layout.addLayout(source_layout)
        
        # Output folder selection
        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("Output Folder:"))
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Select output folder for converted images...")
        self.output_path_edit.setReadOnly(True)
        output_layout.addWidget(self.output_path_edit)
        
        self.paste_output_btn = QPushButton("Paste")
        self.paste_output_btn.setIcon(qta.icon('fa5s.paste'))
        self.paste_output_btn.clicked.connect(self.paste_output_folder)
        output_layout.addWidget(self.paste_output_btn)
        
        self.select_output_btn = QPushButton("Select Output Folder")
        self.select_output_btn.setIcon(qta.icon('fa5s.folder'))
        self.select_output_btn.clicked.connect(self.select_output_folder)
        output_layout.addWidget(self.select_output_btn)
        
        path_layout.addLayout(output_layout)
        path_group.setLayout(path_layout)
        main_layout.addWidget(path_group)

        # Photoshop exe selection
        photoshop_layout = QHBoxLayout()
        photoshop_layout.addWidget(QLabel("Photoshop Executable:"))
        self.photoshop_path_edit = QLineEdit()
        self.photoshop_path_edit.setPlaceholderText("Select Photoshop executable...")
        self.photoshop_path_edit.setReadOnly(True)
        photoshop_layout.addWidget(self.photoshop_path_edit)

        self.paste_photoshop_btn = QPushButton("Paste")
        self.paste_photoshop_btn.setIcon(qta.icon('fa5s.paste'))
        self.paste_photoshop_btn.clicked.connect(self.paste_photoshop_path)
        photoshop_layout.addWidget(self.paste_photoshop_btn)

        self.select_photoshop_btn = QPushButton("Select Photoshop")
        self.select_photoshop_btn.setIcon(qta.icon('fa5s.desktop'))
        self.select_photoshop_btn.clicked.connect(self.select_photoshop_path)
        photoshop_layout.addWidget(self.select_photoshop_btn)

        main_layout.addLayout(photoshop_layout)
        
        # Top section: Drop area and output path
        top_layout = QVBoxLayout()
        
        # Drop area
        self.drop_area = DropArea()
        self.drop_area.files_dropped.connect(self.add_files)
        top_layout.addWidget(self.drop_area)
        
        main_layout.addLayout(top_layout)
        
        # Splitter for table and log
        splitter = QSplitter(Qt.Vertical)
        
        # File table
        self.file_table = QTableWidget()
        self.file_table.setColumnCount(3)
        self.file_table.setHorizontalHeaderLabels(["File Path", "Status", "Actions"])
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.file_table.setColumnWidth(1, 140)  # Lebarkan kolom status
        self.file_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.file_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        splitter.addWidget(self.file_table)
        
        # Log area
        self.log_area = QTextEdit()
        self.log_area.setMaximumHeight(150)
        splitter.addWidget(self.log_area)
        
        main_layout.addWidget(splitter)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)
        
        # Initialize button states
        self.processing_button.setEnabled(False)
        # Center window on screen
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        window_geometry = self.frameGeometry()
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())
    
    def add_files(self, file_paths):
        """Add files to the processing queue"""
        print(f"📥 [UI] Adding {len(file_paths)} files to queue")
        
        added_count = 0
        for file_path in file_paths:
            file_id = self.db_manager.add_file_path(file_path)
            if file_id:
                added_count += 1
                print(f"✅ [UI] Added file: {Path(file_path).name}")
            else:
                print(f"⚠️ [UI] File already exists: {Path(file_path).name}")
        
        if added_count > 0:
            self.load_data()
            message = f"Added {added_count} new files to queue"
            print(f"📊 [UI] {message}")
            self.log(message)
        else:
            message = "No new files added (files may already exist in queue)"
            print(f"ℹ️ [UI] {message}")
            self.log(message)
    
    def toggle_processing(self):
        """Toggle between start, stop, and continue processing based on current state"""
        if self.processing_worker and self.processing_worker.isRunning():
            # Currently processing, so stop
            self.stop_processing()
        else:
            # Not processing, check file states to decide action
            files = self.db_manager.get_file_paths()
            statuses = [status for _, _, status in files]
            
            has_stopped = any(s in statuses for s in ['stopped', 'error'])
            has_completed = any(s in statuses for s in ['completed'])
            has_draft = any(s in statuses for s in ['draft'])
            
            print(f"🔍 [UI] Toggle processing - has_stopped: {has_stopped}, has_completed: {has_completed}, has_draft: {has_draft}")
            
            if (has_stopped or has_completed) and (has_draft or has_stopped):
                # Has some processed files and remaining files - continue processing
                print("🟡 [UI] Triggering continue processing")
                self.continue_processing()
            else:
                # Only draft files - start normal processing
                print("🟢 [UI] Triggering start processing")
                self.start_processing()
    
    def update_start_stop_button(self, is_processing):
        """Update start/stop button appearance based on processing state"""
        if is_processing:
            self.processing_button.setText("Stop Processing")
            self.processing_button.setIcon(qta.icon('fa5s.stop'))
            self.processing_button.setStyleSheet("""
                QPushButton {
                    background-color: #f44336;
                    color: white;
                    font-weight: bold;
                    font-size: 14px;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #d32f2f;
                }
                QPushButton:disabled {
                    background-color: #cccccc;
                    color: #666666;
                }
            """)
        else:
            # Update based on file conditions when not processing
            self.update_processing_button_state()
    
    def update_processing_button_state(self):
        """Update processing button state based on file conditions"""
        files = self.db_manager.get_file_paths()
        if not files:
            # No files
            self.processing_button.setText("Start Processing")
            self.processing_button.setIcon(qta.icon('fa5s.play'))
            self.processing_button.setEnabled(False)
            self.processing_button.setStyleSheet("""
                QPushButton {
                    background-color: #cccccc;
                    color: #666666;
                    font-weight: bold;
                    font-size: 14px;
                    border: none;
                    border-radius: 8px;
                }
            """)
            return
        
        statuses = [status for _, _, status in files]
        has_draft = any(s in statuses for s in ['draft'])
        has_stopped = any(s in statuses for s in ['stopped', 'error'])
        has_completed = any(s in statuses for s in ['completed'])
        has_non_completed = any(s != 'completed' for s in statuses)
        
        print(f"🔍 [UI] File statuses: {set(statuses)}")
        print(f"🔍 [UI] has_draft: {has_draft}, has_stopped: {has_stopped}, has_completed: {has_completed}, has_non_completed: {has_non_completed}")
        
        if not has_non_completed:
            # All completed
            self.processing_button.setText("All Completed")
            self.processing_button.setIcon(qta.icon('fa5s.check'))
            self.processing_button.setEnabled(False)
            self.processing_button.setStyleSheet("""
                QPushButton {
                    background-color: #cccccc;
                    color: #666666;
                    font-weight: bold;
                    font-size: 14px;
                    border: none;
                    border-radius: 8px;
                }
            """)
        elif (has_stopped or has_completed) and has_non_completed:
            # Has some processed files and remaining files - show continue
            print("🟡 [UI] Setting button to Continue Processing")
            self.processing_button.setText("Continue Processing")
            self.processing_button.setIcon(qta.icon('fa5s.play-circle'))
            self.processing_button.setEnabled(True)
            self.processing_button.setStyleSheet("""
                QPushButton {
                    background-color: #FF9800;
                    color: white;
                    font-weight: bold;
                    font-size: 14px;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #F57C00;
                }
            """)
        else:
            # Only draft files - show start
            print("🟢 [UI] Setting button to Start Processing")
            self.processing_button.setText("Start Processing")
            self.processing_button.setIcon(qta.icon('fa5s.play'))
            self.processing_button.setEnabled(True)
            self.processing_button.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    font-weight: bold;
                    font-size: 14px;
                    border: none;
                    border-radius: 8px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
            """)

    def paste_source_folder(self):
        """Paste folder path from clipboard for source folder"""
        clipboard = QApplication.clipboard()
        folder_path = clipboard.text().strip()
        
        if folder_path and Path(folder_path).exists() and Path(folder_path).is_dir():
            self.source_path_edit.setText(folder_path)
            # Save source path to database
            self.db_manager.set_setting('source_path', folder_path)
            self.load_psd_files_from_folder(folder_path)
            self.log(f"Source folder pasted: {folder_path}")
        else:
            QMessageBox.warning(self, "Warning", "Clipboard does not contain a valid folder path!")
    
    def paste_output_folder(self):
        """Paste folder path from clipboard for output folder"""
        clipboard = QApplication.clipboard()
        folder_path = clipboard.text().strip()
        
        if folder_path and Path(folder_path).exists() and Path(folder_path).is_dir():
            self.output_path_edit.setText(folder_path)
            # Save output path to database
            self.db_manager.set_setting('output_path', folder_path)
            self.log(f"Output folder pasted: {folder_path}")
        else:
            QMessageBox.warning(self, "Warning", "Clipboard does not contain a valid folder path!")

    def paste_photoshop_path(self):
        """Paste Photoshop executable path from clipboard and save to config"""
        clipboard = QApplication.clipboard()
        exe_path = clipboard.text().strip()
        if exe_path and Path(exe_path).exists():
            self.photoshop_path = exe_path
            self.photoshop_path_edit.setText(exe_path)
            self.save_config()
            self.log(f"Photoshop path pasted: {exe_path}")
        else:
            QMessageBox.warning(self, "Warning", "Clipboard does not contain a valid executable path!")

    def select_photoshop_path(self):
        """Select Photoshop executable manually"""
        file, _ = QFileDialog.getOpenFileName(self, "Select Photoshop Executable", "", "Executables (*.exe);;All Files (*)")
        if file:
            self.photoshop_path = file
            self.photoshop_path_edit.setText(file)
            self.save_config()
            self.log(f"Photoshop path selected: {file}")
    
    def select_source_folder(self):
        """Select source folder containing PSD files"""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Source Folder", ""
        )
        if folder:
            self.source_path_edit.setText(folder)
            # Save source path to database
            self.db_manager.set_setting('source_path', folder)
            self.load_psd_files_from_folder(folder)
            self.log(f"Source folder selected: {folder}")
    
    def select_output_folder(self):
        """Select output folder for converted images"""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", ""
        )
        if folder:
            self.output_path_edit.setText(folder)
            # Update output path in database
            self.db_manager.set_setting('output_path', folder)
            self.log(f"Output folder selected: {folder}")
    
    def load_psd_files_from_folder(self, folder_path):
        """Load all PSD files from selected folder"""
        psd_files = []
        folder = Path(folder_path)
        
        # Find all PSD files in the folder and subfolders
        for psd_file in folder.rglob("*.psd"):
            psd_files.append(str(psd_file))
        
        if psd_files:
            self.add_files(psd_files)
            self.log(f"Found {len(psd_files)} PSD files in folder")
        else:
            self.log("No PSD files found in selected folder")
    
    def browse_output_folder(self):
        """Browse for output folder"""
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.db_manager.set_setting('output_path', folder)
            self.output_path_edit.setText(folder)
            self.log(f"Output path set to: {folder}")
    
    def load_data(self):
        """Load data from database and update UI"""
        print("🔄 [UI] Loading data from database...")
        
        # Load source path
        source_path = self.db_manager.get_setting('source_path', '')
        if source_path:
            self.source_path_edit.setText(source_path)
        
        # Load output path
        output_path = self.db_manager.get_setting('output_path', '')
        if output_path:
            self.output_path_edit.setText(output_path)

        # Load photoshop path into UI (from config)
        try:
            if hasattr(self, 'photoshop_path_edit'):
                self.photoshop_path_edit.setText(self.photoshop_path or "")
        except Exception:
            pass
        
        # Load files
        files = self.db_manager.get_file_paths()
        self.file_table.setRowCount(len(files))
        
        print(f"📊 [UI] Loaded {len(files)} files from database")
        
        for row, (file_id, file_path, status) in enumerate(files):
            # File path column
            self.file_table.setItem(row, 0, QTableWidgetItem(file_path))
            
            # Status column with custom widget
            status_widget = StatusWidget(status)
            self.file_table.setCellWidget(row, 1, status_widget)
            
            # Remove button
            remove_button = QPushButton()
            remove_button.setIcon(qta.icon('fa5s.times'))
            remove_button.setToolTip("Remove file from queue")
            remove_button.clicked.connect(lambda checked, fid=file_id: self.remove_file(fid))
            self.file_table.setCellWidget(row, 2, remove_button)
            
            print(f"📋 [UI] Row {row+1}: {Path(file_path).name} - Status: {status}")
        
        # Update button states based on file statuses
        self.update_button_states(files)
        
        # Update progressbar to show current progress
        if files:
            total_files = len(files)
            completed_files = len([f for f in files if f[2] == 'completed'])
            
            # Only show progressbar if processing is running or there are completed files
            if (self.processing_worker and self.processing_worker.isRunning()) or completed_files > 0:
                    self.progress_bar.setVisible(True)
                    self.progress_bar.setMaximum(total_files)
                    self.progress_bar.setValue(completed_files)
                    percentage = (completed_files / total_files * 100) if total_files > 0 else 0
                    progress_text = f"{completed_files}/{total_files} ({percentage:.0f}%)"
                    self.progress_bar.setFormat(progress_text)
                    print(f"📊 [UI] Current progress: {progress_text}")
            else:
                self.progress_bar.setVisible(False)
    
    def update_button_states(self, files):
        """Update button states based on current file statuses"""
        # Check if processing is currently running
        if self.processing_worker and self.processing_worker.isRunning():
            return  # Don't change button states while processing
        
        # Update processing button based on file states
        self.update_processing_button_state()
    
    def remove_file(self, file_id):
        """Remove file from database"""
        conn = sqlite3.connect(self.db_manager.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM file_paths WHERE id = ?", (file_id,))
        cursor.execute("DELETE FROM processing_status WHERE file_id = ?", (file_id,))
        conn.commit()
        conn.close()
        self.load_data()
        self.log(f"File removed from queue")
    
    def start_processing(self):
        """Start batch processing for all files"""
        print("🚀 [UI] Start processing requested")
        
        output_path = self.output_path_edit.text().strip()
        if not output_path:
            print("⚠️ [UI] No output path selected")
            QMessageBox.warning(self, "Warning", "Please select an output folder first!")
            return

        # Validate photoshop executable
        if not self.photoshop_path or not Path(self.photoshop_path).exists():
            QMessageBox.warning(self, "Warning", "Please select a valid Photoshop executable first!")
            return
        
        files = self.db_manager.get_file_paths()
        # Process all files except completed ones
        pending_files = [(fid, path, status) for fid, path, status in files if status != 'completed']
        
        print(f"📋 [UI] Found {len(pending_files)} files to process")
        
        if not pending_files:
            print("ℹ️ [UI] No files to process")
            QMessageBox.information(self, "Info", "No files to process!")
            return
        
        self._start_worker(pending_files, "Started batch processing...")
    
    def continue_processing(self):
        """Continue processing from stopped/error files"""
        print("🔄 [UI] Continue processing requested")
        
        output_path = self.output_path_edit.text().strip()
        if not output_path:
            print("⚠️ [UI] No output path selected")
            QMessageBox.warning(self, "Warning", "Please select an output folder first!")
            return

        # Validate photoshop executable
        if not self.photoshop_path or not Path(self.photoshop_path).exists():
            QMessageBox.warning(self, "Warning", "Please select a valid Photoshop executable first!")
            return
        
        files = self.db_manager.get_file_paths()
        # Process all non-completed files (continue from where stopped)
        continue_files = [(fid, path, status) for fid, path, status in files if status != 'completed']
        
        print(f"📋 [UI] Found {len(continue_files)} files to continue processing")
        
        if not continue_files:
            print("ℹ️ [UI] No files to continue - all completed")
            QMessageBox.information(self, "Info", "No files to continue - all completed!")
            return
        
        self._start_worker(continue_files, "Continuing processing from stopped point...")
    
    def _start_worker(self, files_to_process, log_message):
        """Internal method to start the processing worker"""
        print(f"⚙️ [UI] Starting worker with {len(files_to_process)} files")
        
        self.processing_button.setEnabled(True)
        self.update_start_stop_button(True)  # Switch to stop mode
        
        # Set progressbar based on total files vs completed files
        all_files = self.db_manager.get_file_paths()
        total_files = len(all_files)
        completed_files = len([f for f in all_files if f[2] == 'completed'])
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(total_files)
        self.progress_bar.setValue(completed_files)
        
        print(f"📊 [UI] Progress: {completed_files}/{total_files} files completed")
        
        self.processing_worker = ProcessingWorker(self.db_manager, files_to_process, 
                              self.output_path_edit.text().strip(),
                              photoshop_path=self.photoshop_path)
        self.processing_worker.progress_updated.connect(self.log)
        self.processing_worker.file_completed.connect(self.on_file_completed)
        self.processing_worker.processing_finished.connect(self.on_processing_finished)
        self.processing_worker.error_occurred.connect(self.log)
        self.processing_worker.start()
        
        print(f"✅ [UI] Worker started successfully")
        self.log(log_message)
    
    def stop_processing(self):
        """Stop batch processing gracefully"""
        print("🛑 [UI] Stop processing requested")
        
        if self.processing_worker and self.processing_worker.isRunning():
            self.log("Stopping processing...")
            self.processing_worker.stop_processing()
            
            # Give worker some time to stop gracefully
            if not self.processing_worker.wait(3000):  # Wait 3 seconds
                print("⚠️ [UI] Worker didn't stop gracefully, terminating...")
                self.processing_worker.terminate()
                if not self.processing_worker.wait(2000):  # Wait 2 more seconds
                    print("💥 [UI] Force killing worker...")
                    self.processing_worker.kill()
            
            # Cleanup worker
            self.processing_worker.deleteLater()
            self.processing_worker = None
            print("✅ [UI] Worker stopped successfully")
            
            # Reset UI state
            self.update_start_stop_button(False)  # Switch back to start mode
            self.processing_button.setEnabled(True)
            self.progress_bar.setVisible(False)
            self.load_data()
        else:
            print("ℹ️ [UI] No processing worker running")
            self.log("No processing currently running")
    
    def on_file_completed(self, file_id, status):
        """Handle file completion"""
        print(f"✅ [UI] File completed: ID {file_id}, Status: {status}")
        self.load_data()
        
        # Update progressbar based on actual completed count
        all_files = self.db_manager.get_file_paths()
        total_files = len(all_files)
        completed_files = len([f for f in all_files if f[2] == 'completed'])
        
        self.progress_bar.setMaximum(total_files)
        self.progress_bar.setValue(completed_files)
        percentage = (completed_files / total_files * 100) if total_files > 0 else 0
        progress_text = f"{completed_files}/{total_files} ({percentage:.0f}%)"
        self.progress_bar.setFormat(progress_text)
        print(f"📊 [UI] Progress updated: {progress_text}")
        self.log(f"Progress: {progress_text}")
    
    def on_processing_finished(self):
        """Handle processing completion"""
        print("🏁 [UI] Processing finished")
        
        self.update_start_stop_button(False)  # Switch back to start mode
        self.processing_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        # Properly cleanup worker thread
        if self.processing_worker:
            self.processing_worker.quit()
            self.processing_worker.wait()  # Wait for thread to finish
            self.processing_worker.deleteLater()
            self.processing_worker = None
            print("🧹 [UI] Worker thread cleaned up")
        
        self.load_data()
        self.log("Processing finished!")
    
    def clear_all(self):
        """Clear all files from the list and database - start new session"""
        reply = QMessageBox.question(
            self, 
            "Clear All Files", 
            "This will remove ALL files from the database and start a new session.\nAre you sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(self.db_manager.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM file_paths")
            cursor.execute("DELETE FROM processing_status")
            conn.commit()
            conn.close()
            
            # Clear path fields
            self.source_path_edit.clear()
            self.output_path_edit.clear()
            
            # Clear paths from database
            self.db_manager.set_setting('source_path', '')
            self.db_manager.set_setting('output_path', '')
            
            self.load_data()
            self.log("All files and paths cleared - New session started")
    
    def clear_completed(self):
        """Clear completed files from the list"""
        conn = sqlite3.connect(self.db_manager.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM file_paths WHERE status = 'completed'")
        conn.commit()
        conn.close()
        self.load_data()
        self.log("Cleared completed files")
    
    def log(self, message):
        """Add message to log area with icons"""
        timestamp = time.strftime("%H:%M:%S")
        
        # Add appropriate icon based on message content
        if "completed" in message.lower() or "finished" in message.lower():
            icon_text = "✅"
        elif "error" in message.lower() or "failed" in message.lower():
            icon_text = "❌"
        elif "warning" in message.lower():
            icon_text = "⚠️"
        elif "stopped" in message.lower() or "stopping" in message.lower():
            icon_text = "🛑"
        elif "processing" in message.lower() or "executing" in message.lower():
            icon_text = "⚙️"
        elif "jsx" in message.lower():
            icon_text = "📝"
        elif "photoshop" in message.lower():
            icon_text = "🖼️"
        elif "waiting" in message.lower():
            icon_text = "⏳"
        elif "added" in message.lower():
            icon_text = "📥"
        elif "cleaned" in message.lower():
            icon_text = "🧹"
        elif "generated" in message.lower():
            icon_text = "📝"
        elif "export" in message.lower():
            icon_text = "💾"
        else:
            icon_text = "ℹ️"
        
        formatted_message = f"[{timestamp}] {icon_text} {message}"
        self.log_area.append(formatted_message)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())
        
        # Also print to console
        print(f"📋 [LOG] {message}")


def main():
    # On Windows set an explicit AppUserModelID so the taskbar uses our app icon/grouping
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("com.example.psdtoimg")
        except Exception:
            pass

    app = QApplication(sys.argv)
    
    # Build a multi-size application icon from the QtAwesome glyph so Windows can show it in the taskbar
    base_icon = qta.icon('fa5s.image', color="#FF7300")
    app_icon = QIcon()
    for size in (16, 32, 48, 256):
        pm = base_icon.pixmap(size, size)
        app_icon.addPixmap(pm)

    # Apply icon to both the QApplication and the main window
    app.setWindowIcon(app_icon)

    window = PSDToIMGConverter()
    window.setWindowIcon(app_icon)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()