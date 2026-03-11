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

    def _load_targets(self):
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
        self._analyze_cornering()
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

    def _analyze_strategy(self):
        if 'FuelLevel' not in self.df.columns:
            return

        # Fuel per lap for this specific lap
        fuel_start = self.df['FuelLevel'].iloc[0]
        fuel_end = self.df['FuelLevel'].iloc[-1]
        fuel_used = fuel_start - fuel_end
        
        # If fuel used is negative (refueled?), set to 0
        fuel_used = max(0, fuel_used)
        
        self.strategy_diagnostics['FuelPerLap'] = fuel_used
        
        # Estimated laps remaining
        last_fuel = self.df['FuelLevel'].iloc[-1]
        if fuel_used > 0:
            est_laps = last_fuel / fuel_used
            self.strategy_diagnostics['EstimatedLapsRemaining'] = est_laps
        else:
            self.strategy_diagnostics['EstimatedLapsRemaining'] = 0

    def _analyze_gear_rpm(self):
        if 'RPM' not in self.df.columns or 'Gear' not in self.df.columns:
            return

        redline = 7000 # Default
        if self.session_info and 'DriverInfo' in self.session_info:
            redline = self.session_info['DriverInfo'].get('DriverCarRedLine', 7000)

        over_rev_threshold = redline * 0.95
        lugging_threshold = redline * 0.40
        
        over_rev_count = len(self.df[self.df['RPM'] > over_rev_threshold])
        # Lugging: Only check in high gears (3 and above)
        lugging_mask = (self.df['Gear'] >= 3) & (self.df['RPM'] < lugging_threshold) & (self.df['Throttle'] > 0.5)
        lugging_count = len(self.df[lugging_mask])
        
        advice = []
        if over_rev_count > 10: # Some threshold to avoid transient spikes
            advice.append("Over-revving detected: You are holding gears too long. Shift earlier to stay in the power band and save the engine.")
        
        if lugging_count > 10:
            advice.append("Engine lugging detected: You are in too high a gear for the corner speed. Downshift more to maintain RPM.")
            
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

        # Trail braking: Brake decreasing while steering increasing
        trail_mask = (df['BrakeDelta'] < 0) & (df['SteerDelta'] > 0) & (df['Brake'] > 0.05)
        
        if trail_mask.any():
            # Check for abrupt release
            # If the driver releases the brake too abruptly (high negative derivative)
            # 0.15 change per sample at 60Hz is quite fast (~100% to 0 in < 0.1s)
            max_release = df.loc[trail_mask, 'BrakeDelta'].abs().max()
            if max_release > 0.15:
                self.coaching_recommendations.append(
                    "Trail Braking: You are releasing the brake too abruptly during turn-in. Try to 'bleed' the pressure off more slowly as you increase steering angle."
                )

    def _analyze_throttle_smoothness(self):
        if 'Throttle' not in self.df.columns or 'SteeringWheelAngle' not in self.df.columns:
            return
            
        df = self.df.copy()
        df['SteerAbs'] = df['SteeringWheelAngle'].abs()
        df['SteerDelta'] = df['SteerAbs'].diff().fillna(0)
        df['ThrottleDelta'] = df['Throttle'].diff().fillna(0)
        
        # Corner exit: Steering decreasing and Throttle increasing/active
        exit_mask = (df['SteerDelta'] < 0) & (df['Throttle'] > 0.2)
        
        if exit_mask.any():
            exit_data = df[exit_mask]
            # Variance of throttle derivative - high variance means pumping or choppy throttle
            throttle_var = exit_data['ThrottleDelta'].var()
            
            if throttle_var > 0.001: # Calibrated threshold for choppiness
                self.coaching_recommendations.append(
                    "Throttle Smoothness: Choppy throttle detected on corner exit. Aim for a single, progressive application to maximize traction."
                )

    def _analyze_braking(self):
        # Look for instances of high braking and potential front/rear lockups
        # Often brake locking leads to wheel speed being much lower than ground speed.
        if 'Brake' not in self.df.columns or 'Speed' not in self.df.columns:
            return

        # Simple heuristic: high brake pressure
        high_brake_zones = self.df[self.df['Brake'] > 0.8]
        if not high_brake_zones.empty:
            self.diagnostics['Hard Braking Zones'] = len(high_brake_zones)
            
            # Check for locking if wheel speed channels exist
            wheel_speeds = ['LFspeed', 'RFspeed', 'LRspeed', 'RRspeed']
            if all(col in self.df.columns for col in wheel_speeds):
                for index, row in high_brake_zones.iterrows():
                    car_speed = row['Speed']
                    if car_speed > 10: # m/s
                        front_speed = (row['LFspeed'] + row['RFspeed']) / 2.0
                        rear_speed = (row['LRspeed'] + row['RRspeed']) / 2.0
                        
                        if front_speed < car_speed * 0.7:
                            self.recommendations.append(
                                "Front brakes are locking heavily under hard braking. Move brake bias REARWARD."
                            )
                            break
                        elif rear_speed < car_speed * 0.7:
                            self.recommendations.append(
                                "Rear brakes are locking under hard braking, causing instability. Move brake bias FORWARD."
                            )
                            break

    def _analyze_cornering(self):
        # Look for understeer or oversteer using steering angle and yaw rate/lateral Gs
        if 'SteeringWheelAngle' not in self.df.columns or 'YawRate' not in self.df.columns:
            return
            
        # Very rough heuristic: high steering angle but low yaw rate -> understeer
        # High yaw rate compared to steering angle -> oversteer
        # Since units and ratios vary per car, we look for extreme outliers in the session.
        
        # Focus on mid-corner (low throttle, low brake, high lat g)
        if 'Throttle' in self.df.columns and 'Brake' in self.df.columns and 'LatAccel' in self.df.columns:
            cornering = self.df[(self.df['Throttle'] < 0.2) & (self.df['Brake'] < 0.1) & (self.df['LatAccel'].abs() > 5.0)]
            
            if not cornering.empty:
                # Just placeholder heuristics for demonstration
                avg_steer_mag = cornering['SteeringWheelAngle'].abs().mean()
                avg_yaw_mag = cornering['YawRate'].abs().mean()
                
                # If steering is very high on average but yaw is relatively low
                if avg_steer_mag > 1.5 and avg_yaw_mag < 0.3:
                    self.recommendations.append("Possible Mid-Corner Understeer detected. Consider softening front ARB or stiffening rear ARB.")
                elif avg_yaw_mag > 0.8 and avg_steer_mag < 0.5:
                    self.recommendations.append("Possible Mid-Corner Oversteer detected. Consider stiffening front ARB or softening rear ARB.")

    def _analyze_ride_height(self):
        # Look for bottoming out
        rh_channels = ['LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight']
        if all(col in self.df.columns for col in rh_channels):
            for col in rh_channels:
                # If ride height goes below a threshold (e.g., 0.015m or 15mm depending on car)
                # iRacing usually stores in meters. Let's assume < 0.005m is scraping.
                min_rh = self.df[col].min()
                if min_rh < 0.005:
                    corner = col[:2]
                    self.recommendations.append(f"Bottoming out detected on {corner} corner (min {min_rh:.3f}m). Increase ride height or stiffen spring/packer.")
                    break

    def _analyze_aero_balance(self):
        rh_channels = ['LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight', 'Speed']
        if not all(col in self.df.columns for col in rh_channels):
            return

        # 150 km/h = 41.67 m/s
        high_speed = 41.67
        # Get baseline rake at low speed (< 20 km/h) if available
        low_speed_data = self.df[self.df['Speed'] < 5.56]
        if low_speed_data.empty:
            low_speed_data = self.df.iloc[:10] # Fallback to start of run
        
        static_front_rh = (low_speed_data['LFrideHeight'] + low_speed_data['RFrideHeight']).mean() / 2
        static_rear_rh = (low_speed_data['LRrideHeight'] + low_speed_data['RRrideHeight']).mean() / 2
        static_rake = static_rear_rh - static_front_rh

        high_speed_data = self.df[self.df['Speed'] > high_speed]
        if not high_speed_data.empty:
            hs_front_rh = (high_speed_data['LFrideHeight'] + high_speed_data['RFrideHeight']).mean() / 2
            hs_rear_rh = (high_speed_data['LRrideHeight'] + high_speed_data['RRrideHeight']).mean() / 2
            hs_rake = hs_rear_rh - hs_front_rh
            
            rake_delta = hs_rake - static_rake
            
            # If rake increases significantly (> 10mm)
            if rake_delta > 0.010:
                self.recommendations.append(f"High-speed rake increase detected (+{rake_delta*1000:.1f}mm). If the car feels unstable at high speeds, consider stiffer front springs or reducing rear wing.")
            elif rake_delta < -0.010:
                self.recommendations.append(f"High-speed rake decrease detected ({rake_delta*1000:.1f}mm). If the car lacks turn-in at high speed, consider stiffer rear springs or more rear wing.")

    def _analyze_tire_imo(self):
        tire_prefixes = ['LF', 'RF', 'LR', 'RR']
        # iRacing typically uses tempL, tempM, tempR for each tire
        # Inner/Outer depends on side of car. 
        # LF: Inner is Right, RF: Inner is Left, LR: Inner is Right, RR: Inner is Left
        
        car_type = "GT3" # Default
        if self.session_info and 'DriverInfo' in self.session_info:
            car_name = self.session_info['DriverInfo'].get('DriverCarShortName', '')
            if 'MX5' in car_name:
                car_type = "MX5"
            elif 'porsche' in car_name.lower() or '992' in car_name:
                car_type = "GT3" # We use GT3 targets for the Porsche GT3 R
        
        max_spread = self.targets.get(car_type, {}).get('max_imo_spread', 8)

        for tire in tire_prefixes:
            temp_cols = [f'{tire}tempL', f'{tire}tempM', f'{tire}tempR']
            if all(col in self.df.columns for col in temp_cols):
                # We'll use the mean temp across the lap
                avg_L = self.df[temp_cols[0]].mean()
                avg_M = self.df[temp_cols[1]].mean()
                avg_R = self.df[temp_cols[2]].mean()
                
                # Identify Inner vs Outer
                if tire.endswith('F') or tire.endswith('R'): # LF, RF, LR, RR
                    if tire.startswith('L'): # Left side
                        inner, outer = avg_R, avg_L
                    else: # Right side
                        inner, outer = avg_L, avg_R
                
                spread = inner - outer
                if abs(spread) > max_spread:
                    if spread > 0:
                        self.recommendations.append(f"{tire} tire Inner is too hot (+{spread:.1f}°C). Reduce negative camber.")
                    else:
                        self.recommendations.append(f"{tire} tire Outer is too hot ({spread:.1f}°C). Increase negative camber.")
                
                # Pressure analysis
                avg_IO = (inner + outer) / 2
                mid_diff = avg_M - avg_IO
                if mid_diff > 3.0:
                    self.recommendations.append(f"{tire} tire Middle is too hot (+{mid_diff:.1f}°C). Decrease tire pressure.")
                elif mid_diff < -3.0:
                    self.recommendations.append(f"{tire} tire Middle is too cold ({mid_diff:.1f}°C). Increase tire pressure.")

    def _analyze_damper_curb(self):
        rh_channels = ['LFrideHeight', 'RFrideHeight', 'LRrideHeight', 'RRrideHeight']
        if not all(col in self.df.columns for col in rh_channels) or 'YawRate' not in self.df.columns:
            return

        # Calculate vertical velocity (approximate)
        for col in rh_channels:
            # Simple diff
            self.df[f'{col}_vel'] = self.df[col].diff() / (1/60.0) # Assume 60Hz if not specified
            
        # Look for high velocity spikes (curb strikes)
        # Threshold for "curb strike" (e.g., > 0.5 m/s)
        for col in rh_channels:
            curb_strikes = self.df[self.df[f'{col}_vel'].abs() > 0.3]
            if not curb_strikes.empty:
                # Check if yaw rate spikes during these curb strikes
                for idx in curb_strikes.index[:10]: # Check first 10 strikes
                    # Look at a small window around the strike
                    window = self.df.loc[max(0, idx-5):min(len(self.df)-1, idx+5)]
                    if window['YawRate'].abs().max() > 0.5: # Arbitrary yaw rate threshold
                        corner = col[:2]
                        self.recommendations.append(f"Instability detected over curbs at {corner}. Consider softening low-speed/high-speed dampers.")
                        break
