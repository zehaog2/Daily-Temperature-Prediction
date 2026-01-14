import requests
from datetime import datetime, timedelta
import pandas as pd
from pathlib import Path
import statistics

class OptimalTradingTimeCalculator:
    """
    Determines optimal time to run temperature checks for Kalshi trading
    Based on historical patterns of when daily high/low temperatures occur
    """
    
    def __init__(self):
        self.output_dir = Path.home() / 'Desktop' / 'Daily-Temperature-Prediction'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.headers = {
            'User-Agent': '(Weather Trader, trading@kalshi.com)',
            'Accept': 'application/json'
        }
        
        # YOUR timezone offset (Boston = Eastern = UTC-5)
        self.my_timezone_offset = -5  # Change this if you move!
        self.my_timezone_name = "EST"  # Or "EDT" during daylight saving
        
        # Trading stations
        self.stations = {
            'KNYC': {'name': 'NYC Central Park', 'type': 'hourly', 'utc_offset': -5},
            'KLAX': {'name': 'Los Angeles LAX', 'type': '5-minute', 'utc_offset': -8},
            'KMDW': {'name': 'Chicago Midway', 'type': '5-minute', 'utc_offset': -6},
            'KPHL': {'name': 'Philadelphia', 'type': '5-minute', 'utc_offset': -5},
            'KAUS': {'name': 'Austin', 'type': '5-minute', 'utc_offset': -6},
            'KDEN': {'name': 'Denver', 'type': '5-minute', 'utc_offset': -7},
            'KMIA': {'name': 'Miami', 'type': '5-minute', 'utc_offset': -5},
            'KSFO': {'name': 'San Francisco', 'type': '5-minute', 'utc_offset': -8},
            'KMSY': {'name': 'New Orleans', 'type': '5-minute', 'utc_offset': -6},
            'KLAS': {'name': 'Las Vegas', 'type': '5-minute', 'utc_offset': -8},
        }
    
    def get_historical_observations(self, station_id, days_back=7):
        """
        Get past week of observations to analyze timing patterns
        """
        try:
            url = f"https://api.weather.gov/stations/{station_id}/observations"
            
            # Get past week
            start_time = datetime.utcnow() - timedelta(days=days_back)
            
            params = {
                'start': start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'limit': 500
            }
            
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if 'features' not in data:
                return pd.DataFrame()
            
            observations = []
            station_info = self.stations[station_id]
            
            for obs in data['features']:
                props = obs['properties']
                temp_c = props.get('temperature', {}).get('value')
                
                if temp_c is None:
                    continue
                
                temp_f = (temp_c * 9/5) + 32
                timestamp_utc = datetime.fromisoformat(props['timestamp'].replace('Z', '+00:00'))
                timestamp_local = timestamp_utc + timedelta(hours=station_info['utc_offset'])
                
                observations.append({
                    'timestamp_utc': timestamp_utc,
                    'timestamp_local': timestamp_local,
                    'temp_f': temp_f,
                    'date': timestamp_local.date(),
                    'hour': timestamp_local.hour,
                    'minute': timestamp_local.minute
                })
            
            return pd.DataFrame(observations)
            
        except Exception as e:
            print(f"Error fetching data for {station_id}: {e}")
            return pd.DataFrame()
    
    def analyze_daily_extremes_timing(self, station_id):
        """
        Analyze when daily highs and lows typically occur
        """
        df = self.get_historical_observations(station_id, days_back=7)
        
        if df.empty:
            return None
        
        # Group by date and find high/low for each day
        daily_extremes = []
        
        for date in df['date'].unique():
            day_data = df[df['date'] == date]
            
            if len(day_data) < 10:  # Need enough data points
                continue
            
            # Find high and low
            high_idx = day_data['temp_f'].idxmax()
            low_idx = day_data['temp_f'].idxmin()
            
            high_time = day_data.loc[high_idx, 'timestamp_local']
            low_time = day_data.loc[low_idx, 'timestamp_local']
            
            daily_extremes.append({
                'date': date,
                'high_temp': day_data.loc[high_idx, 'temp_f'],
                'high_hour': high_time.hour,
                'high_minute': high_time.minute,
                'low_temp': day_data.loc[low_idx, 'temp_f'],
                'low_hour': low_time.hour,
                'low_minute': low_time.minute
            })
        
        return pd.DataFrame(daily_extremes)
    
    def calculate_optimal_trading_time(self, station_id):
        """
        Calculate when to trade based on when high/low typically occur + data delay
        Returns separate optimal times for high and low trading
        """
        station_info = self.stations[station_id]
        extremes_df = self.analyze_daily_extremes_timing(station_id)
        
        if extremes_df is None or extremes_df.empty:
            return None
        
        # Calculate average high time
        avg_high_hour = extremes_df['high_hour'].mean()
        avg_high_minute = extremes_df['high_minute'].mean()
        
        # Calculate average low time (typically around sunrise)
        avg_low_hour = extremes_df['low_hour'].mean()
        avg_low_minute = extremes_df['low_minute'].mean()
        
        # Data collection delay based on station type
        if station_info['type'] == '5-minute':
            # 5-minute stations report every 5-10 minutes
            # Safe to wait 15 minutes after typical extreme
            data_delay_minutes = 15
        else:  # hourly
            # Hourly stations report on the hour
            # Safe to wait until next hour + 5 minutes
            data_delay_minutes = 60
        
        # Calculate optimal trading time for HIGH (high time + delay)
        high_total_minutes = int(avg_high_hour * 60 + avg_high_minute + data_delay_minutes)
        optimal_high_hour = high_total_minutes // 60
        optimal_high_minute = high_total_minutes % 60
        
        # Calculate optimal trading time for LOW (low time + delay)
        low_total_minutes = int(avg_low_hour * 60 + avg_low_minute + data_delay_minutes)
        optimal_low_hour = low_total_minutes // 60
        optimal_low_minute = low_total_minutes % 60
        
        # Convert to user's timezone (Boston time)
        station_offset = station_info['utc_offset']
        my_offset = self.my_timezone_offset
        timezone_diff = my_offset - station_offset  # Hours difference
        
        # Convert high time to my timezone
        my_high_total_minutes = high_total_minutes + (timezone_diff * 60)
        my_high_hour = (my_high_total_minutes // 60) % 24
        my_high_minute = my_high_total_minutes % 60
        
        # Convert low time to my timezone  
        my_low_total_minutes = low_total_minutes + (timezone_diff * 60)
        my_low_hour = (my_low_total_minutes // 60) % 24
        my_low_minute = my_low_total_minutes % 60
        
        # For practical trading: if low happens early (before noon), 
        # you can trade both high and low at the high's optimal time
        # But we'll show both times for transparency
        
        return {
            'station_id': station_id,
            'station_name': station_info['name'],
            'station_type': station_info['type'],
            'avg_high_time': f"{int(avg_high_hour):02d}:{int(avg_high_minute):02d}",
            'avg_low_time': f"{int(avg_low_hour):02d}:{int(avg_low_minute):02d}",
            'data_delay_minutes': data_delay_minutes,
            'optimal_high_time': f"{optimal_high_hour:02d}:{optimal_high_minute:02d}",
            'optimal_low_time': f"{optimal_low_hour:02d}:{optimal_low_minute:02d}",
            'my_high_time': f"{my_high_hour:02d}:{my_high_minute:02d}",
            'my_low_time': f"{my_low_hour:02d}:{my_low_minute:02d}",
            'optimal_high_hour': optimal_high_hour,
            'optimal_high_minute': optimal_high_minute,
            'optimal_low_hour': optimal_low_hour,
            'optimal_low_minute': optimal_low_minute,
            'my_high_hour': my_high_hour,
            'my_high_minute': my_high_minute,
            'days_analyzed': len(extremes_df),
            'high_time_std': extremes_df['high_hour'].std(),
            'low_time_std': extremes_df['low_hour'].std()
        }
    
    def generate_trading_schedule(self):
        """
        Generate optimal trading times for all stations
        """
        print("\n" + "="*70)
        print("ANALYZING HISTORICAL TEMPERATURE PATTERNS")
        print("="*70 + "\n")
        
        results = []
        
        for station_id in self.stations.keys():
            print(f"Analyzing {self.stations[station_id]['name']}... ", end="")
            result = self.calculate_optimal_trading_time(station_id)
            
            if result:
                results.append(result)
                print("✓")
            else:
                print("✗")
        
        if not results:
            print("\n✗ No results generated")
            return None
        
        # Sort by YOUR timezone high time (most practical)
        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values('my_high_hour')
        
        # Display schedule
        print("\n" + "="*90)
        print("OPTIMAL TRADING SCHEDULE")
        print(f"Times shown in: LOCAL (city time) and {self.my_timezone_name} (YOUR time)")
        print("="*90 + "\n")
        
        print(f"{'City':<20} | {'Local High':<12} | {'Local Low':<12} | {f'{self.my_timezone_name} High':<12} | {f'{self.my_timezone_name} Low':<12}")
        print("-" * 90)
        
        for _, row in results_df.iterrows():
            print(f"{row['station_name']:<20} | {row['optimal_high_time']:<12} | "
                  f"{row['optimal_low_time']:<12} | {row['my_high_time']:<12} | "
                  f"{row['my_low_time']:<12}")
        
        print("\n" + "="*90)
        print("YOUR TRADING SCHEDULE (IN YOUR TIMEZONE)")
        print("="*90 + "\n")
        
        print(f"Trade at these times ({self.my_timezone_name}):")
        print("-" * 90)
        
        # Group by your high time for easy reading
        for _, row in results_df.iterrows():
            print(f"{row['my_high_time']} - Trade {row['station_name']} HIGH "
                  f"(LOW ready at {row['my_low_time']})")
        
        print("\n" + "="*90)
        print("TRADING STRATEGY")
        print("="*90)
        print(f"""
1. All times in "{self.my_timezone_name}" column are YOUR local time (Boston)
   
2. MINIMUM Temperature Trading:
   - Low times shown are in YOUR timezone
   - All lows ready by ~10 AM {self.my_timezone_name}
   
3. MAXIMUM Temperature Trading:
   - High times shown are in YOUR timezone  
   - Trade each city at the {self.my_timezone_name} time shown
   
4. One-Check Strategy (RECOMMENDED):
   - Check at latest {self.my_timezone_name} high time (bottom of list)
   - All cities' HIGH and LOW will be ready
   - Trade everything in one session

5. Example: If latest time is 5:38 PM {self.my_timezone_name}:
   - Run script at 5:40 PM {self.my_timezone_name}
   - ALL cities ready (both high and low)
   - Trade all contracts at once
        """)
        print("="*90)
        
        # Save to CSV
        output_file = self.output_dir / f"trading_schedule_{datetime.now().strftime('%Y%m%d')}.csv"
        results_df.to_csv(output_file, index=False)
        print(f"\n✓ Trading schedule saved to: {output_file}\n")
        
        return results_df
    
    def check_if_ready_to_trade(self, station_id, trade_type='both'):
        """
        Check if current time is past the optimal trading time for a station
        
        trade_type: 'high', 'low', or 'both'
        Returns True if safe to trade, False if should wait
        """
        result = self.calculate_optimal_trading_time(station_id)
        
        if not result:
            return False, "No timing data available"
        
        now = datetime.now()
        
        if trade_type == 'low':
            optimal_time = datetime.now().replace(
                hour=result['optimal_low_hour'],
                minute=result['optimal_low_minute'],
                second=0,
                microsecond=0
            )
            
            if now >= optimal_time:
                return True, f"✓ Safe to trade LOW (past {result['optimal_low_time']})"
            else:
                wait_minutes = (optimal_time - now).total_seconds() / 60
                return False, f"⚠ Wait {int(wait_minutes)} min for LOW (until {result['optimal_low_time']})"
        
        elif trade_type == 'high':
            optimal_time = datetime.now().replace(
                hour=result['optimal_high_hour'],
                minute=result['optimal_high_minute'],
                second=0,
                microsecond=0
            )
            
            if now >= optimal_time:
                return True, f"✓ Safe to trade HIGH (past {result['optimal_high_time']})"
            else:
                wait_minutes = (optimal_time - now).total_seconds() / 60
                return False, f"⚠ Wait {int(wait_minutes)} min for HIGH (until {result['optimal_high_time']})"
        
        else:  # both
            low_time = datetime.now().replace(
                hour=result['optimal_low_hour'],
                minute=result['optimal_low_minute'],
                second=0,
                microsecond=0
            )
            high_time = datetime.now().replace(
                hour=result['optimal_high_hour'],
                minute=result['optimal_high_minute'],
                second=0,
                microsecond=0
            )
            
            if now >= high_time:
                return True, f"✓ Safe to trade BOTH (past {result['optimal_high_time']})"
            elif now >= low_time:
                wait_minutes = (high_time - now).total_seconds() / 60
                return False, f"⚠ LOW ready, HIGH wait {int(wait_minutes)} min (until {result['optimal_high_time']})"
            else:
                wait_minutes = (low_time - now).total_seconds() / 60
                return False, f"⚠ Wait {int(wait_minutes)} min for LOW (until {result['optimal_low_time']})"


# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("OPTIMAL TRADING TIME CALCULATOR")
    print("Determines when to trade based on historical temperature patterns")
    print("="*70)
    
    calculator = OptimalTradingTimeCalculator()
    
    # Generate complete schedule
    schedule = calculator.generate_trading_schedule()
    
    # Check current readiness for each station
    if schedule is not None:
        print("\n" + "="*70)
        print("CURRENT TRADING READINESS")
        print(f"Current Time: {datetime.now().strftime('%H:%M')}")
        print("="*70 + "\n")
        
        print("MINIMUM (LOW) Temperature Trading:")
        print("-" * 70)
        for station_id in calculator.stations.keys():
            is_ready, message = calculator.check_if_ready_to_trade(station_id, 'low')
            status = "🟢" if is_ready else "🔴"
            print(f"{status} {calculator.stations[station_id]['name']:<20} - {message}")
        
        print("\n" + "="*70)
        print("MAXIMUM (HIGH) Temperature Trading:")
        print("-" * 70)
        for station_id in calculator.stations.keys():
            is_ready, message = calculator.check_if_ready_to_trade(station_id, 'high')
            status = "🟢" if is_ready else "🔴"
            print(f"{status} {calculator.stations[station_id]['name']:<20} - {message}")
        
        print("\n" + "="*70)
        print("\nTo use this in automated trading:")
        print("1. Run this script each morning to get today's optimal times")
        print("2. Schedule your temperature check at the 'Trade At' times")
        print("3. Or use check_if_ready_to_trade() before placing bets")
        print("="*70)