import os
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QSplitter, QTextEdit
)
from PyQt6.QtCore import Qt
import pyqtgraph as pg

# Local imports
from analyzer.parser import TelemetryParser
from analyzer.engine import SetupAnalyzer

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("iRacing Telemetry Setup Analyzer")
        self.resize(1200, 800)
        
        self.parser = TelemetryParser()
        self.analyzer = None
        
        self.setup_ui()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # --- Top Bar ---
        top_bar = QHBoxLayout()
        self.btn_load = QPushButton("Load .ibt File")
        self.btn_load.clicked.connect(self.load_file)
        
        self.lbl_file = QLabel("No file loaded.")
        self.lbl_file.setStyleSheet("color: gray;")
        
        top_bar.addWidget(self.btn_load)
        top_bar.addWidget(self.lbl_file)
        top_bar.addStretch()
        
        main_layout.addLayout(top_bar)
        
        # --- Main Splitter ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # Left Panel: Channels & Recommendations
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_recs = QLabel("Setup Recommendations:")
        self.lbl_recs.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        self.txt_recs = QTextEdit()
        self.txt_recs.setReadOnly(True)
        self.txt_recs.setPlaceholderText("Recommendations will appear here after loading a file...")
        
        left_layout.addWidget(self.lbl_recs)
        left_layout.addWidget(self.txt_recs)
        
        # Right Panel: Graphs
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # pyqtgraph setup
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')
        
        self.plot_widget = pg.GraphicsLayoutWidget()
        right_layout.addWidget(self.plot_widget)
        
        # Add plots
        self.p1 = self.plot_widget.addPlot(title="Speed (m/s)")
        self.plot_widget.nextRow()
        self.p2 = self.plot_widget.addPlot(title="Inputs (Throttle / Brake)")
        self.p2.setXLink(self.p1) # Link X axis (Time or Index)
        
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 800])

    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open iRacing Telemetry", "", "Telemetry Files (*.ibt);;All Files (*)"
        )
        if file_path:
            self.lbl_file.setText(f"Loading: {os.path.basename(file_path)}...")
            self.lbl_file.setStyleSheet("color: blue;")
            QApplication.processEvents() # Force UI update
            
            try:
                df, session_info = self.parser.load_file(file_path)
                self.lbl_file.setText(f"Loaded: {os.path.basename(file_path)}")
                self.lbl_file.setStyleSheet("color: green;")
                
                self.update_graphs(df)
                self.generate_recommendations(df, session_info)
                
            except Exception as e:
                self.lbl_file.setText("Error loading file.")
                self.lbl_file.setStyleSheet("color: red;")
                self.txt_recs.setPlainText(f"Failed to parse file:\n{str(e)}")

    def update_graphs(self, df):
        self.p1.clear()
        self.p2.clear()
        
        if df is None or df.empty:
            return
            
        # Time axis could be SessionTime if available, else index
        x = df['SessionTime'].values if 'SessionTime' in df.columns else df.index.values
        
        if 'Speed' in df.columns:
            self.p1.plot(x, df['Speed'].values, pen='b', name='Speed')
            
        if 'Throttle' in df.columns:
            self.p2.plot(x, df['Throttle'].values, pen='g', name='Throttle')
        if 'Brake' in df.columns:
            self.p2.plot(x, df['Brake'].values, pen='r', name='Brake')

    def generate_recommendations(self, df, session_info):
        self.analyzer = SetupAnalyzer(df, session_info)
        recs = self.analyzer.run_analysis()
        
        self.txt_recs.clear()
        if not recs:
            self.txt_recs.append("No actionable recommendations found.")
        else:
            for i, rec in enumerate(recs, 1):
                self.txt_recs.append(f"{i}. {rec}\n")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
