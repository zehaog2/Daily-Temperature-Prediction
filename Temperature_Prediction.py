def monitor_multiple_stations(self, stations, verbose=False):
        """
        Monitor multiple stations at once
        verbose: If True, prints detailed output for each station
        """
        results = []
        
        print(f"\n{'='*70}")
        print(f"FETCHING DATA FOR {len(stations)} WEATHER STATIONS")
        print(f"{'='*70}\n")
        
        for station in stations:
            print(f"Processing: {station['name']}...", end=" ")
            result = self.get_today_high_low(station['id'], station['name'], verbose=verbose)
            if result:
                results.append(result)
                print("✓")
            else:
                print("✗")
        
        return results
import requests
from datetime import datetime, timedelta
import pandas as pd
from pathlib import Path
import numpy as np
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.units import inch

class NWSTemperatureTracker:
    """
    Track real-time temperatures from NWS observation stations
    Accounts for 5-minute vs Hourly station differences and rounding errors
    Based on: NWS stations report data differently - understanding this is critical for trading
    """
    
    def __init__(self):
        self.output_dir = Path.home() / 'Desktop' / 'Daily-Temperature-Prediction'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # NWS requires User-Agent header
        self.headers = {
            'User-Agent': '(Weather Trader, trading@kalshi.com)',
            'Accept': 'application/json'
        }
        
        # Station metadata - which type and timezone
        self.station_types = {
            'KMDW': '5-minute',  # Chicago Midway
            'KNYC': 'hourly',    # NYC Central Park
            'KLAX': '5-minute',  # LAX
            'KPHL': '5-minute',  # Philadelphia
            'KAUS': '5-minute',  # Austin
            'KSEA': '5-minute',  # Seattle
            'KDEN': '5-minute',  # Denver
            'KDCA': '5-minute',  # DC Reagan
            'KBOS': '5-minute',  # Boston Logan
            'KMIA': '5-minute',  # Miami
            'KHOU': '5-minute',  # Houston Hobby
        }
        
        # UTC offsets (winter/standard time)
        # Note: During DST (Mar-Nov), add 1 hour to these
        self.utc_offsets = {
            'KNYC': -5,  # EST
            'KBOS': -5,  # EST
            'KDCA': -5,  # EST
            'KPHL': -5,  # EST
            'KMIA': -5,  # EST
            'KMDW': -6,  # CST
            'KAUS': -6,  # CST
            'KHOU': -6,  # CST
            'KDEN': -7,  # MST
            'KLAX': -8,  # PST
            'KSEA': -8,  # PST
        }
    
    def nws_round(self, value):
        """
        NWS-style rounding (always rounds .5 up, not banker's rounding)
        """
        from decimal import Decimal, ROUND_HALF_UP
        return int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    
    def celsius_to_fahrenheit_range(self, temp_c):
        """
        For 5-minute stations: Given a Celsius reading, determine possible Fahrenheit values
        
        5-minute stations:
        1. Record temp in °F (rounded to nearest whole degree)
        2. Convert to °C (rounded to nearest whole degree)
        3. NWS converts back to °F (creates error!)
        
        We need to reverse-engineer the original °F value
        """
        # What Fahrenheit values round to this Celsius value?
        # Celsius range that rounds to temp_c
        c_min = temp_c - 0.5
        c_max = temp_c + 0.5
        
        # Convert to Fahrenheit
        f_min = (c_min * 9/5) + 32
        f_max = (c_max * 9/5) + 32
        
        # Original F values that would produce this C reading
        # Need to check which whole F values convert to temp_c when rounded
        possible_f = []
        
        for f in range(int(f_min) - 2, int(f_max) + 3):
            # Convert F to C and round using NWS rounding
            c = self.nws_round((f - 32) * 5/9)
            if c == temp_c:
                possible_f.append(f)
        
        return possible_f
    
    def interpret_5min_station_temp(self, temp_c, temp_f_reported):
        """
        Interpret temperature from 5-minute station accounting for rounding error
        
        Returns: (likely_actual_f, possible_range_low, possible_range_high, confidence)
        """
        possible_f = self.celsius_to_fahrenheit_range(temp_c)
        
        if not possible_f:
            # Fallback to reported value
            return temp_f_reported, temp_f_reported, temp_f_reported, 'low'
        
        # The actual temp is likely one of these values
        min_f = min(possible_f)
        max_f = max(possible_f)
        
        # If range is small (1-2°F), high confidence
        if max_f - min_f <= 1:
            confidence = 'high'
        elif max_f - min_f <= 2:
            confidence = 'medium'
        else:
            confidence = 'low'
        
        # Best estimate: middle of range
        likely_f = (min_f + max_f) / 2
        
        return likely_f, min_f, max_f, confidence
    
    def get_station_observations(self, station_id, hours_back=24):
        """
        Get observations from a specific station
        
        station_id: ICAO station code (e.g., 'KMDW' for Midway)
        hours_back: How many hours of data to retrieve
        """
        station_type = self.station_types.get(station_id, 'unknown')
        
        try:
            # NWS API endpoint for station observations
            url = f"https://api.weather.gov/stations/{station_id}/observations"
            
            # Calculate start time
            start_time = datetime.utcnow() - timedelta(hours=hours_back)
            
            params = {
                'start': start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'limit': 500  # Max observations to retrieve
            }
            
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Parse observations
            observations = []
            
            if 'features' not in data:
                return pd.DataFrame()
            
            for obs in data['features']:
                props = obs['properties']
                
                # Extract temperature (comes in Celsius from NWS)
                temp_c = props.get('temperature', {}).get('value')
                if temp_c is None:
                    continue
                
                # NWS reported Fahrenheit (has conversion error for 5-min stations)
                temp_f_reported = (temp_c * 9/5) + 32
                
                # Parse timestamp and convert to local time
                timestamp = datetime.fromisoformat(props['timestamp'].replace('Z', '+00:00'))
                
                # Get UTC offset for this station
                utc_offset = self.utc_offsets.get(station_id, -6)  # Default CST
                timestamp_local = timestamp + timedelta(hours=utc_offset)
                
                obs_data = {
                    'timestamp_utc': timestamp,
                    'timestamp_local': timestamp_local,
                    'temp_c': temp_c,
                    'temp_f_reported': temp_f_reported,
                    'station_type': station_type
                }
                
                # For 5-minute stations: calculate actual possible F range
                if station_type == '5-minute':
                    likely_f, min_f, max_f, confidence = self.interpret_5min_station_temp(temp_c, temp_f_reported)
                    obs_data.update({
                        'temp_f_likely': likely_f,
                        'temp_f_min': min_f,
                        'temp_f_max': max_f,
                        'temp_confidence': confidence
                    })
                else:
                    # Hourly stations: reported F is more accurate (minimal conversion error)
                    obs_data.update({
                        'temp_f_likely': temp_f_reported,
                        'temp_f_min': temp_f_reported,
                        'temp_f_max': temp_f_reported,
                        'temp_confidence': 'high'
                    })
                
                # Additional data
                obs_data.update({
                    'dewpoint_f': (props.get('dewpoint', {}).get('value', 0) * 9/5) + 32 if props.get('dewpoint', {}).get('value') else None,
                    'humidity': props.get('relativeHumidity', {}).get('value'),
                    'wind_speed': props.get('windSpeed', {}).get('value'),
                    'wind_direction': props.get('windDirection', {}).get('value'),
                    'description': props.get('textDescription', '')
                })
                
                observations.append(obs_data)
            
            if not observations:
                return pd.DataFrame()
            
            df = pd.DataFrame(observations)
            df = df.sort_values('timestamp_local')
            
            return df
            
        except requests.exceptions.RequestException as e:
            return pd.DataFrame()
        except Exception as e:
            return pd.DataFrame()
    
    def estimate_actual_high(self, df, station_type):
        """
        Estimate the actual high temperature accounting for station type
        """
        if df.empty:
            return None, None, None
        
        if station_type == 'hourly':
            observed_max = df['temp_f_reported'].max()
            estimated_high = observed_max
            estimated_high_max = observed_max + 2
        else:  # 5-minute station
            observed_max_likely = df['temp_f_likely'].max()
            observed_max_upper = df['temp_f_max'].max()
            estimated_high = observed_max_likely
            estimated_high_max = observed_max_upper + 1
        
        return estimated_high, estimated_high_max, df.loc[df['temp_f_likely'].idxmax(), 'timestamp_local']
    
    def monitor_multiple_stations(self, stations, verbose=False):
        """
        Monitor multiple stations at once
        verbose: If True, prints detailed output for each station
        """
        results = []
        
        print(f"\n{'='*70}")
        print(f"FETCHING DATA FOR {len(stations)} WEATHER STATIONS")
        print(f"{'='*70}\n")
        
        for station in stations:
            print(f"Processing: {station['name']}...", end=" ")
            result = self.get_today_high_low(station['id'], station['name'], verbose=verbose)
            if result:
                results.append(result)
                print("✓")
            else:
                print("✗")
        
        return results
    
    def get_today_high_low(self, station_id, station_name, verbose=False):
        """
        Get today's high and low temperatures with proper interpretation
        verbose: If True, prints detailed output. If False, only essential info.
        """
        station_type = self.station_types.get(station_id, 'unknown')
        
        # Get 24 hours of data to ensure we capture full day
        df = self.get_station_observations(station_id, hours_back=24)
        
        if df.empty:
            if verbose:
                print(f"\n✗ No data available for {station_name}")
            return None
        
        # Filter for today (local time)
        today = datetime.now().date()
        df['date'] = df['timestamp_local'].dt.date
        today_data = df[df['date'] == today]
        
        if today_data.empty:
            if verbose:
                print(f"\n⚠ No observations for today yet. Showing last 24 hours instead.")
            today_data = df
        
        # Get last observation time
        last_observation_time = today_data.iloc[-1]['timestamp_local']
        
        # Calculate high and low with proper interpretation
        if station_type == 'hourly':
            high_temp = today_data['temp_f_reported'].max()
            low_temp = today_data['temp_f_reported'].min()
            high_time = today_data.loc[today_data['temp_f_reported'].idxmax(), 'timestamp_local']
            low_time = today_data.loc[today_data['temp_f_reported'].idxmin(), 'timestamp_local']
            current_temp = today_data.iloc[-1]['temp_f_reported']
            high_range_min = high_temp
            high_range_max = high_temp + 2  # Hourly stations can be 0-2°F higher
            low_range_min = low_temp
            low_range_max = low_temp
        else:  # 5-minute station
            high_temp = today_data['temp_f_likely'].max()
            high_range_min = today_data['temp_f_min'].max()
            high_range_max = today_data['temp_f_max'].max() + 1
            low_temp = today_data['temp_f_likely'].min()
            low_range_min = today_data['temp_f_min'].min()
            low_range_max = today_data['temp_f_max'].min()
            high_time = today_data.loc[today_data['temp_f_likely'].idxmax(), 'timestamp_local']
            low_time = today_data.loc[today_data['temp_f_likely'].idxmin(), 'timestamp_local']
            current_temp = today_data.iloc[-1]['temp_f_likely']
        
        current_time = today_data.iloc[-1]['timestamp_local']
        
        # CLI settlement predictions using NWS rounding
        high_rounded_low = self.nws_round(high_range_min)
        high_rounded_high = self.nws_round(high_range_max)
        low_rounded = self.nws_round(low_temp)
        
        # Determine confidence
        # If both ends of range round to same value = confident
        # If they round to different values = uncertain
        high_confident = (high_rounded_low == high_rounded_high)
        
        # Only print if verbose
        if verbose:
            print(f"\n{'='*70}")
            print(f"{station_name}")
            print(f"{'='*70}")
            print(f"\n🔥 Today's Observed High: {high_temp:.1f}°F")
            print(f"   Time: {high_time.strftime('%I:%M %p')}")
            print(f"   Possible range: {high_range_min:.1f}°F - {high_range_max:.1f}°F")
            if high_confident:
                print(f"   ⚠️  CLI will report: {high_rounded_low}°F (confident)")
            else:
                print(f"   ⚠️  CLI may report: {high_rounded_low}°F or {high_rounded_high}°F (uncertain)")
            
            print(f"\n❄️  Today's Observed Low: {low_temp:.1f}°F")
            print(f"   Time: {low_time.strftime('%I:%M %p')}")
            if low_range_min != low_range_max:
                print(f"   Possible range: {low_range_min:.1f}°F - {low_range_max:.1f}°F")
            
            print(f"\n📈 CLI Settlement Prediction:")
            if high_confident:
                print(f"   High will round to: {high_rounded_low}°F (confident)")
            else:
                print(f"   High will round to: {high_rounded_low}°F or {high_rounded_high}°F (uncertain)")
            print(f"   Low will round to: {low_rounded}°F")
            print(f"{'='*70}")
        
        return {
            'station': station_name,
            'station_id': station_id,
            'station_type': station_type,
            'date': today,
            'last_observation': last_observation_time,
            'high_observed': high_temp,
            'high_time': high_time,
            'high_range_min': high_range_min,
            'high_range_max': high_range_max,
            'high_rounded_low': high_rounded_low,
            'high_rounded_high': high_rounded_high,
            'low_observed': low_temp,
            'low_time': low_time,
            'low_range_min': low_range_min,
            'low_range_max': low_range_max,
            'low_rounded': low_rounded,
        }
    
    def generate_pdf_report(self, results, output_filename=None):
        """
        Generate clean PDF report with only essential temperature information
        """
        if not results:
            print("No results to generate PDF")
            return None
        
        if output_filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_filename = self.output_dir / f"temperature_report_{timestamp}.pdf"
        
        # Create PDF
        doc = SimpleDocTemplate(str(output_filename), pagesize=letter,
                               topMargin=0.5*inch, bottomMargin=0.5*inch)
        
        # Container for elements
        elements = []
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#2C3E50'),
            spaceAfter=12,
            alignment=1  # Center
        )
        
        header_style = ParagraphStyle(
            'CustomHeader',
            parent=styles['Heading2'],
            fontSize=12,
            textColor=colors.HexColor('#34495E'),
            spaceAfter=6
        )
        
        info_style = ParagraphStyle(
            'InfoStyle',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#7F8C8D'),
            spaceAfter=6
        )
        
        # Title
        title = Paragraph(f"NWS Temperature Report - {results[0]['date']}", title_style)
        elements.append(title)
        
        # Add last observation time
        last_obs = results[0]['last_observation'].strftime('%I:%M %p')
        info_text = Paragraph(f"Last Data Update: {last_obs}", info_style)
        elements.append(info_text)
        elements.append(Spacer(1, 0.2*inch))
        
        # Process each station
        for i, r in enumerate(results):
            # Station header with last observation time
            station_text = f"<b>{r['station']}</b> (Last: {r['last_observation'].strftime('%I:%M %p')})"
            station_header = Paragraph(station_text, header_style)
            elements.append(station_header)
            
            # Create data rows with unrounded temperatures
            data = [
                ['', 'Temperature', 'Time', 'CLI Range'],
                ['🔥 High', 
                 f"{r['high_observed']:.1f}°F",
                 r['high_time'].strftime('%I:%M %p'),
                 f"{r['high_range_min']:.1f}°F - {r['high_range_max']:.1f}°F"],
                ['❄️ Low',
                 f"{r['low_observed']:.1f}°F",
                 r['low_time'].strftime('%I:%M %p'),
                 f"{r['low_range_min']:.1f}°F - {r['low_range_max']:.1f}°F"]
            ]
            
            # CLI Prediction row
            if r['high_rounded_low'] == r['high_rounded_high']:
                cli_high = f"{r['high_rounded_low']}°F"
            else:
                cli_high = f"{r['high_rounded_low']}°F or {r['high_rounded_high']}°F"
            
            data.append(['📈 CLI Prediction',
                        f"High: {cli_high}",
                        '',
                        f"Low: {r['low_rounded']}°F"])
            
            # Create table
            table = Table(data, colWidths=[1*inch, 1.5*inch, 1.5*inch, 2*inch])
            table.setStyle(TableStyle([
                # Header row
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498DB')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                
                # Data rows
                ('BACKGROUND', (0, 1), (-1, 2), colors.HexColor('#ECF0F1')),
                ('BACKGROUND', (0, 3), (-1, 3), colors.HexColor('#FFF9E6')),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('TOPPADDING', (0, 1), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
                
                # Borders
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('LINEBELOW', (0, 0), (-1, 0), 2, colors.HexColor('#2980B9')),
            ]))
            
            elements.append(table)
            elements.append(Spacer(1, 0.3*inch))
            
            # Page break after every 3 stations (except last)
            if (i + 1) % 3 == 0 and i < len(results) - 1:
                elements.append(PageBreak())
        
        # Footer note
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=1
        )
        footer_text = f"Generated: {datetime.now().strftime('%Y-%m-%d %I:%M %p')} | " \
                     f"CLI Range accounts for 5-min station conversion errors"
        elements.append(Spacer(1, 0.2*inch))
        elements.append(Paragraph(footer_text, footer_style))
        
        # Build PDF
        doc.build(elements)
        
        print(f"\n✓ PDF report saved to: {output_filename}")
        return output_filename


# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    print("\n" + "="*70)
    print("NWS TEMPERATURE TRACKER - PDF REPORT GENERATOR")
    print("="*70)
    
    tracker = NWSTemperatureTracker()
    
    # Kalshi official stations
    stations = [
        {'id': 'KNYC', 'name': 'NYC Central Park'},
        {'id': 'KMIA', 'name': 'Miami Intl Airport'},
        {'id': 'KMDW', 'name': 'Chicago Midway'},
        {'id': 'KDEN', 'name': 'Denver Intl Airport'},
        {'id': 'KAUS', 'name': 'Austin Bergstrom'},
        {'id': 'KPHL', 'name': 'Philadelphia Intl'},
        {'id': 'KLAX', 'name': 'Los Angeles LAX'},
        {'id': 'KSFO', 'name': 'San Francisco Intl'},
        {'id': 'KMSY', 'name': 'New Orleans Intl'},
        {'id': 'KLAS', 'name': 'Las Vegas Intl'},
    ]
    
    # Fetch data (verbose=False for clean output)
    results = tracker.monitor_multiple_stations(stations, verbose=False)
    
    if results:
        # Generate PDF report
        print(f"\n{'='*70}")
        print("GENERATING PDF REPORT")
        print(f"{'='*70}")
        
        pdf_file = tracker.generate_pdf_report(results)
        
        print(f"\n{'='*70}")
        print("REPORT COMPLETE")
        print(f"{'='*70}")
        print(f"\nPDF contains temperature data for {len(results)} stations")
        print(f"Location: {pdf_file}")
    else:
        print("\n✗ No data available to generate report")
    
    print("\n" + "="*70)