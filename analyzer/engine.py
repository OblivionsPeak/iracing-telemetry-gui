import pandas as pd
import numpy as np
import json
import os

def calculate_delta(df_a: pd.DataFrame, df_b: pd.DataFrame):
    """
    Calculates the time delta between two laps by interpolating Lap B's time 
    onto Lap A's distance points. Returns (time_a, delta_time).
    """
    if 'LapDistPct' not in df_a.columns or 'LapDistPct' not in df_b.columns:
        return None, None
    if 'SessionTime' not in df_a.columns or 'SessionTime' not in df_b.columns:
        return None, None

    # Normalize SessionTime to start from 0
    time_a = df_a['SessionTime'].values - df_a['SessionTime'].iloc[0]
    time_b = df_b['SessionTime'].values - df_b['SessionTime'].iloc[0]
    
    dist_a = df_a['LapDistPct'].values
    dist_b = df_b['LapDistPct'].values

    # Interpolate Lap B's time into lap based on Lap A's distance points
    interp_time_b_on_a = np.interp(dist_a, dist_b, time_b)
    
    delta = time_a - interp_time_b_on_a
    return time_a, delta

class SetupAnalyzer:
    def __init__(self, dataframe: pd.DataFrame = None, session_info: dict = None):
        self.df = dataframe
        self.session_info = session_info
        self.recommendations = []
        self.coaching_recommendations = []
        self.strategy_diagnostics = {}
        self.diagnostics = {}
        self.targets = self._load_targets()
        self.car_setup = session_info.get('CarSetup', {}) if session_info else {}

    def _load_targets(self):
        import sys
        if hasattr(sys, '_MEIPASS'):
            # Running as a PyInstaller bundle
            targets_path = os.path.join(sys._MEIPASS, 'car_targets.json')
        else:
            # Running in normal python env
            targets_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'car_targets.json')
            
        if os.path.exists(targets_path):
            with open(targets_path, 'r') as f:
                return json.load(f)
        return {}

    def run_analysis(self, lap_df: pd.DataFrame = None):
        if lap_df is not None:
            self.df = lap_df

        self.recommendations.clear()
        self.coaching_recommendations.clear()
        self.strategy_diagnostics.clear()
        self.diagnostics.clear()

        if self.df is None or self.df.empty:
            return {"setup": ["No telemetry data loaded."], "coaching": [], "strategy": {}}

        # Pre-calculations
        self._calculate_suspension_velocities()

        # Setup Analysis
        self._analyze_braking()
        self._analyze_cornering_robust()
        self._analyze_ride_height()
        self._analyze_aero_balance()
        self._analyze_tire_imo()
        self._analyze_damper_curb()
        self._analyze_differential()
        
        # Coaching Analysis
        self._analyze_trail_braking()
        self._analyze_throttle_smoothness()
        self._analyze_gear_rpm()

        # Strategy Analysis
        self._analyze_strategy()
        
        if not self.recommendations:
            self.recommendations.append("Your setup looks well-balanced based on this limited telemetry run.")
            
        return {
            "setup": self.recommendations,
            "coaching": self.coaching_recommendations,
            "strategy": self.strategy_diagnostics
        }

    def _get_setup_value(self, category, name):
        """Helper to extract a nested value from CarSetup YAML."""
        if not self.car_setup: return None
        try:
            return self.car_setup.get(category, {}).get(name)
        except:
            return None

    def _get_car_type(self):
        car_type = "GT3"
        if self.session_info and 'DriverInfo' in self.session_info:
            car_name = self.session_info['DriverInfo'].get('DriverCarShortName', '').lower()
            if 'mx5' in car_name: return "MX5"
            if 'gt4' in car_name: return "GT4"
            if 'p217' in car_name or 'lmp2' in car_name: return "LMP2"
            if 'porsche' in car_name and ('cup' in car_name or '992' in car_name):
                if 'gt3' in car_name: return "GT3"
                return "PCUP"
            if 'porsche' in car_name or '992' in car_name: return "GT3"
        return car_type

    def _get_ambient_adjustment(self):
        """Calculate temperature window shift based on track temp."""
        if not self.session_info:
            return 0
        
        weekend_info = self.session_info.get('WeekendInfo', {})
        # iRacing temp strings can be "25.00 C" or "77.00 F"
        track_temp_str = weekend_info.get('TrackSurfaceTemp', '100.00 F')
        
        try:
            parts = track_temp_str.split()
            val = float(parts[0])
            unit = parts[1].upper() if len(parts) > 1 else 'F'
            if unit == 'C':
                track_temp_f = (val * 9/5) + 32
            else:
                track_temp_f = val
        except:
            track_temp_f = 100.0
            
        adjustment = 0
        if track_temp_f > 100.0:
            # Increase target by 0.5°F for every 1°F increase in track temp above 100°F
            adjustment = (track_temp_f - 100.0) * 0.5
            
        return adjustment

    def _get_normalized_tire_targets(self):
        car_type = self._get_car_type()
        base_targets = self.targets.get(car_type, {}).get('target_temps', [160, 200])
        adj = self._get_ambient_adjustment()
        return [t + adj for t in base_targets]

    def _calculate_suspension_velocities(self):
        """Compute ride height velocities in inches per second (Imperial)."""
        rh_channels = ['LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight']
        if not all(col in self.df.columns for col in rh_channels):
            return
        
        for col in rh_channels:
            # iRacing ride height is in meters, sample rate is 60Hz.
            # Conversion: meters * 39.37 = inches.
            # Velocity = (delta_meters * 39.37) / (1/60) = delta_meters * 39.37 * 60
            self.df[f'{col}_vel'] = self.df[col].diff() * 39.37 * 60.0

    def _analyze_differential(self):
        """Analyze wheel speed deltas on driven axles to suggest diff changes."""
        wheel_speeds = ['RRspeed', 'LRspeed', 'RFspeed', 'LFspeed']
        if not all(col in self.df.columns for col in wheel_speeds + ['Throttle', 'SteeringWheelAngle']):
            return

        # High throttle > 80% and low steering (straight-line or mild corner exit)
        # SteeringWheelAngle is in Radians. 0.25 rad is ~14 degrees.
        mask = (self.df['Throttle'] > 0.8) & (self.df['SteeringWheelAngle'].abs() < 0.25)
        if not mask.any():
            return
            
        data = self.df[mask]
        
        # Check Rear Axle (Driven for most cars)
        rear_min = np.maximum(data[['RRspeed', 'LRspeed']].min(axis=1), 1.0)
        rear_delta = (data['RRspeed'] - data['LRspeed']).abs() / rear_min
        
        # Check Front Axle (for 4WD)
        front_min = np.maximum(data[['RFspeed', 'LFspeed']].min(axis=1), 1.0)
        front_delta = (data['RFspeed'] - data['LFspeed']).abs() / front_min
        
        # If one driven wheel spins significantly faster (> 10%) than the other
        if (rear_delta > 0.10).any() or (front_delta > 0.10).any():
            self.recommendations.append("Significant driven wheel speed delta detected (>10%) during high throttle. Consider increasing Differential Locking or Preload to improve traction.")

    def _analyze_cornering_robust(self):
        """Advanced cornering analysis using Entry, Mid, and Exit phases."""
        if not all(c in self.df.columns for c in ['SteeringWheelAngle', 'YawRate', 'LatAccel', 'Brake', 'Throttle']):
            return

        # 1. Detect Corner Events
        # A corner is defined as LatAccel > 0.5G
        corner_mask = self.df['LatAccel'].abs() > 5.0
        if not corner_mask.any():
            return

        # 2. Extract Phase Data
        # Entry: Braking + Increasing Steering
        entry_mask = corner_mask & (self.df['Brake'] > 0.1) & (self.df['SteeringWheelAngle'].diff().abs() > 0.01)
        # Mid: Low Inputs + High Lat G
        mid_mask = corner_mask & (self.df['Brake'] < 0.1) & (self.df['Throttle'] < 0.2)
        # Exit: Decreasing Steering + Increasing Throttle
        exit_mask = corner_mask & (self.df['Throttle'] > 0.2) & (self.df['SteeringWheelAngle'].diff().abs() < 0)

        # Handling Heuristics
        # Current Setup Context
        front_arb = self._get_setup_value('Chassis', 'FrontAntiRollBar')
        rear_arb = self._get_setup_value('Chassis', 'RearAntiRollBar')

        # Entry Analysis
        if entry_mask.any():
            entry_data = self.df[entry_mask]
            ratio = (entry_data['SteeringWheelAngle'].abs() / (entry_data['YawRate'].abs() + 0.1)).mean()
            if ratio > 5.0: # High ratio -> Understeer
                advice = "Entry Understeer detected."
                if front_arb: advice += f" Your Front ARB is at {front_arb}; consider softening it."
                self.recommendations.append(advice)
            elif ratio < 1.0: # Low ratio -> Oversteer
                advice = "Entry Oversteer detected."
                if front_arb: advice += f" Your Front ARB is at {front_arb}; consider stiffening it."
                self.recommendations.append(advice)

        # Mid Analysis
        if mid_mask.any():
            mid_data = self.df[mid_mask]
            avg_lat_g = mid_data['LatAccel'].abs().mean()
            if avg_lat_g < 10.0: # If we aren't pulling enough Gs in the mid corner
                advice = "Mid-Corner Understeer: Lacking mid-corner rotation."
                if rear_arb: advice += f" Try stiffening Rear ARB (current: {rear_arb})."
                self.recommendations.append(advice)

        # Exit Analysis
        if exit_mask.any():
            exit_data = self.df[exit_mask]
            yaw_accel = exit_data['YawRate'].diff().abs().max()
            if yaw_accel > 0.1:
                advice = "Exit Oversteer: The rear is stepping out on power."
                if rear_arb: advice += f" Consider softening Rear ARB (current: {rear_arb}) or increasing Wing."
                self.recommendations.append(advice)

    def _analyze_strategy(self):
        if 'FuelLevel' not in self.df.columns:
            return
        # Convert Liters to Gallons
        L_TO_GAL = 0.264172
        fuel_start = self.df['FuelLevel'].iloc[0] * L_TO_GAL
        fuel_end = self.df['FuelLevel'].iloc[-1] * L_TO_GAL
        fuel_used = fuel_start - fuel_end
        fuel_used = max(0, fuel_used)
        self.strategy_diagnostics['FuelPerLap'] = fuel_used
        last_fuel = (self.df['FuelLevel'].iloc[-1]) * L_TO_GAL
        if fuel_used > 0:
            est_laps = last_fuel / fuel_used
            self.strategy_diagnostics['EstimatedLapsRemaining'] = est_laps
        else:
            self.strategy_diagnostics['EstimatedLapsRemaining'] = 0

    def _analyze_gear_rpm(self):
        if 'RPM' not in self.df.columns or 'Gear' not in self.df.columns:
            return
        redline = 7000
        if self.session_info and 'DriverInfo' in self.session_info:
            redline = self.session_info['DriverInfo'].get('DriverCarRedLine', 7000)
        over_rev_threshold = redline * 0.95
        lugging_threshold = redline * 0.40
        over_rev_count = len(self.df[self.df['RPM'] > over_rev_threshold])
        lugging_mask = (self.df['Gear'] >= 3) & (self.df['RPM'] < lugging_threshold) & (self.df['Throttle'] > 0.5)
        lugging_count = len(self.df[lugging_mask])
        advice = []
        if over_rev_count > 10:
            advice.append("Over-revving detected: You are holding gears too long. Shift earlier.")
        if lugging_count > 10:
            advice.append("Engine lugging detected: Downshift more to maintain RPM.")
        if not advice:
            advice.append("Gear selection and RPM range look optimal.")
        self.strategy_diagnostics['GearAdvice'] = advice

    def _analyze_trail_braking(self):
        if 'Brake' not in self.df.columns or 'SteeringWheelAngle' not in self.df.columns:
            return
        df = self.df.copy()
        df['SteerAbs'] = df['SteeringWheelAngle'].abs()
        df['SteerDelta'] = df['SteerAbs'].diff().fillna(0)
        df['BrakeDelta'] = df['Brake'].diff().fillna(0)
        trail_mask = (df['BrakeDelta'] < 0) & (df['SteerDelta'] > 0) & (df['Brake'] > 0.05)
        if trail_mask.any():
            max_release = df.loc[trail_mask, 'BrakeDelta'].abs().max()
            if max_release > 0.15:
                self.coaching_recommendations.append("Trail Braking: Releasing brake too abruptly during turn-in.")

    def _analyze_throttle_smoothness(self):
        if 'Throttle' not in self.df.columns or 'SteeringWheelAngle' not in self.df.columns:
            return
        df = self.df.copy()
        df['SteerAbs'] = df['SteeringWheelAngle'].abs()
        df['SteerDelta'] = df['SteerAbs'].diff().fillna(0)
        df['ThrottleDelta'] = df['Throttle'].diff().fillna(0)
        exit_mask = (df['SteerDelta'] < 0) & (df['Throttle'] > 0.2)
        if exit_mask.any():
            exit_data = df[exit_mask]
            throttle_var = exit_data['ThrottleDelta'].var()
            if throttle_var > 0.001:
                self.coaching_recommendations.append("Throttle Smoothness: Choppy throttle detected on corner exit.")

    def _analyze_braking(self):
        if 'Brake' not in self.df.columns or 'Speed' not in self.df.columns:
            return
        high_brake_zones = self.df[self.df['Brake'] > 0.8]
        if not high_brake_zones.empty:
            wheel_speeds = ['LFspeed', 'RFspeed', 'LRspeed', 'RRspeed']
            if all(col in self.df.columns for col in wheel_speeds):
                for index, row in high_brake_zones.iterrows():
                    car_speed = row['Speed']
                    if car_speed > 4.47: # > 10 MPH
                        front_speed = (row['LFspeed'] + row['RFspeed']) / 2.0
                        rear_speed = (row['LRspeed'] + row['RRspeed']) / 2.0
                        if front_speed < car_speed * 0.7:
                            self.recommendations.append("Front brakes locking. Move brake bias REARWARD.")
                            break
                        elif rear_speed < car_speed * 0.7:
                            self.recommendations.append("Rear brakes locking. Move brake bias FORWARD.")
                            break

    def _analyze_ride_height(self):
        rh_channels = ['LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight']
        if all(col in self.df.columns for col in rh_channels):
            for col in rh_channels:
                # Convert meters to inches for internal logic
                min_rh_in = self.df[col].min() * 39.37
                if min_rh_in < 0.20: # < 0.2 inches
                    self.recommendations.append(f"Bottoming out detected on {col[:2]} ({min_rh_in:.2f} in). Increase ride height.")
                    break

    def _analyze_aero_balance(self):
        rh_channels = ['LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight', 'Speed']
        if not all(col in self.df.columns for col in rh_channels):
            return
        # high_speed = 93 MPH (41.67 m/s)
        high_speed = 41.67
        # low_speed = 12.4 MPH (5.56 m/s)
        low_speed_data = self.df[self.df['Speed'] < 5.56]
        if low_speed_data.empty: low_speed_data = self.df.iloc[:10]
        static_front_rh = (low_speed_data['LFrideHeight'] + low_speed_data['RFrideHeight']).mean() / 2
        static_rear_rh = (low_speed_data['LRrideHeight'] + low_speed_data['RRrideHeight']).mean() / 2
        static_rake = static_rear_rh - static_front_rh
        high_speed_data = self.df[self.df['Speed'] > high_speed]
        if not high_speed_data.empty:
            hs_front_rh = (high_speed_data['LFrideHeight'] + high_speed_data['RFrideHeight']).mean() / 2
            hs_rear_rh = (high_speed_data['LRrideHeight'] + high_speed_data['RRrideHeight']).mean() / 2
            hs_rake = hs_rear_rh - hs_front_rh
            rake_delta = hs_rake - static_rake
            # Convert rake delta to inches for recommendations
            rake_delta_in = rake_delta * 39.37
            if rake_delta > 0.010:
                self.recommendations.append(f"High-speed rake increase detected (+{rake_delta_in:.2f} in). Stiffen front springs.")
            elif rake_delta < -0.010:
                self.recommendations.append(f"High-speed rake decrease detected ({rake_delta_in:.2f} in). Stiffen rear springs.")

    def _analyze_tire_imo(self):
        tire_prefixes = ['LF', 'RF', 'LR', 'RR']
        car_type = self._get_car_type()
        
        max_spread = self.targets.get(car_type, {}).get('max_imo_spread', 15) # spread in F
        target_min, target_max = self._get_normalized_tire_targets()
        
        for tire in tire_prefixes:
            temp_cols = [f'{tire}tempL', f'{tire}tempM', f'{tire}tempR']
            if all(col in self.df.columns for col in temp_cols):
                # Convert Celsius to Fahrenheit
                avg_L = (self.df[temp_cols[0]].mean() * 9/5) + 32
                avg_M = (self.df[temp_cols[1]].mean() * 9/5) + 32
                avg_R = (self.df[temp_cols[2]].mean() * 9/5) + 32
                
                if tire.startswith('L'): inner, outer = avg_R, avg_L
                else: inner, outer = avg_L, avg_R
                
                # IMO Spread Analysis
                spread = inner - outer
                if abs(spread) > max_spread:
                    if spread > 0: self.recommendations.append(f"{tire} Inner too hot (+{spread:.1f}°F). Reduce neg camber.")
                    else: self.recommendations.append(f"{tire} Outer too hot ({spread:.1f}°F). Increase neg camber.")
                
                # Pressure Analysis
                avg_IO = (inner + outer) / 2
                mid_diff = avg_M - avg_IO
                if mid_diff > 5.0: # ~3C -> 5.4F
                    self.recommendations.append(f"{tire} Middle too hot (+{mid_diff:.1f}°F). Decrease pressure.")
                elif mid_diff < -5.0:
                    self.recommendations.append(f"{tire} Middle too cold ({mid_diff:.1f}°F). Increase pressure.")
                
                # Absolute Temperature Analysis (Normalized)
                avg_tire_temp = (avg_L + avg_M + avg_R) / 3.0
                if avg_tire_temp < target_min:
                    self.recommendations.append(f"{tire} tires are running cold (Avg: {avg_tire_temp:.1f}°F, Target: {target_min:.1f}°F+). Increase aggressive driving or reduce cooling.")
                elif avg_tire_temp > target_max:
                    self.recommendations.append(f"{tire} tires are overheating (Avg: {avg_tire_temp:.1f}°F, Target: <{target_max:.1f}°F). Soften setup or adjust driving style.")

    def _analyze_damper_curb(self):
        rh_channels = ['LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight']
        if not all(f'{col}_vel' in self.df.columns for col in rh_channels) or 'YawRate' not in self.df.columns:
            return

        for col in rh_channels:
            # Threshold: 12.0 inches/sec (approx 0.3 m/s)
            curb_strikes = self.df[self.df[f'{col}_vel'].abs() > 12.0]
            if not curb_strikes.empty:
                for idx in curb_strikes.index[:10]:
                    window = self.df.loc[max(0, idx-5):min(len(self.df)-1, idx+5)]
                    if window['YawRate'].abs().max() > 0.5:
                        self.recommendations.append(f"Instability over curbs at {col[:2]} ({self.df.loc[idx, f'{col}_vel']:.1f} in/s). Soften high-speed dampers.")
                        break

    def diagnose_issue(self, issue_label):
        """Specifically scans for a user-selected handling symptom."""
        if self.df is None or self.df.empty:
            return False, ["No telemetry data available. Please load a lap."]
            
        # Ensure latest analysis data is available
        results = self.run_analysis()
        confirmed = False
        fixes = []

        if issue_label == "Unstable under braking (entry oversteer)":
            confirmed = any("Entry Oversteer" in r or "Rear brakes locking" in r for r in results['setup'])
            fixes = [
                "Move Brake Bias forward (increase percentage).",
                "Stiffen front springs or Front ARB.",
                "Increase Rear Wing angle for more aero stability.",
                "Soften rear springs or Rear ARB.",
                "Increase differential coast locking or preload."
            ]
        elif issue_label == "Car won't turn (entry understeer)":
            confirmed = any("Entry Understeer" in r or "Front brakes locking" in r for r in results['setup'])
            fixes = [
                "Move Brake Bias rearward (decrease percentage).",
                "Soften front springs or Front ARB.",
                "Increase front wing angle or decrease front ride height (increase rake).",
                "Increase negative front camber."
            ]
        elif issue_label == "Pushes mid-corner (mid understeer)":
            confirmed = any("Mid-Corner Understeer" in r for r in results['setup'])
            fixes = [
                "Stiffen Rear ARB or rear springs.",
                "Soften Front ARB or front springs.",
                "Lower front ride height or raise rear ride height (increase rake).",
                "Increase front negative camber."
            ]
        elif issue_label == "Rear steps out on throttle (exit oversteer)":
            confirmed = any("Exit Oversteer" in r or "driven wheel speed delta" in r for r in results['setup'])
            fixes = [
                "Soften Rear ARB or rear springs.",
                "Decrease Rear Wing angle (if high-speed) or increase if lacking aero grip.",
                "Reduce rear ride height (decrease rake).",
                "Increase differential power locking or preload to prevent inside wheel spin."
            ]
        elif issue_label == "Bottoms out over bumps":
            confirmed = any("Bottoming out" in r or "Instability over curbs" in r for r in results['setup'])
            fixes = [
                "Increase ride height (Front and/or Rear).",
                "Stiffen springs (increase spring rate).",
                "Increase low-speed compression damping (to control aero) or high-speed compression (for bumps).",
                "Add 'Packers' or 'Bumpstops' to limit travel before floor contact."
            ]
        elif issue_label == "Tires getting too hot":
            confirmed = any("overheating" in r or "too hot" in r for r in results['setup'])
            fixes = [
                "Soften the overall setup (Springs/ARBs) to reduce the load on the tires.",
                "Adjust tire pressures (typically higher to reduce carcass flex, or lower if sliding).",
                "Check camber settings; excessive IMO spread can cause localized overheating.",
                "Avoid over-driving (sliding) the car; smooth inputs reduce tire surface temps."
            ]

        return confirmed, fixes
