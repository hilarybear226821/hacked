
import time
import json
import threading
import numpy as np
from modules.rx_bus import rx_bus

class SpectrumWorker:
    def __init__(self, broadcast_func):
        self.broadcast = broadcast_func
        self.running = False
        self.thread = None
        
    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            
    def _run(self):
        # We limit FFT rate to avoid saturating clients
        last_fft_time = 0
        target_fps = 10 # 10Hz updates
        
        while self.running:
            try:
                # Blocking pull with small timeout
                sample = rx_bus.pull(timeout=0.2, consumer="spectrum")
                if not sample: continue
                
                now = time.time()
                if now - last_fft_time < (1.0 / target_fps):
                    continue
                    
                last_fft_time = now
                
                # Compute FFT
                iq = sample.samples
                # Take center slice if too large
                if len(iq) > 2048:
                    iq = iq[:2048]
                    
                # Blackman window
                window = np.blackman(len(iq))
                iq_windowed = iq * window
                
                fft_vals = np.abs(np.fft.fftshift(np.fft.fft(iq_windowed)))
                fft_db = 20 * np.log10(fft_vals + 1e-9)
                
                # Downsample for web (e.g. 256 bins)
                bins = 256
                # Resize
                x = np.linspace(0, len(fft_db), len(fft_db))
                new_x = np.linspace(0, len(fft_db), bins)
                fft_resampled = np.interp(new_x, x, fft_db)
                
                # Normalize reasonably (-100 to 0 dB mostly)
                # Just send raw dB values, client handles scaling
                
                data = {
                    "type": "spectrum",
                    "timestamp": sample.timestamp,
                    "center_freq": sample.center_freq,
                    "bins": fft_resampled.tolist() # JSON serializable
                }
                
                self.broadcast(json.dumps(data))
                
            except Exception as e:
                # print(f"Spectrum Error: {e}")
                time.sleep(1.0)
