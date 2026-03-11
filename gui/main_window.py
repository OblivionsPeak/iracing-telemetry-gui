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
        
        header_info = QVBoxLayout()
        self.lbl_car = QLabel("")
        self.lbl_car.setStyleSheet("font-weight: bold; font-size: 14px; color: #2c3e50;")
        self.lbl_track = QLabel("")
        self.lbl_track.setStyleSheet("font-weight: bold; font-size: 12px; color: #7f8c8d;")
        header_info.addWidget(self.lbl_car)
        header_info.addWidget(self.lbl_track)
        
        top_bar.addWidget(self.btn_load)
        top_bar.addWidget(self.btn_live)
        top_bar.addWidget(self.btn_export)
        top_bar.addWidget(self.btn_report)
        top_bar.addWidget(self.lbl_file)
        top_bar.addLayout(header_info)
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
        self.lbl_max_speed = QLabel("Max Speed: --- MPH")
        self.lbl_max_lat_g = QLabel("Max Lat G: -.-- G")
        
        self.lbl_tire_lf = QLabel("LF: ---°F")
        self.lbl_tire_rf = QLabel("RF: ---°F")
        self.lbl_tire_lr = QLabel("LR: ---°F")
        self.lbl_tire_rr = QLabel("RR: ---°F")
        
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
        
        self.lbl_fuel_lap = QLabel("Fuel/Lap: -.-- Gal")
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
        
        self.p1 = self.plot_widget.addPlot(title="Speed (MPH)")
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
        self.adv_plot_widget.setBackground('k')
        advanced_layout.addWidget(self.adv_plot_widget)

        self.p_track = self.adv_plot_widget.addPlot(title="Track Map (Speed Heatmap)")
        self.p_track.setAspectLocked(True)
        self.p_track.showGrid(x=True, y=True, alpha=0.3)
        
        self.curr_pos_dot = pg.ScatterPlotItem(size=12, pen=pg.mkPen('w', width=1), brush=pg.mkBrush('y'))
        self.p_track.addItem(self.curr_pos_dot)
        self.curr_pos_dot.hide()
        
        self.p_track.scene().sigMouseClicked.connect(self.on_map_clicked)

        self.adv_plot_widget.nextRow()
        self.p_aero = self.adv_plot_widget.addPlot(title="Aero Map (FRH vs RRH)")
        
        self.right_tabs.addTab(advanced_tab, "Advanced Charts")
        
        self.main_splitter.addWidget(laps_container)
        self.main_splitter.addWidget(analysis_panel)
        self.main_splitter.addWidget(self.right_tabs)
        self.main_splitter.setSizes([200, 350, 850])

        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        self.tabs.addTab(history_tab, "History")
        
        setup_tab = QWidget()
        setup_layout = QVBoxLayout(setup_tab)
        self.tabs.addTab(setup_tab, "Current Setup")
        
        self.setup_tree = QTableWidget()
        self.setup_tree.setColumnCount(2)
        self.setup_tree.setHorizontalHeaderLabels(["Parameter", "Value"])
        self.setup_tree.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        setup_layout.addWidget(self.setup_tree)
        
        btn_import_sto = QPushButton("Import .sto (HTML Export)")
        btn_import_sto.clicked.connect(self.import_external_setup)
        setup_layout.addWidget(btn_import_sto)
        
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
            return
        try:
            self.laps, self.session_info = self.parser.load_file(file_path)
            self.laps_list.clear()
            for lap in self.laps:
                status = "Flying" if lap.is_flying else "Out/In"
                time_str = self.format_time(lap.lap_time)
                self.laps_list.addItem(f"Lap {lap.lap_number} - {time_str} ({status})")
            
            weekend_info = self.session_info.get('WeekendInfo', {})
            track_name = weekend_info.get('TrackDisplayName', "Unknown Track")
            car_name = self.session_info.get('DriverInfo', {}).get('DriverCarFullName', "Unknown Car")
            self.lbl_car.setText(f"Vehicle: {car_name}")
            self.lbl_track.setText(f"Track: {track_name}")
            
            car_setup = getattr(self.parser, 'car_setup', {})
            self.update_setup_display(car_setup)
            self.generate_track_outline()
            
            for i, lap in enumerate(self.laps):
                if lap.is_flying:
                    self.laps_list.setCurrentRow(i)
                    break
            else: self.laps_list.setCurrentRow(0)

            self.history_manager.save_session(file_path, self.session_info, self.laps)
            self.refresh_history()
            self.tabs.setCurrentIndex(0)
        except Exception as e:
            print(f"Error loading file: {e}")

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
            self.load_best_lap_for_delta()
            self.live_timer.start(16)
        else:
            self.btn_live.setText("Start Live Mode")
            self.live_timer.stop()

    def update_live_data(self):
        data = self.live_monitor.poll_live_data()
        if not data: return
        lap_time = data.get('LapCurrentLapTime', 0)
        self.lbl_lap_time.setText(f"Time: {self.format_time(lap_time)}")
        # MPH conversion
        self.lbl_max_speed.setText(f"Speed: {data['Speed'] * 2.23694:.1f} MPH")
        self.lbl_max_lat_g.setText(f"Lat G: {data['LatAccel'] / 9.81:.2f} G")

        for corner in ['LF', 'RF', 'LR', 'RR']:
            avg_temp_c = (data[f'{corner}tempL'] + data[f'{corner}tempM'] + data[f'{corner}tempR']) / 3
            avg_temp_f = (avg_temp_c * 9/5) + 32
            lbl = getattr(self, f"lbl_tire_{corner.lower()}")
            lbl.setText(f"{corner}: {avg_temp_f:.1f}°F")
            color = "#3498db" if avg_temp_f < 140 else "#2ecc71" if avg_temp_f < 194 else "#f39c12" if avg_temp_f < 230 else "#e74c3c"
            lbl.setStyleSheet(f"background-color: {color}; color: white;")

    def update_summary(self, lap, df):
        self.lbl_lap_time.setText(f"Time: {self.format_time(lap.lap_time)}")
        if 'Speed' in df.columns:
            max_speed_mph = df['Speed'].max() * 2.23694
            self.lbl_max_speed.setText(f"Max Speed: {max_speed_mph:.1f} MPH")
        if 'LatAccel' in df.columns:
            max_lat_g = df['LatAccel'].abs().max() / 9.81
            self.lbl_max_lat_g.setText(f"Max Lat G: {max_lat_g:.2f} G")
        for corner in ['LF', 'RF', 'LR', 'RR']:
            cols = [f'{corner}tempL', f'{corner}tempM', f'{corner}tempR']
            if all(c in df.columns for c in cols):
                avg_temp_c = df[cols].mean().mean()
                avg_temp_f = (avg_temp_c * 9/5) + 32
                getattr(self, f"lbl_tire_{corner.lower()}").setText(f"{corner}: {avg_temp_f:.1f}°F")
        self.sector_table.setRowCount(len(lap.sectors))
        for i, sector_time in enumerate(lap.sectors):
            self.sector_table.setItem(i, 0, QTableWidgetItem(f"Sector {i+1}"))
            self.sector_table.setItem(i, 1, QTableWidgetItem(f"{sector_time:.3f}s"))

    def update_graphs(self, lap_data_list):
        self.p1.clear()
        self.p2.clear()
        self.p3.clear()
        self.p1.addItem(self.v_line1, ignoreBounds=True)
        self.p2.addItem(self.v_line2, ignoreBounds=True)
        self.p3.addItem(self.v_line3, ignoreBounds=True)
        self.p_track.clear()
        self.p_track.addItem(self.curr_pos_dot)
        self.generate_track_outline()
        self.p_aero.clear()
        
        colors = ['#00d2ff', '#ff0055']
        for i, (lap, df) in enumerate(lap_data_list):
            if i >= 2: break
            color = colors[i]
            x = df['SessionTime'].values - df['SessionTime'].iloc[0] if 'SessionTime' in df.columns else np.arange(len(df))
            if 'Speed' in df.columns:
                self.p1.plot(x, df['Speed'].values * 2.23694, pen=pg.mkPen(color, width=2), name=f"Lap {lap.lap_number}")
            if 'Throttle' in df.columns:
                self.p2.plot(x, df['Throttle'].values, pen=pg.mkPen(color, style=Qt.PenStyle.SolidLine))
            if 'Brake' in df.columns:
                self.p2.plot(x, df['Brake'].values, pen=pg.mkPen(color, style=Qt.PenStyle.DashLine))

        if len(lap_data_list) == 2:
            x_delta, delta_values = calculate_delta(lap_data_list[0][1], lap_data_list[1][1])
            if x_delta is not None:
                self.p3.plot(x_delta, delta_values, pen=pg.mkPen('#2c3e50', width=1.5))
                self.p3.addLine(y=0, pen=pg.mkPen('gray', style=Qt.PenStyle.DashLine))

        if lap_data_list:
            player_idx = self.session_info.get('DriverInfo', {}).get('DriverCarIdx', 0) if self.session_info else 0
            def extract_coord(val):
                if isinstance(val, (list, tuple, np.ndarray)): return val[player_idx] if len(val) > player_idx else 0
                return val
            if len(lap_data_list) == 1:
                lap, df = lap_data_list[0]
                if 'CarIdxX' in df.columns and 'CarIdxY' in df.columns:
                    tx = df['CarIdxX'].apply(extract_coord).values
                    ty = df['CarIdxY'].apply(extract_coord).values
                    speed = df['Speed'].values * 2.23694
                    mask = (tx != 0) | (ty != 0)
                    if mask.any():
                        tx, ty, speed = tx[mask], ty[mask], speed[mask]
                        norm_speed = (speed - speed.min()) / (speed.max() - speed.min() + 1e-6)
                        brushes = pg.colormap.get('plasma').map(norm_speed, mode='byte')
                        self.p_track.addItem(pg.ScatterPlotItem(x=tx, y=ty, brush=brushes, size=4, pen=None))
            else:
                for i, (lap, df) in enumerate(lap_data_list[:2]):
                    if 'CarIdxX' in df.columns and 'CarIdxY' in df.columns:
                        tx, ty = df['CarIdxX'].apply(extract_coord).values, df['CarIdxY'].apply(extract_coord).values
                        mask = (tx != 0) | (ty != 0)
                        if mask.any(): self.p_track.plot(tx[mask], ty[mask], pen=pg.mkPen(colors[i], width=3))

            lap, df = lap_data_list[0]
            if all(c in df.columns for c in ['LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight']):
                frh = (df['LFrideHeight'] + df['RFrideHeight']) / 2 * 39.37 # inches
                rrh = (df['LRrideHeight'] + df['RRrideHeight']) / 2 * 39.37 # inches
                self.p_aero.plot(frh.values, rrh.values, pen=None, symbol='o', symbolSize=4, symbolBrush='#3498db')
                self.p_aero.setLabel('bottom', "Front Ride Height", units='in')
                self.p_aero.setLabel('left', "Rear Ride Height", units='in')

    def generate_engineering_report(self):
        if self.primary_df is None: return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Report", f"report_lap_{self.primary_lap.lap_number}.html", "HTML (*.html)")
        if not file_path: return
        si = self.session_info
        recs = self.analyzer.run_analysis(self.primary_df)
        strategy = recs.get('strategy', {})
        
        import pyqtgraph.exporters
        import base64
        exporter = pg.exporters.ImageExporter(self.p_track.vb)
        exporter.parameters()['width'] = 800
        img_base64 = ""
        try:
            exporter.export("temp.png")
            with open("temp.png", "rb") as f: img_base64 = base64.b64encode(f.read()).decode('utf-8')
            os.remove("temp.png")
        except: pass

        html = f"""
        <html><head><style>body {{ font-family: sans-serif; margin: 40px; }} .box {{ padding: 15px; border-radius: 8px; margin-top: 10px; }}</style></head>
        <body><h1>Engineering Report</h1>
        <p><b>Car:</b> {si.get('DriverInfo', {}).get('DriverCarFullName')}</p>
        <p><b>Track:</b> {si.get('WeekendInfo', {}).get('TrackDisplayName')}</p>
        <p><b>Lap:</b> {self.primary_lap.lap_number} ({self.format_time(self.primary_lap.lap_time)})</p>
        <h2>Track Map</h2><img src="data:image/png;base64,{img_base64}" />
        <h2>Setup Advice</h2><div class="box" style="background:#ebf5fb"><ul>{''.join([f'<li>{r}</li>' for r in recs['setup']])}</ul></div>
        <h2>Fuel/Strategy</h2><div class="box" style="background:#fef5e7">
        <p>Fuel/Lap: {strategy.get('FuelPerLap', 0):.3f} Gal</p>
        <p>Est. Laps: {strategy.get('EstimatedLapsRemaining', 0):.1f}</p></div>
        </body></html>
        """
        with open(file_path, "w", encoding="utf-8") as f: f.write(html)

    def import_external_setup(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Setup", "", "HTML (*.html)")
        if not file_path: return
        from bs4 import BeautifulSoup
        with open(file_path, 'r', encoding='utf-8') as f: soup = BeautifulSoup(f, 'html.parser')
        external_setup = {}
        for row in soup.find_all('tr'):
            cols = row.find_all('td')
            if len(cols) == 2: external_setup[cols[0].text.strip().replace(':', '')] = cols[1].text.strip()
        if external_setup:
            if self.session_info: self.session_info['ExternalSetup'] = external_setup
            self.update_setup_display(external_setup)
            if self.primary_df is not None: self.generate_recommendations(self.primary_df)

    def update_setup_display(self, setup_dict):
        self.setup_tree.setRowCount(0)
        rows = []
        def flatten(d, p=''):
            for k, v in d.items():
                if isinstance(v, dict): flatten(v, p + k + ' > ')
                else: rows.append((p + k, str(v)))
        flatten(setup_dict)
        self.setup_tree.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.setup_tree.setItem(i, 0, QTableWidgetItem(k))
            self.setup_tree.setItem(i, 1, QTableWidgetItem(v))

    def generate_track_outline(self):
        if not self.laps: return
        self.p_track.clear()
        self.p_track.addItem(self.curr_pos_dot)
        best_lap = max(self.laps, key=lambda l: l.end_index - l.start_index)
        df = self.parser.get_lap_data(best_lap.lap_number, ['CarIdxX', 'CarIdxY'])
        if not df.empty:
            p_idx = self.session_info.get('DriverInfo', {}).get('DriverCarIdx', 0)
            def ex(v): return v[p_idx] if isinstance(v, (list, tuple, np.ndarray)) else v
            tx, ty = df['CarIdxX'].apply(ex).values, df['CarIdxY'].apply(ex).values
            mask = (tx != 0) | (ty != 0)
            if mask.any():
                self.p_track.plot(tx[mask], ty[mask], pen=pg.mkPen('#ffffff', width=1))
                self.p_track.autoRange()

    def on_history_double_clicked(self, index):
        self.load_file_from_path(self.history_table.item(index.row(), 4).text())

    def format_time(self, s):
        if s <= 0: return "--:--.---"
        return f"{int(s//60)}:{s%60:06.3f}"

    def on_lap_selected(self):
        sel = sorted([self.laps_list.row(i) for i in self.laps_list.selectedItems()])[:2]
        if not sel: return
        ldl = []
        p_idx = self.session_info.get('DriverInfo', {}).get('DriverCarIdx', 0)
        for idx in sel:
            lap = self.laps[idx]
            df = self.parser.get_lap_data(lap.lap_number, ['SessionTime', 'LapDistPct', 'Speed', 'Throttle', 'Brake', 'LatAccel', 'LFtempL', 'LFtempM', 'LFtempR', 'RFtempL', 'RFtempM', 'RFtempR', 'LRtempL', 'LRtempM', 'LRtempR', 'RRtempL', 'RRtempM', 'RRtempR', 'FuelLevel', 'RPM', 'Gear', 'LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight', 'SteeringWheelAngle', 'YawRate', 'CarIdxX', 'CarIdxY'])
            if not df.empty:
                for c in ['CarIdxX', 'CarIdxY']:
                    if c in df.columns: df[c] = df[c].apply(lambda x: x[p_idx] if isinstance(x, (list, tuple, np.ndarray)) else x)
                ldl.append((lap, df))
        if ldl:
            self.primary_lap, self.primary_df = ldl[0]
            self.btn_export.setEnabled(True)
            self.btn_report.setEnabled(True)
            self.update_summary(self.primary_lap, self.primary_df)
            self.generate_recommendations(self.primary_df)
            self.update_graphs(ldl)

    def on_map_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            items = self.p_track.scene().items(event.scenePos())
            if self.p_track.vb in [i for i in items if isinstance(i, pg.ViewBox)]:
                mouse_point = self.p_track.vb.mapSceneToView(event.scenePos())
                self.sync_to_coordinate(mouse_point.x(), mouse_point.y())

    def sync_to_coordinate(self, xc, yc):
        if self.primary_df is not None and 'CarIdxX' in self.primary_df.columns:
            df = self.primary_df
            mask = (df['CarIdxX'] != 0) | (df['CarIdxY'] != 0)
            if not mask.any(): return
            vdf = df[mask]
            dists = (vdf['CarIdxX'] - xc)**2 + (vdf['CarIdxY'] - yc)**2
            row = vdf.iloc[np.argmin(dists)]
            x_val = row['SessionTime'] - df['SessionTime'].iloc[0]
            self.v_line1.setPos(x_val); self.v_line2.setPos(x_val); self.v_line3.setPos(x_val)
            self.v_line1.show(); self.v_line2.show(); self.v_line3.show()
            self.curr_pos_dot.setData(x=[row['CarIdxX']], y=[row['CarIdxY']]); self.curr_pos_dot.show()

    def generate_recommendations(self, df):
        self.analyzer = SetupAnalyzer(df, self.session_info)
        recs = self.analyzer.run_analysis()
        self.txt_recs.clear()
        self.lbl_fuel_lap.setText(f"Fuel/Lap: {recs['strategy'].get('FuelPerLap', 0):.2f} Gal")
        self.lbl_laps_rem.setText(f"Est. Laps Left: {recs['strategy'].get('EstimatedLapsRemaining', 0):.1f}")
        self.txt_recs.append("<b>🔧 Setup Advice</b>")
        for i, r in enumerate(recs['setup'], 1): self.txt_recs.append(f"{i}. {r}")
        self.txt_recs.append("<br><b>🏁 Coaching</b>")
        for i, r in enumerate(recs['coaching'], 1): self.txt_recs.append(f"{i}. {r}")

    def export_csv(self):
        if self.primary_df is None: return
        p, _ = QFileDialog.getSaveFileName(self, "Export", f"lap_{self.primary_lap.lap_number}.csv", "CSV (*.csv)")
        if p: self.primary_df.to_csv(p, index=False)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
