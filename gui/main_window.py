import os
import sys
import pandas as pd
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QSplitter, QTextEdit,
    QGroupBox, QGridLayout
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
        self.resize(1400, 900)
        
        self.parser = TelemetryParser()
        self.analyzer = None
        self.session_info = None
        self.laps = []
        
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
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.main_splitter)
        
        # 1. Left Panel: Laps List
        self.laps_list = QListWidget()
        self.laps_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.laps_list.itemSelectionChanged.connect(self.on_lap_selected)
        
        laps_container = QWidget()
        laps_layout = QVBoxLayout(laps_container)
        laps_layout.addWidget(QLabel("<b>Detected Laps</b>"))
        laps_layout.addWidget(self.laps_list)
        
        # 2. Middle Panel: Summary & Recommendations
        analysis_panel = QWidget()
        analysis_layout = QVBoxLayout(analysis_panel)
        analysis_layout.setContentsMargins(5, 0, 5, 0)
        
        # Summary Dashboard
        self.summary_group = QGroupBox("Lap Summary")
        summary_grid = QGridLayout(self.summary_group)
        
        self.lbl_lap_time = QLabel("Time: --:--.---")
        self.lbl_max_speed = QLabel("Max Speed: --- km/h")
        self.lbl_max_lat_g = QLabel("Max Lat G: -.-- G")
        
        self.lbl_tire_lf = QLabel("LF: ---°C")
        self.lbl_tire_rf = QLabel("RF: ---°C")
        self.lbl_tire_lr = QLabel("LR: ---°C")
        self.lbl_tire_rr = QLabel("RR: ---°C")
        
        summary_grid.addWidget(self.lbl_lap_time, 0, 0)
        summary_grid.addWidget(self.lbl_max_speed, 0, 1)
        summary_grid.addWidget(self.lbl_max_lat_g, 0, 2)
        summary_grid.addWidget(QLabel("<b>Avg Tire Temps:</b>"), 1, 0)
        summary_grid.addWidget(self.lbl_tire_lf, 2, 0)
        summary_grid.addWidget(self.lbl_tire_rf, 2, 1)
        summary_grid.addWidget(self.lbl_tire_lr, 3, 0)
        summary_grid.addWidget(self.lbl_tire_rr, 3, 1)
        
        analysis_layout.addWidget(self.summary_group)
        
        # Recommendations
        analysis_layout.addWidget(QLabel("<b>Setup Recommendations:</b>"))
        self.txt_recs = QTextEdit()
        self.txt_recs.setReadOnly(True)
        self.txt_recs.setPlaceholderText("Select a lap to see analysis...")
        analysis_layout.addWidget(self.txt_recs)
        
        # 3. Right Panel: Graphs
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # pyqtgraph setup
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')
        pg.setConfigOption('antialias', True)
        
        self.plot_widget = pg.GraphicsLayoutWidget()
        right_layout.addWidget(self.plot_widget)
        
        # Add plots
        self.p1 = self.plot_widget.addPlot(title="Speed (km/h)")
        self.plot_widget.nextRow()
        self.p2 = self.plot_widget.addPlot(title="Inputs (Throttle / Brake)")
        self.p2.setXLink(self.p1)
        
        self.main_splitter.addWidget(laps_container)
        self.main_splitter.addWidget(analysis_panel)
        self.main_splitter.addWidget(right_panel)
        self.main_splitter.setSizes([200, 350, 850])

    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open iRacing Telemetry", "", "Telemetry Files (*.ibt);;All Files (*)"
        )
        if file_path:
            self.lbl_file.setText(f"Loading: {os.path.basename(file_path)}...")
            self.lbl_file.setStyleSheet("color: blue;")
            QApplication.processEvents()
            
            try:
                self.laps, self.session_info = self.parser.load_file(file_path)
                
                self.laps_list.clear()
                if not self.laps:
                    self.lbl_file.setText("No laps detected in file.")
                    self.lbl_file.setStyleSheet("color: orange;")
                    return

                for lap in self.laps:
                    status = "Flying" if lap.is_flying else "Out/In"
                    time_str = self.format_time(lap.lap_time)
                    item_text = f"Lap {lap.lap_number} - {time_str} ({status})"
                    self.laps_list.addItem(item_text)
                
                self.lbl_file.setText(f"Loaded: {os.path.basename(file_path)}")
                self.lbl_file.setStyleSheet("color: green;")
                
                # Auto-select first flying lap
                for i, lap in enumerate(self.laps):
                    if lap.is_flying:
                        self.laps_list.setCurrentRow(i)
                        break
                else:
                    self.laps_list.setCurrentRow(0)
                
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                self.lbl_file.setText("Error loading file.")
                self.lbl_file.setStyleSheet("color: red;")
                self.txt_recs.setPlainText(f"Failed to parse file:\n{str(e)}\n\n{error_details}")

    def format_time(self, seconds):
        if seconds <= 0: return "--:--.---"
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}:{secs:06.3f}"

    def on_lap_selected(self):
        selected_items = self.laps_list.selectedItems()
        if not selected_items:
            return

        selected_indices = [self.laps_list.row(item) for item in selected_items]
        
        # Sort indices to maintain Lap A vs Lap B consistency
        selected_indices.sort()
        
        # Only support up to 2 laps for now
        indices_to_load = selected_indices[:2]
        
        lap_data_list = []
        channels = [
            'SessionTime', 'Speed', 'Throttle', 'Brake', 'LatAccel',
            'LFtempL', 'LFtempM', 'LFtempR',
            'RFtempL', 'RFtempM', 'RFtempR',
            'LRtempL', 'LRtempM', 'LRtempR',
            'RRtempL', 'RRtempM', 'RRtempR'
        ]
        
        # Add extra channels for analysis if needed
        analysis_channels = [
            'LFspeed', 'RFspeed', 'LRspeed', 'RRspeed',
            'LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight',
            'SteeringWheelAngle', 'YawRate'
        ]
        channels.extend([c for c in analysis_channels if c not in channels])

        for idx in indices_to_load:
            lap = self.laps[idx]
            df = self.parser.get_lap_data(lap.lap_number, channels)
            if not df.empty:
                lap_data_list.append((lap, df))

        if not lap_data_list:
            return

        # Update Summary Dashboard (use first selected lap)
        primary_lap, primary_df = lap_data_list[0]
        self.update_summary(primary_lap, primary_df)
        
        # Update Recommendations
        self.generate_recommendations(primary_df)
        
        # Update Graphs
        self.update_graphs(lap_data_list)

    def update_summary(self, lap, df):
        self.lbl_lap_time.setText(f"Time: {self.format_time(lap.lap_time)}")
        
        if 'Speed' in df.columns:
            max_speed = df['Speed'].max() * 3.6 # m/s to km/h
            self.lbl_max_speed.setText(f"Max Speed: {max_speed:.1f} km/h")
        
        if 'LatAccel' in df.columns:
            max_lat_g = df['LatAccel'].abs().max() / 9.81
            self.lbl_max_lat_g.setText(f"Max Lat G: {max_lat_g:.2f} G")
            
        # Tire Temps
        for corner in ['LF', 'RF', 'LR', 'RR']:
            cols = [f'{corner}tempL', f'{corner}tempM', f'{corner}tempR']
            if all(c in df.columns for c in cols):
                avg_temp = df[cols].mean().mean()
                getattr(self, f"lbl_tire_{corner.lower()}").setText(f"{corner}: {avg_temp:.1f}°C")

    def update_graphs(self, lap_data_list):
        self.p1.clear()
        self.p2.clear()
        
        colors = ['b', 'r'] # Blue for Lap A, Red for Lap B
        
        for i, (lap, df) in enumerate(lap_data_list):
            if i >= 2: break
            
            color = colors[i]
            # Use Time into Lap as X axis
            if 'SessionTime' in df.columns:
                x = df['SessionTime'].values - df['SessionTime'].iloc[0]
            else:
                x = range(len(df))
            
            if 'Speed' in df.columns:
                self.p1.plot(x, df['Speed'].values * 3.6, pen=pg.mkPen(color, width=1.5), name=f"Lap {lap.lap_number}")
                
            if 'Throttle' in df.columns:
                self.p2.plot(x, df['Throttle'].values, pen=pg.mkPen(color, style=Qt.PenStyle.SolidLine), name=f"T Lap {lap.lap_number}")
            if 'Brake' in df.columns:
                # Use dashed for brake or just different color? Let's use darker color/different style
                self.p2.plot(x, df['Brake'].values, pen=pg.mkPen(color, style=Qt.PenStyle.DashLine), name=f"B Lap {lap.lap_number}")

    def generate_recommendations(self, df):
        self.analyzer = SetupAnalyzer(df, self.session_info)
        recs = self.analyzer.run_analysis()
        
        self.txt_recs.clear()
        if not recs:
            self.txt_recs.append("No actionable recommendations found.")
        else:
            for i, rec in enumerate(recs, 1):
                self.txt_recs.append(f"<b>{i}.</b> {rec}\n")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
