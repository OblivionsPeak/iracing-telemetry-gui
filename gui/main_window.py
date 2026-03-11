import os
import sys
import pandas as pd
import numpy as np
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QListWidget, QSplitter, QTextEdit,
    QGroupBox, QGridLayout, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QTimer
import pyqtgraph as pg

# Local imports
from analyzer.parser import TelemetryParser, LiveMonitor
from analyzer.engine import SetupAnalyzer, calculate_delta
from analyzer.storage import HistoryManager

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("iRacing Telemetry Setup Analyzer")
        self.resize(1400, 900)
        
        self.parser = TelemetryParser()
        self.live_monitor = LiveMonitor()
        self.history_manager = HistoryManager()
        self.analyzer = None
        self.session_info = None
        self.laps = []
        self.primary_df = None
        self.primary_lap = None
        
        # Live Mode State
        self.live_timer = QTimer()
        self.live_timer.timeout.connect(self.update_live_data)
        self.best_lap_df = None

        self.setup_ui()
        self.refresh_history()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # --- Top Bar ---
        top_bar = QHBoxLayout()
        self.btn_load = QPushButton("Load .ibt File")
        self.btn_load.clicked.connect(self.load_file)
        
        self.btn_live = QPushButton("Start Live Mode")
        self.btn_live.setCheckable(True)
        self.btn_live.clicked.connect(self.toggle_live_mode)
        
        self.btn_export = QPushButton("Export Lap to CSV")
        self.btn_export.clicked.connect(self.export_csv)
        self.btn_export.setEnabled(False)

        self.btn_report = QPushButton("Generate Engineering Report")
        self.btn_report.clicked.connect(self.generate_engineering_report)
        self.btn_report.setEnabled(False)
        
        self.lbl_file = QLabel("No file loaded.")
        self.lbl_file.setStyleSheet("color: gray;")
        
        self.lbl_car = QLabel("")
        self.lbl_car.setStyleSheet("font-weight: bold; color: #2c3e50; margin-left: 20px;")
        
        top_bar.addWidget(self.btn_load)
        top_bar.addWidget(self.btn_live)
        top_bar.addWidget(self.btn_export)
        top_bar.addWidget(self.lbl_file)
        top_bar.addWidget(self.lbl_car)
        top_bar.addStretch()
        
        main_layout.addLayout(top_bar)

        # --- Tabs ---
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # 1. Analysis Tab
        analysis_tab = QWidget()
        analysis_tab_layout = QVBoxLayout(analysis_tab)
        self.tabs.addTab(analysis_tab, "Analysis")
        
        # --- Main Splitter (inside Analysis Tab) ---
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        analysis_tab_layout.addWidget(self.main_splitter)
        
        # 1.1 Left Panel: Laps List
        self.laps_list = QListWidget()
        self.laps_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.laps_list.itemSelectionChanged.connect(self.on_lap_selected)
        
        laps_container = QWidget()
        laps_layout = QVBoxLayout(laps_container)
        laps_layout.addWidget(QLabel("<b>Detected Laps</b>"))
        laps_layout.addWidget(self.laps_list)
        
        # 1.2 Middle Panel: Summary & Recommendations
        analysis_panel = QWidget()
        analysis_layout = QVBoxLayout(analysis_panel)
        analysis_layout.setContentsMargins(5, 0, 5, 0)
        
        # Summary Dashboard
        self.summary_group = QGroupBox("Lap Summary")
        summary_grid = QGridLayout(self.summary_group)
        
        self.lbl_lap_time = QLabel("Time: --:--.---")
        self.lbl_delta = QLabel("Delta: --.---s")
        self.lbl_delta.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.lbl_max_speed = QLabel("Max Speed: --- km/h")
        self.lbl_max_lat_g = QLabel("Max Lat G: -.-- G")
        
        self.lbl_tire_lf = QLabel("LF: ---°C")
        self.lbl_tire_rf = QLabel("RF: ---°C")
        self.lbl_tire_lr = QLabel("LR: ---°C")
        self.lbl_tire_rr = QLabel("RR: ---°C")
        
        summary_grid.addWidget(self.lbl_lap_time, 0, 0)
        summary_grid.addWidget(self.lbl_delta, 0, 1)
        summary_grid.addWidget(self.lbl_max_speed, 0, 2)
        summary_grid.addWidget(self.lbl_max_lat_g, 1, 2)
        summary_grid.addWidget(QLabel("<b>Avg Tire Temps:</b>"), 1, 0)
        summary_grid.addWidget(self.lbl_tire_lf, 2, 0)
        summary_grid.addWidget(self.lbl_tire_rf, 2, 1)
        summary_grid.addWidget(self.lbl_tire_lr, 3, 0)
        summary_grid.addWidget(self.lbl_tire_rr, 3, 1)
        
        analysis_layout.addWidget(self.summary_group)

        # Strategy Dashboard
        self.strategy_group = QGroupBox("Strategy & Fuel")
        strategy_grid = QGridLayout(self.strategy_group)
        
        self.lbl_fuel_lap = QLabel("Fuel/Lap: -.-- L")
        self.lbl_laps_rem = QLabel("Est. Laps Left: --.-")
        
        strategy_grid.addWidget(self.lbl_fuel_lap, 0, 0)
        strategy_grid.addWidget(self.lbl_laps_rem, 0, 1)
        
        analysis_layout.addWidget(self.strategy_group)
        
        # Sector Table
        analysis_layout.addWidget(QLabel("<b>Sector Splits:</b>"))
        self.sector_table = QTableWidget()
        self.sector_table.setColumnCount(2)
        self.sector_table.setHorizontalHeaderLabels(["Sector", "Time"])
        self.sector_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sector_table.setFixedHeight(150)
        analysis_layout.addWidget(self.sector_table)
        
        # Recommendations
        analysis_layout.addWidget(QLabel("<b>Setup Recommendations:</b>"))
        self.txt_recs = QTextEdit()
        self.txt_recs.setReadOnly(True)
        self.txt_recs.setPlaceholderText("Select a lap to see analysis...")
        analysis_layout.addWidget(self.txt_recs)
        
        # 1.3 Right Panel: Tabbed Graphs
        self.right_tabs = QTabWidget()
        
        # pyqtgraph setup
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')
        pg.setConfigOption('antialias', True)

        # Tab 1: Telemetry (Linear)
        telemetry_tab = QWidget()
        telemetry_layout = QVBoxLayout(telemetry_tab)
        self.plot_widget = pg.GraphicsLayoutWidget()
        telemetry_layout.addWidget(self.plot_widget)
        
        self.p1 = self.plot_widget.addPlot(title="Speed (km/h)")
        self.plot_widget.nextRow()
        self.p2 = self.plot_widget.addPlot(title="Inputs (Throttle / Brake)")
        self.p2.setXLink(self.p1)
        self.plot_widget.nextRow()
        self.p3 = self.plot_widget.addPlot(title="Delta Time (s)")
        self.p3.setXLink(self.p1)
        
        # Scrub Bar Lines
        self.v_line1 = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('k', width=1, style=Qt.PenStyle.DashLine))
        self.v_line2 = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('k', width=1, style=Qt.PenStyle.DashLine))
        self.v_line3 = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('k', width=1, style=Qt.PenStyle.DashLine))
        
        self.p1.addItem(self.v_line1, ignoreBounds=True)
        self.p2.addItem(self.v_line2, ignoreBounds=True)
        self.p3.addItem(self.v_line3, ignoreBounds=True)
        
        # Hide initially
        self.v_line1.hide()
        self.v_line2.hide()
        self.v_line3.hide()

        self.right_tabs.addTab(telemetry_tab, "Telemetry")

        # Tab 2: Advanced Charts
        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)
        self.adv_plot_widget = pg.GraphicsLayoutWidget()
        advanced_layout.addWidget(self.adv_plot_widget)

        self.p_track = self.adv_plot_widget.addPlot(title="Track Map (Speed Heatmap)")
        self.p_track.setAspectLocked(True)
        
        self.curr_pos_dot = pg.ScatterPlotItem(size=12, pen=pg.mkPen('w', width=1), brush=pg.mkBrush('y'))
        self.p_track.addItem(self.curr_pos_dot)
        self.curr_pos_dot.hide()
        
        # Connect mouse click for map-to-graph sync
        self.p_track.scene().sigMouseClicked.connect(self.on_map_clicked)

        self.adv_plot_widget.nextRow()
        self.p_aero = self.adv_plot_widget.addPlot(title="Aero Map (FRH vs RRH)")
        
        self.right_tabs.addTab(advanced_tab, "Advanced Charts")
        
        self.main_splitter.addWidget(laps_container)
        self.main_splitter.addWidget(analysis_panel)
        self.main_splitter.addWidget(self.right_tabs)
        self.main_splitter.setSizes([200, 350, 850])

        # 2. History Tab
        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        self.tabs.addTab(history_tab, "History")
        
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(["ID", "Date", "Car", "Track", "File Path"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.doubleClicked.connect(self.on_history_double_clicked)
        
        history_layout.addWidget(self.history_table)

    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open iRacing Telemetry", "", "Telemetry Files (*.ibt);;All Files (*)"
        )
        if file_path:
            self.load_file_from_path(file_path)

    def load_file_from_path(self, file_path):
        if not os.path.exists(file_path):
            self.lbl_file.setText(f"File not found: {os.path.basename(file_path)}")
            self.lbl_file.setStyleSheet("color: red;")
            return

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
            
            # Display Car Name
            car_name = self.session_info.get('DriverInfo', {}).get('DriverCarFullName', "Unknown Car")
            self.lbl_car.setText(f"Car: {car_name}")
            
            # Auto-select first flying lap
            for i, lap in enumerate(self.laps):
                if lap.is_flying:
                    self.laps_list.setCurrentRow(i)
                    break
            else:
                self.laps_list.setCurrentRow(0)

            # Save to history
            self.history_manager.save_session(file_path, self.session_info, self.laps)
            self.refresh_history()
            
            # Switch to Analysis tab if we are in History
            self.tabs.setCurrentIndex(0)
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            self.lbl_file.setText("Error loading file.")
            self.lbl_file.setStyleSheet("color: red;")
            self.txt_recs.setPlainText(f"Failed to parse file:\n{str(e)}\n\n{error_details}")

    def refresh_history(self):
        sessions = self.history_manager.get_all_sessions()
        self.history_table.setRowCount(len(sessions))
        for i, session in enumerate(sessions):
            self.history_table.setItem(i, 0, QTableWidgetItem(str(session['id'])))
            self.history_table.setItem(i, 1, QTableWidgetItem(session['date']))
            self.history_table.setItem(i, 2, QTableWidgetItem(session['car_name']))
            self.history_table.setItem(i, 3, QTableWidgetItem(session['track_name']))
            self.history_table.setItem(i, 4, QTableWidgetItem(session['file_path']))

    def toggle_live_mode(self, checked):
        if checked:
            self.btn_live.setText("Stop Live Mode")
            self.btn_live.setStyleSheet("background-color: #e74c3c; color: white;")
            self.load_best_lap_for_delta()
            self.live_timer.start(16) # ~60Hz
            self.lbl_file.setText("LIVE MODE ACTIVE")
            self.lbl_file.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.btn_live.setText("Start Live Mode")
            self.btn_live.setStyleSheet("")
            self.live_timer.stop()
            self.lbl_delta.setText("Delta: --.---s")
            self.lbl_delta.setStyleSheet("font-size: 16px; font-weight: bold; color: black;")
            self.lbl_file.setText("Live Mode Stopped.")
            self.lbl_file.setStyleSheet("color: gray;")

    def load_best_lap_for_delta(self):
        """Attempts to find the best lap in history for the current car/track."""
        data = self.live_monitor.poll_live_data()
        if data and self.live_monitor.session_info:
            si = self.live_monitor.session_info
            driver_info = si.get('DriverInfo', {})
            driver_idx = driver_info.get('DriverCarIdx', 0)
            drivers = driver_info.get('Drivers', [])
            car_name = drivers[driver_idx].get('CarScreenName', "Unknown Car") if drivers else "Unknown Car"
            track_name = si.get('WeekendInfo', {}).get('TrackDisplayName', "Unknown Track")

            best = self.history_manager.get_best_lap(car_name, track_name)
            if best:
                try:
                    best_parser = TelemetryParser()
                    best_parser.load_file(best['file_path'])
                    channels = ['SessionTime', 'LapDistPct', 'Speed', 'Throttle', 'Brake']
                    self.best_lap_df = best_parser.get_lap_data(best['lap_number'], channels)
                    self.lbl_car.setText(f"Live: {car_name} (Best: {self.format_time(best['lap_time'])})")
                except:
                    self.best_lap_df = None
            else:
                self.lbl_car.setText(f"Live: {car_name} (No best lap found)")

    def update_live_data(self):
        data = self.live_monitor.poll_live_data()
        if not data:
            return

        # Update Summary Dashboard
        lap_time = data.get('LapCurrentLapTime', 0)
        self.lbl_lap_time.setText(f"Time: {self.format_time(lap_time)}")
        self.lbl_max_speed.setText(f"Speed: {data['Speed'] * 3.6:.1f} km/h")
        self.lbl_max_lat_g.setText(f"Lat G: {data['LatAccel'] / 9.81:.2f} G")

        # Tire Temps & Heat
        for corner in ['LF', 'RF', 'LR', 'RR']:
            avg_temp = (data[f'{corner}tempL'] + data[f'{corner}tempM'] + data[f'{corner}tempR']) / 3
            lbl = getattr(self, f"lbl_tire_{corner.lower()}")
            lbl.setText(f"{corner}: {avg_temp:.1f}°C")

            # Color indicator (heat)
            if avg_temp < 60: color = "#3498db" # Blue
            elif avg_temp < 90: color = "#2ecc71" # Green
            elif avg_temp < 110: color = "#f39c12" # Orange
            else: color = "#e74c3c" # Red
            lbl.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold; padding: 2px;")

        # Delta Calculation
        if self.best_lap_df is not None and not self.best_lap_df.empty:
            current_dist = data['LapDistPct']
            best_dist = self.best_lap_df['LapDistPct'].values
            best_time = self.best_lap_df['SessionTime'].values - self.best_lap_df['SessionTime'].iloc[0]

            # Interpolate best time at current distance
            interp_best_time = np.interp(current_dist, best_dist, best_time)
            delta = lap_time - interp_best_time

            color = "#e74c3c" if delta > 0 else "#2ecc71"
            self.lbl_delta.setText(f"Delta: {delta:+.3f}s")
            self.lbl_delta.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {color};")

        # Update Graphs in Real-time (at lower frequency to save CPU)
        if len(self.live_monitor.lap_buffer) % 30 == 0:
            df = self.live_monitor.get_current_lap_df()
            if not df.empty:
                self.update_live_graphs(df, data)

    def update_live_graphs(self, df, current_data):
        self.p1.clear()
        self.p2.clear()

        # Plot Best Lap as reference
        if self.best_lap_df is not None:
            bx = self.best_lap_df['SessionTime'].values - self.best_lap_df['SessionTime'].iloc[0]
            self.p1.plot(bx, self.best_lap_df['Speed'].values * 3.6, pen=pg.mkPen('gray', width=1, style=Qt.PenStyle.DashLine))

        # Plot Current Lap
        cx = df['SessionTime'].values - df['SessionTime'].iloc[0]
        self.p1.plot(cx, df['Speed'].values * 3.6, pen=pg.mkPen('b', width=1.5))
        self.p2.plot(cx, df['Throttle'].values, pen=pg.mkPen('g', width=1))
        self.p2.plot(cx, df['Brake'].values, pen=pg.mkPen('r', width=1))

        # Track Map current position
        if 'CarIdxX' in current_data and 'CarIdxY' in current_data:
            self.curr_pos_dot.setData(x=[current_data['CarIdxX']], y=[current_data['CarIdxY']])
            self.p_track.addItem(self.curr_pos_dot)
            self.curr_pos_dot.show()

    def export_csv(self):

        if self.primary_df is None:
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Lap CSV", f"lap_{self.primary_lap.lap_number}.csv", "CSV Files (*.csv)"
        )
        if file_path:
            self.primary_df.to_csv(file_path, index=False)
            self.lbl_file.setText(f"Exported: {os.path.basename(file_path)}")
            self.lbl_file.setStyleSheet("color: green;")

    def generate_engineering_report(self):
        if self.primary_df is None or self.primary_lap is None:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Engineering Report", f"report_lap_{self.primary_lap.lap_number}.html", "HTML Files (*.html)"
        )
        if not file_path:
            return

        # 1. Gather Data
        weekend_info = self.session_info.get('WeekendInfo', {})
        driver_info = self.session_info.get('DriverInfo', {})
        
        track_name = weekend_info.get('TrackDisplayName', "Unknown Track")
        car_name = driver_info.get('DriverCarFullName', "Unknown Car")
        date_str = weekend_info.get('WeekendOptions', {}).get('Date', "N/A")
        
        lap_time = self.format_time(self.primary_lap.lap_time)
        sectors = self.primary_lap.sectors
        
        recs_dict = self.analyzer.run_analysis(self.primary_df)
        setup_recs = recs_dict.get('setup', [])
        coaching_recs = recs_dict.get('coaching', [])
        strategy = recs_dict.get('strategy', {})
        
        fuel_lap = strategy.get('FuelPerLap', 0)
        est_laps = strategy.get('EstimatedLapsRemaining', 0)
        gear_advice = strategy.get('GearAdvice', [])

        # 2. Capture Track Map
        import pyqtgraph.exporters
        import base64
        
        exporter = pg.exporters.ImageExporter(self.p_track.vb)
        exporter.parameters()['width'] = 800
        
        temp_img = "temp_track_map.png"
        img_base64 = ""
        try:
            exporter.export(temp_img)
            with open(temp_img, "rb") as f:
                img_base64 = base64.b64encode(f.read()).decode('utf-8')
            os.remove(temp_img)
        except Exception as e:
            print(f"Failed to export track map: {e}")

        # 3. Build HTML
        html = f"""
        <html>
        <head>
            <title>iRacing Engineering Report - Lap {self.primary_lap.lap_number}</title>
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; color: #333; background-color: #f4f7f6; }}
                .container {{ max-width: 1000px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 5px 15px rgba(0,0,0,0.1); }}
                h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; margin-top: 0; }}
                h2 {{ color: #2980b9; margin-top: 30px; border-left: 5px solid #3498db; padding-left: 10px; }}
                .metadata {{ background: #ecf0f1; padding: 20px; border-radius: 8px; margin-bottom: 20px; display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
                .metadata p {{ margin: 5px 0; font-size: 1.1em; }}
                .section {{ margin-bottom: 40px; }}
                .recommendations, .coaching, .strategy {{ padding: 15px; border-radius: 8px; border-left: 5px solid; margin-top: 10px; }}
                .recommendations {{ background: #ebf5fb; border-left-color: #3498db; }}
                .coaching {{ background: #eafaf1; border-left-color: #27ae60; }}
                .strategy {{ background: #fef5e7; border-left-color: #f39c12; }}
                ul {{ margin: 0; padding-left: 20px; }}
                li {{ margin-bottom: 8px; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 10px; background: white; }}
                th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
                th {{ background-color: #3498db; color: white; }}
                tr:nth-child(even) {{ background-color: #f9f9f9; }}
                .track-map {{ text-align: center; margin-top: 20px; background: #fff; padding: 10px; border: 1px solid #ddd; border-radius: 8px; }}
                .track-map img {{ max-width: 100%; height: auto; }}
                .footer {{ text-align: center; margin-top: 50px; color: #7f8c8d; font-size: 0.9em; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>iRacing Engineering Report</h1>
                
                <div class="metadata">
                    <div>
                        <p><b>Date:</b> {date_str}</p>
                        <p><b>Car:</b> {car_name}</p>
                        <p><b>Track:</b> {track_name}</p>
                    </div>
                    <div>
                        <p><b>Lap Number:</b> {self.primary_lap.lap_number}</p>
                        <p><b>Lap Time:</b> <span style="font-weight: bold; color: #e74c3c;">{lap_time}</span></p>
                    </div>
                </div>

                <div class="section">
                    <h2>Sector Times</h2>
                    <table>
                        <tr><th>Sector</th><th>Time</th></tr>
                        {"".join([f"<tr><td>Sector {i+1}</td><td>{s:.3f}s</td></tr>" for i, s in enumerate(sectors)])}
                    </table>
                </div>

                <div class="section">
                    <h2>Track Map (Speed Heatmap)</h2>
                    <div class="track-map">
                        {f'<img src="data:image/png;base64,{img_base64}" />' if img_base64 else '<p>No track map available.</p>'}
                    </div>
                </div>

                <div class="section">
                    <h2>🔧 Setup Recommendations</h2>
                    <div class="recommendations">
                        <ul>
                            {"".join([f"<li>{r}</li>" for r in setup_recs]) if setup_recs else "<li>No setup issues detected.</li>"}
                        </ul>
                    </div>
                </div>

                <div class="section">
                    <h2>🏁 Driver Coaching</h2>
                    <div class="coaching">
                        <ul>
                            {"".join([f"<li>{r}</li>" for r in coaching_recs]) if coaching_recs else "<li>No coaching tips for this lap.</li>"}
                        </ul>
                    </div>
                </div>

                <div class="section">
                    <h2>⛽ Strategy & Fuel</h2>
                    <div class="strategy">
                        <p><b>Avg Fuel per Lap:</b> {fuel_lap:.3f} L</p>
                        <p><b>Estimated Laps Remaining:</b> {est_laps:.1f}</p>
                        <h3 style="margin-top: 15px; font-size: 1.1em; color: #d68910;">Gear Advice:</h3>
                        <ul>
                            {"".join([f"<li>{a}</li>" for a in gear_advice]) if gear_advice else "<li>Gear selection looks optimal.</li>"}
                        </ul>
                    </div>
                </div>
                
                <div class="footer">
                    Generated by iRacing Telemetry Setup Analyzer
                </div>
            </div>
        </body>
        </html>
        """

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(html)
            self.lbl_file.setText(f"Report generated: {os.path.basename(file_path)}")
            self.lbl_file.setStyleSheet("color: green;")
        except Exception as e:
            self.lbl_file.setText(f"Failed to save report: {str(e)}")
            self.lbl_file.setStyleSheet("color: red;")

    def on_history_double_clicked(self, index):
        row = index.row()
        file_path = self.history_table.item(row, 4).text()
        self.load_file_from_path(file_path)

    def format_time(self, seconds):
        if seconds <= 0: return "--:--.---"
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}:{secs:06.3f}"

    def on_lap_selected(self):
        selected_items = self.laps_list.selectedItems()
        if not selected_items:
            self.btn_export.setEnabled(False)
            return

        selected_indices = [self.laps_list.row(item) for item in selected_items]
        
        # Sort indices to maintain Lap A vs Lap B consistency
        selected_indices.sort()
        
        # Only support up to 2 laps for now
        indices_to_load = selected_indices[:2]
        
        lap_data_list = []
        channels = [
            'SessionTime', 'LapDistPct', 'Speed', 'Throttle', 'Brake', 'LatAccel',
            'LFtempL', 'LFtempM', 'LFtempR',
            'RFtempL', 'RFtempM', 'RFtempR',
            'LRtempL', 'LRtempM', 'LRtempR',
            'RRtempL', 'RRtempM', 'RRtempR',
            'FuelLevel', 'RPM', 'Gear'
        ]
        
        # Add extra channels for analysis and advanced charts
        analysis_channels = [
            'LFspeed', 'RFspeed', 'LRspeed', 'RRspeed',
            'LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight',
            'SteeringWheelAngle', 'YawRate', 'CarIdxX', 'CarIdxY'
        ]
        channels.extend([c for c in analysis_channels if c not in channels])

        player_idx = self.session_info.get('DriverInfo', {}).get('DriverCarIdx', 0) if self.session_info else 0

        for idx in indices_to_load:
            lap = self.laps[idx]
            df = self.parser.get_lap_data(lap.lap_number, channels)
            
            if not df.empty:
                # Process array channels (like CarIdxX) to extract player-only data
                # iRacing CarIdxX/Y are often arrays of all cars in session
                for col in ['CarIdxX', 'CarIdxY']:
                    if col in df.columns:
                        sample = df[col].iloc[0]
                        if isinstance(sample, (list, tuple, np.ndarray)):
                             df[col] = df[col].apply(lambda x: x[player_idx] if len(x) > player_idx else 0)
                
                lap_data_list.append((lap, df))

        if not lap_data_list:
            self.btn_export.setEnabled(False)
            return

        # Update Summary Dashboard (use first selected lap)
        self.primary_lap, self.primary_df = lap_data_list[0]
        self.btn_export.setEnabled(True)
        self.btn_report.setEnabled(True)
        
        self.update_summary(self.primary_lap, self.primary_df)
        
        # Update Recommendations
        self.generate_recommendations(self.primary_df)
        
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

        # Update Sectors
        self.sector_table.setRowCount(len(lap.sectors))
        for i, sector_time in enumerate(lap.sectors):
            self.sector_table.setItem(i, 0, QTableWidgetItem(f"Sector {i+1}"))
            self.sector_table.setItem(i, 1, QTableWidgetItem(f"{sector_time:.3f}s"))

    def update_graphs(self, lap_data_list):
        self.p1.clear()
        self.p2.clear()
        self.p3.clear()
        self.p_track.clear()
        self.p_aero.clear()
        
        # Re-add persistent items after clear
        self.p1.addItem(self.v_line1, ignoreBounds=True)
        self.p2.addItem(self.v_line2, ignoreBounds=True)
        self.p3.addItem(self.v_line3, ignoreBounds=True)
        self.p_track.addItem(self.curr_pos_dot)
        
        # Hide scrub lines initially on new data
        self.v_line1.hide()
        self.v_line2.hide()
        self.v_line3.hide()
        self.curr_pos_dot.hide()
        
        colors = ['b', 'r'] # Blue for Lap A, Red for Lap B
        
        for i, (lap, df) in enumerate(lap_data_list):
            if i >= 2: break
            
            color = colors[i]
            # Use Time into Lap as X axis
            if 'SessionTime' in df.columns:
                x = df['SessionTime'].values - df['SessionTime'].iloc[0]
            else:
                x = np.arange(len(df))
            
            if 'Speed' in df.columns:
                self.p1.plot(x, df['Speed'].values * 3.6, pen=pg.mkPen(color, width=1.5), name=f"Lap {lap.lap_number}")
                
            if 'Throttle' in df.columns:
                self.p2.plot(x, df['Throttle'].values, pen=pg.mkPen(color, style=Qt.PenStyle.SolidLine), name=f"T Lap {lap.lap_number}")
            if 'Brake' in df.columns:
                self.p2.plot(x, df['Brake'].values, pen=pg.mkPen(color, style=Qt.PenStyle.DashLine), name=f"B Lap {lap.lap_number}")

        # Plot Delta if 2 laps are selected
        if len(lap_data_list) == 2:
            lap_a, df_a = lap_data_list[0]
            lap_b, df_b = lap_data_list[1]
            
            x_delta, delta_values = calculate_delta(df_a, df_b)
            if x_delta is not None:
                self.p3.plot(x_delta, delta_values, pen=pg.mkPen('k', width=1.5), name="Delta (A-B)")
                self.p3.addLine(y=0, pen=pg.mkPen('gray', style=Qt.PenStyle.DashLine))

        # Advanced Charts
        if lap_data_list:
            # 1. Track Map
            if len(lap_data_list) == 1:
                # Single Lap: Speed Heatmap
                lap, df = lap_data_list[0]
                if 'CarIdxX' in df.columns and 'CarIdxY' in df.columns:
                    tx = df['CarIdxX'].values
                    ty = df['CarIdxY'].values
                    speed = df['Speed'].values * 3.6
                    mask = (tx != 0) | (ty != 0)
                    if mask.any():
                        tx, ty, speed = tx[mask], ty[mask], speed[mask]
                        norm_speed = (speed - speed.min()) / (speed.max() - speed.min() + 1e-6)
                        try:
                            cmap = pg.colormap.get('jet')
                            brushes = cmap.map(norm_speed, mode='byte')
                        except:
                            brushes = [pg.mkBrush('b') for _ in range(len(tx))]
                        scatter = pg.ScatterPlotItem(x=tx, y=ty, brush=brushes, size=3, pen=None)
                        self.p_track.addItem(scatter)
            else:
                # Comparison: Racing Line Comparison (Blue vs Red)
                for i, (lap, df) in enumerate(lap_data_list[:2]):
                    if 'CarIdxX' in df.columns and 'CarIdxY' in df.columns:
                        tx = df['CarIdxX'].values
                        ty = df['CarIdxY'].values
                        mask = (tx != 0) | (ty != 0)
                        if mask.any():
                            self.p_track.plot(tx[mask], ty[mask], pen=pg.mkPen(colors[i], width=2), name=f"Lap {lap.lap_number}")

            # 2. Aero Map (Primary Lap)
            lap, df = lap_data_list[0]
            rrh_cols = ['LRrideHeight', 'RRrideHeight']
            frh_cols = ['LFrideHeight', 'RFrideHeight']
            if all(c in df.columns for c in rrh_cols + frh_cols):
                frh = (df['LFrideHeight'] + df['RFrideHeight']) / 2 * 1000 # mm
                rrh = (df['LRrideHeight'] + df['RRrideHeight']) / 2 * 1000 # mm
                self.p_aero.plot(frh.values, rrh.values, pen=None, symbol='o', symbolSize=4, symbolBrush='b', name="Aero Platform")
                self.p_aero.setLabel('bottom', "Front Ride Height", units='mm')
                self.p_aero.setLabel('left', "Rear Ride Height", units='mm')

    def on_map_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Check if click is on p_track
            items = self.p_track.scene().items(event.scenePos())
            if self.p_track.vb in [item for item in items if isinstance(item, pg.ViewBox)]:
                pos = event.scenePos()
                mouse_point = self.p_track.vb.mapSceneToView(pos)
                self.sync_to_coordinate(mouse_point.x(), mouse_point.y())

    def sync_to_coordinate(self, x_click, y_click):
        if self.primary_df is not None and 'CarIdxX' in self.primary_df.columns:
            df = self.primary_df
            # Filter out zeros for distance calculation
            valid_mask = (df['CarIdxX'] != 0) | (df['CarIdxY'] != 0)
            if not valid_mask.any():
                return
            
            valid_df = df[valid_mask]
            
            # Find closest point using numpy
            tx = valid_df['CarIdxX'].values
            ty = valid_df['CarIdxY'].values
            dists = (tx - x_click)**2 + (ty - y_click)**2
            idx = np.argmin(dists)
            
            row = valid_df.iloc[idx]
            # Calculate time offset from lap start
            x_val = row['SessionTime'] - df['SessionTime'].iloc[0]
            
            # Update scrub bars
            self.v_line1.setPos(x_val)
            self.v_line2.setPos(x_val)
            self.v_line3.setPos(x_val)
            
            self.v_line1.show()
            self.v_line2.show()
            self.v_line3.show()
            
            # Update current position dot
            self.curr_pos_dot.setData(x=[row['CarIdxX']], y=[row['CarIdxY']])
            self.curr_pos_dot.show()

    def generate_recommendations(self, df):
        self.analyzer = SetupAnalyzer(df, self.session_info)
        recs_dict = self.analyzer.run_analysis()
        
        setup_recs = recs_dict.get('setup', [])
        coaching_recs = recs_dict.get('coaching', [])
        strategy = recs_dict.get('strategy', {})

        self.txt_recs.clear()
        
        # Update Strategy Labels
        fuel_per_lap = strategy.get('FuelPerLap', 0)
        est_laps = strategy.get('EstimatedLapsRemaining', 0)
        self.lbl_fuel_lap.setText(f"Fuel/Lap: {fuel_per_lap:.2f} L")
        self.lbl_laps_rem.setText(f"Est. Laps Left: {est_laps:.1f}")

        # Display Setup Recommendations
        self.txt_recs.append("<b style='color: #2c3e50; font-size: 14px;'>🔧 Car Setup Recommendations</b>")
        if not setup_recs:
            self.txt_recs.append("<i>No setup issues detected.</i>")
        else:
            for i, rec in enumerate(setup_recs, 1):
                self.txt_recs.append(f"<b>{i}.</b> {rec}")

        self.txt_recs.append("<br><b style='color: #2c3e50; font-size: 14px;'>🏁 Driver Coaching Tips</b>")
        if not coaching_recs:
            self.txt_recs.append("<i>No coaching tips found for this lap. Keep it up!</i>")
        else:
            for i, rec in enumerate(coaching_recs, 1):
                self.txt_recs.append(f"<b>{i}.</b> {rec}")

        # Add Gear Optimization Advice
        gear_advice = strategy.get('GearAdvice', [])
        if gear_advice:
            self.txt_recs.append("<br><b style='color: #2c3e50; font-size: 14px;'>⚙️ Gear Optimization</b>")
            for advice in gear_advice:
                self.txt_recs.append(f"• {advice}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
