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

        # Setup Analysis
        self._analyze_braking()
        self._analyze_cornering_robust()
        self._analyze_ride_height()
        self._analyze_aero_balance()
        self._analyze_tire_imo()
        self._analyze_damper_curb()
        
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
                min_rh = self.df[col].min()
                if min_rh < 0.005: # < 0.2 inches (approx 5mm)
                    self.recommendations.append(f"Bottoming out detected on {col[:2]}. Increase ride height.")
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
        car_type = "GT3"
        if self.session_info and 'DriverInfo' in self.session_info:
            car_name = self.session_info['DriverInfo'].get('DriverCarShortName', '').lower()
            if 'mx5' in car_name: 
                car_type = "MX5"
            elif 'gt4' in car_name:
                car_type = "GT4"
            elif 'p217' in car_name or 'lmp2' in car_name:
                car_type = "LMP2"
            elif 'porsche' in car_name and ('cup' in car_name or '992' in car_name):
                # Distinguish Cup from GT3 if needed, but for now we follow user's request for PCUP
                if 'gt3' in car_name and '992' in car_name:
                    car_type = "GT3"
                else:
                    car_type = "PCUP"
            elif 'porsche' in car_name or '992' in car_name:
                car_type = "GT3"
        
        max_spread = self.targets.get(car_type, {}).get('max_imo_spread', 15) # spread in F
        
        for tire in tire_prefixes:
            temp_cols = [f'{tire}tempL', f'{tire}tempM', f'{tire}tempR']
            if all(col in self.df.columns for col in temp_cols):
                # Convert Celsius to Fahrenheit
                avg_L = (self.df[temp_cols[0]].mean() * 9/5) + 32
                avg_M = (self.df[temp_cols[1]].mean() * 9/5) + 32
                avg_R = (self.df[temp_cols[2]].mean() * 9/5) + 32
                
                if tire.startswith('L'): inner, outer = avg_R, avg_L
                else: inner, outer = avg_L, avg_R
                
                spread = inner - outer
                if abs(spread) > max_spread:
                    if spread > 0: self.recommendations.append(f"{tire} Inner too hot (+{spread:.1f}°F). Reduce neg camber.")
                    else: self.recommendations.append(f"{tire} Outer too hot ({spread:.1f}°F). Increase neg camber.")
                
                avg_IO = (inner + outer) / 2
                mid_diff = avg_M - avg_IO
                if mid_diff > 5.0: # ~3C -> 5.4F
                    self.recommendations.append(f"{tire} Middle too hot (+{mid_diff:.1f}°F). Decrease pressure.")
                elif mid_diff < -5.0:
                    self.recommendations.append(f"{tire} Middle too cold ({mid_diff:.1f}°F). Increase pressure.")

    def _analyze_damper_curb(self):
        rh_channels = ['LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight']
        if not all(col in self.df.columns for col in rh_channels) or 'YawRate' not in self.df.columns:
            return
        for col in rh_channels:
            self.df[f'{col}_vel'] = self.df[col].diff() / (1/60.0)
        for col in rh_channels:
            curb_strikes = self.df[self.df[f'{col}_vel'].abs() > 0.3]
            if not curb_strikes.empty:
                for idx in curb_strikes.index[:10]:
                    window = self.df.loc[max(0, idx-5):min(len(self.df)-1, idx+5)]
                    if window['YawRate'].abs().max() > 0.5:
                        self.recommendations.append(f"Instability over curbs at {col[:2]}. Soften dampers.")
                        break
