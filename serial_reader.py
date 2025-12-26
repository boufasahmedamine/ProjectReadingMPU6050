# serial_reader.py - MPU6050 data acquisition via PySerial
import serial
import json
import time
import threading
import websockets
import asyncio
import numpy as np
from scipy import signal
from datetime import datetime

class MPU6050Reader:
    def __init__(self, port='COM4', baudrate=115200, ws_host='localhost', ws_port=8765):
        self.serial = serial.Serial(port, baudrate, timeout=1)
        self.ws_url = f"ws://{ws_host}:{ws_port}/serial"
        self.running = False
        self.thread = None

        # Calibration constants for MPU6050
        self.ACCEL_SCALE = 16384.0  # LSB/g for ±2g range
        self.GYRO_SCALE = 131.0     # LSB/(°/s) for ±250°/s range

        # Buffers for analysis
        self.buffer_size = 256
        self.ax_buffer = []
        self.ay_buffer = []
        self.az_buffer = []
        self.timestamps = []

        # FFT parameters
        self.sampling_rate = 20  # Hz
        self.fft_window = 128

    def convert_to_g(self, raw_value):
        return raw_value / self.ACCEL_SCALE

    def convert_to_dps(self, raw_value):
        return raw_value / self.GYRO_SCALE

    def parse_data(self, line):
        try:
            if line.startswith('{'):
                data = json.loads(line)
                return {
                    'timestamp_ms': data.get('timestamp_ms', int(time.time() * 1000)),
                    'ax_raw': data.get('ax', 0),
                    'ay_raw': data.get('ay', 0),
                    'az_raw': data.get('az', 0),
                    'gx_raw': data.get('gx', 0),
                    'gy_raw': data.get('gy', 0),
                    'gz_raw': data.get('gz', 0)
                }
            else:
                parts = line.strip().split(',')
                if len(parts) >= 7:
                    return {
                        'timestamp_ms': int(parts[0]),
                        'ax_raw': int(parts[1]),
                        'ay_raw': int(parts[2]),
                        'az_raw': int(parts[3]),
                        'gx_raw': int(parts[4]),
                        'gy_raw': int(parts[5]),
                        'gz_raw': int(parts[6])
                    }
        except:
            pass
        return None

    def compute_fft(self, signal_data):
        if len(signal_data) < self.fft_window:
            return [], []

        window = signal.windows.hamming(self.fft_window)
        windowed_data = signal_data[-self.fft_window:] * window

        fft_result = np.fft.rfft(windowed_data)
        fft_magnitude = np.abs(fft_result)

        freqs = np.fft.rfftfreq(self.fft_window, 1.0/self.sampling_rate)

        return freqs.tolist(), fft_magnitude.tolist()

    def compute_rms(self, buffer):
        if not buffer:
            return 0
        return np.sqrt(np.mean(np.square(buffer)))

    def detect_peaks(self, buffer, threshold=2.0):
        if len(buffer) < 3:
            return []

        buffer_array = np.array(buffer)
        mean_val = np.mean(buffer_array)
        std_val = np.std(buffer_array)

        peaks = []
        for i in range(1, len(buffer) - 1):
            if buffer[i] > buffer[i-1] and buffer[i] > buffer[i+1]:
                if buffer[i] > mean_val + threshold * std_val:
                    peaks.append(i)
        return peaks

    def process_data(self, raw_data):
        processed = {
            'timestamp_ms': raw_data['timestamp_ms'],
            'date': datetime.fromtimestamp(raw_data['timestamp_ms']/1000).strftime('%Y-%m-%d'),
            'time': datetime.fromtimestamp(raw_data['timestamp_ms']/1000).strftime('%H:%M:%S.%f')[:-3],

            'ax_raw': raw_data['ax_raw'],
            'ay_raw': raw_data['ay_raw'],
            'az_raw': raw_data['az_raw'],
            'gx_raw': raw_data['gx_raw'],
            'gy_raw': raw_data['gy_raw'],
            'gz_raw': raw_data['gz_raw'],

            'ax_g': self.convert_to_g(raw_data['ax_raw']),
            'ay_g': self.convert_to_g(raw_data['ay_raw']),
            'az_g': self.convert_to_g(raw_data['az_raw']),
            'gx_dps': self.convert_to_dps(raw_data['gx_raw']),
            'gy_dps': self.convert_to_dps(raw_data['gy_raw']),
            'gz_dps': self.convert_to_dps(raw_data['gz_raw'])
        }

        self.ax_buffer.append(processed['ax_g'])
        self.ay_buffer.append(processed['ay_g'])
        self.az_buffer.append(processed['az_g'])
        self.timestamps.append(processed['timestamp_ms'])

        if len(self.ax_buffer) > self.buffer_size:
            self.ax_buffer.pop(0)
            self.ay_buffer.pop(0)
            self.az_buffer.pop(0)
            self.timestamps.pop(0)

        processed['magnitude'] = np.sqrt(
            processed['ax_g']**2 + processed['ay_g']**2 + processed['az_g']**2
        )

        if self.ax_buffer:
            processed['mean_ax'] = np.mean(self.ax_buffer)
            processed['mean_ay'] = np.mean(self.ay_buffer)
            processed['mean_az'] = np.mean(self.az_buffer)
            processed['mean_magnitude'] = np.mean([
                np.sqrt(x**2 + y**2 + z**2) 
                for x, y, z in zip(self.ax_buffer, self.ay_buffer, self.az_buffer)
            ])

        if len(self.ax_buffer) >= 10:
            processed['rms_ax'] = self.compute_rms(self.ax_buffer)
            processed['rms_ay'] = self.compute_rms(self.ay_buffer)
            processed['rms_az'] = self.compute_rms(self.az_buffer)
            processed['rms_magnitude'] = self.compute_rms([
                np.sqrt(x**2 + y**2 + z**2) 
                for x, y, z in zip(self.ax_buffer, self.ay_buffer, self.az_buffer)
            ])

        if len(self.ax_buffer) >= self.fft_window:
            fft_freq, fft_amp = self.compute_fft(self.ax_buffer)
            processed['fft_freq'] = fft_freq
            processed['fft_amp'] = fft_amp

            if fft_amp and len(fft_amp) > 5:
                peak_indices = signal.find_peaks(fft_amp[1:], height=max(fft_amp)*0.1)[0]
                processed['fft_peaks'] = [
                    {'freq': fft_freq[i+1], 'amp': fft_amp[i+1]}
                    for i in peak_indices
                ]

        if len(self.ax_buffer) >= 20:
            peaks = self.detect_peaks(self.ax_buffer, threshold=2.0)
            if peaks:
                processed['peaks_detected'] = True
                processed['peak_values'] = [self.ax_buffer[i] for i in peaks[-3:]]

        return processed

    async def send_to_websocket(self, processed_data):
        try:
            async with websockets.connect(self.ws_url) as websocket:
                await websocket.send(json.dumps(processed_data))
        except Exception as e:
            print(f"WebSocket error: {e}")

    def read_serial(self):
        print(f"Starting serial reader on {self.serial.port}")

        while self.running:
            try:
                if self.serial.in_waiting > 0:
                    line = self.serial.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        raw_data = self.parse_data(line)
                        if raw_data:
                            processed = self.process_data(raw_data)
                            asyncio.run(self.send_to_websocket(processed))
                            print(f"Processed: {processed['time']} | "
                                  f"X:{processed['ax_g']:.3f}g Y:{processed['ay_g']:.3f}g Z:{processed['az_g']:.3f}g | "
                                  f"Mag:{processed['magnitude']:.3f}g")
            except Exception as e:
                print(f"Serial error: {e}")
                time.sleep(0.1)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self.read_serial)
        self.thread.daemon = True
        self.thread.start()
        print("Serial reader started")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        self.serial.close()
        print("Serial reader stopped")

if __name__ == "__main__":
    reader = MPU6050Reader(
        port='COM4',  # Updated port
        baudrate=115200,
        ws_host='localhost',
        ws_port=8765
    )

    try:
        reader.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        reader.stop()
