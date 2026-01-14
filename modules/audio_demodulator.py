"""
Audio Demodulator for Police/Public Safety Frequencies
Supports AM, FM, and NFM demodulation with real-time playback
"""

import numpy as np
import threading
import time
from typing import Optional
from scipy import signal
import logging
import sys
import os

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    logging.warning("PyAudio not available - audio playback disabled")

logger = logging.getLogger(__name__)


class AudioDemodulator:
    """
    Real-time audio demodulation from SDR IQ samples
    Supports AM, FM, NFM modulations
    """
    
    def __init__(self, sdr, modulation='NFM', audio_rate=48000):
        self.sdr = sdr
        self.modulation = modulation  # 'AM', 'FM', 'NFM'
        self.audio_rate = audio_rate
        self.running = False
        self.thread = None
        self.volume = 1.0
        self.squelch = -50.0 # dB threshold
        self.auto_fine_tune = True
        self.actual_freq = 0
        
        # Audio output
        self.pyaudio = None
        self.stream = None
        
        if PYAUDIO_AVAILABLE:
            self.pyaudio = pyaudio.PyAudio()
        
        # Sample rate from SDR (typically 2 MHz)
        self.sdr_rate = 2e6
        
        # Demodulation state
        self.prev_phase = 0
        self.rssi_smoothed = -100.0
        
        with open("/home/hilary/hacked/audio_debug.log", "a") as f:
            f.write(f"DEBUG: AudioDemodulator.__init__ called. id={id(self)}\n")
            f.write(f"DEBUG: self.running initialized to {self.running}\n")
        logger.info(f"AudioDemodulator initialized (modulation={modulation})")

    @staticmethod
    def find_peak(iq_samples, center_freq, sample_rate):
        """Find the strongest frequency offset in the chunk using FFT"""
        if len(iq_samples) < 1024:
            return center_freq
            
        # Use FFT to find peak
        n = min(len(iq_samples), 8192) # Power of 2
        window = np.hamming(n)
        chunk = iq_samples[:n] * window
        
        fft_data = np.fft.fft(chunk)
        fft_freqs = np.fft.fftfreq(n, 1/sample_rate)
        
        # Power spectrum
        power = np.abs(fft_data)**2
        
        # Ignore DC and extreme edges
        ignore = int(n * 0.05)
        peak_idx = np.argmax(power[ignore:n-ignore]) + ignore
        
        offset = fft_freqs[peak_idx]
        peak_pwr = 10 * np.log10(power[peak_idx] / n**2 + 1e-12)
        
        return center_freq + offset, peak_pwr
    
    def start_listening(self, freq):
        """Start listening to specified frequency"""
        with open("/home/hilary/hacked/audio_debug.log", "a") as f:
            f.write(f"DEBUG: start_listening called for {freq}. id={id(self)}\n")
            f.write(f"DEBUG: hasattr(self, 'running') = {hasattr(self, 'running')}\n")
            if hasattr(self, 'running'):
                f.write(f"DEBUG: self.running = {self.running}\n")
        
        if self.running:
            logger.warning("Already listening")
            return False
        
        if not PYAUDIO_AVAILABLE:
            logger.error("PyAudio not available")
            return False
        
        self.running = True
        
        # Set SDR frequency
        self.sdr.set_frequency(freq)
        self.sdr.set_sample_rate(self.sdr_rate)
        
        # Start audio stream
        try:
            self.stream = self.pyaudio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.audio_rate,
                output=True
            )
        except Exception as e:
            logger.error(f"Failed to open audio stream: {e}")
            self.running = False
            return False
        
        # Start demodulation thread
        self.thread = threading.Thread(target=self._audio_loop, daemon=True)
        self.thread.start()
        
        logger.info(f"Started listening on {freq/1e6} MHz ({self.modulation})")
        return True
    
    def stop_listening(self):
        """Stop listening and cleanup"""
        self.running = False
        
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        
        # Stop SDR
        self.sdr.stop_streaming()
        
        logger.info("Stopped listening")
    
    def set_volume(self, volume):
        """Set audio volume (0.0 to 1.0)"""
        self.volume = max(0.0, min(1.0, volume))
    
    def _audio_loop(self):
        """Main audio processing loop"""
        # Start SDR reception
        if not self.sdr.start_rx(self._process_iq_chunk):
            logger.error("Failed to start SDR RX")
            self.running = False
            return
        
        while self.running:
            time.sleep(0.01)
    
    def _process_iq_chunk(self, iq_samples):
        """Process IQ samples and output audio"""
        if not self.running or not self.stream:
            return
        
        try:
            # Fine-tune frequency if enabled
            if self.auto_fine_tune:
                 self.actual_freq, pwr = self.find_peak(iq_samples, self.sdr.device.config.frequency, self.sdr_rate)
                 # Smooth RSSI
                 self.rssi_smoothed = 0.9 * self.rssi_smoothed + 0.1 * pwr
                 
            # Squelch check
            if self.rssi_smoothed < self.squelch:
                # Output silence
                self.stream.write(np.zeros(int(len(iq_samples) * self.audio_rate / self.sdr_rate), dtype=np.int16).tobytes())
                return

            # Demodulate based on modulation type
            if self.modulation == 'AM':
                audio = self._demodulate_am(iq_samples)
            elif self.modulation in ['FM', 'NFM']:
                audio = self._demodulate_fm(iq_samples)
            else:
                logger.error(f"Unknown modulation: {self.modulation}")
                return
            
            # Resample to audio rate
            audio = self._resample(audio, len(audio), int(len(audio) * self.audio_rate / self.sdr_rate))
            
            # Apply volume
            audio = audio * self.volume
            
            # Convert to int16
            audio = np.clip(audio, -1.0, 1.0)
            audio_int16 = (audio * 32767).astype(np.int16)
            
            # Play audio
            self.stream.write(audio_int16.tobytes(), exception_on_underflow=False)
            
        except Exception as e:
            logger.error(f"Audio processing error: {e}")
    
    def _demodulate_am(self, iq_samples):
        """AM demodulation (envelope detection)"""
        # Calculate magnitude (envelope)
        magnitude = np.abs(iq_samples)
        
        # DC removal
        magnitude = magnitude - np.mean(magnitude)
        
        # Audio bandpass filter (300 Hz - 3 kHz)
        # Normalized frequencies (0 to 1, where 1 = Nyquist = sdr_rate/2)
        lowcut = 300.0 / (self.sdr_rate / 2)
        highcut = 3000.0 / (self.sdr_rate / 2)
        
        b, a = signal.butter(5, [lowcut, highcut], btype='band')
        audio = signal.lfilter(b, a, magnitude)
        
        # Normalize
        if np.max(np.abs(audio)) > 0:
            audio = audio / np.max(np.abs(audio))
        
        return audio
    
    def _demodulate_fm(self, iq_samples):
        """FM/NFM demodulation (phase derivative)"""
        # Calculate instantaneous phase
        phase = np.angle(iq_samples)
        
        # Phase difference (derivative)
        phase_diff = np.diff(phase)
        
        # Unwrap phase jumps
        phase_diff = np.unwrap(phase_diff)
        
        # Normalize to audio range
        audio = phase_diff / np.pi
        
        # De-emphasis filter for FM (75 µs time constant for US)
        # tau = 75e-6
        # alpha = 1.0 - np.exp(-1.0 / (self.sdr_rate * tau))
        #audio = signal.lfilter([alpha], [1, alpha-1], audio)
        
        # Low-pass filter for audio (0-4 kHz for NFM, 0-15 kHz for FM)
        if self.modulation == 'NFM':
            cutoff = 4000.0  # NFM bandwidth
        else:
            cutoff = 15000.0  # WFM bandwidth
        
        cutoff_norm = cutoff / (self.sdr_rate / 2)
        b, a = signal.butter(5, cutoff_norm, btype='low')
        audio = signal.lfilter(b, a, audio)
        
        # Normalize
        if np.max(np.abs(audio)) > 0:
            audio = audio / np.max(np.abs(audio))
        
        return audio
    
    def _resample(self, audio, num_samples_in, num_samples_out):
        """Resample audio to target sample rate"""
        return signal.resample(audio, num_samples_out)
    
    def __del__(self):
        """Cleanup on deletion"""
        if self.running:
            self.stop_listening()
        
        if self.pyaudio:
            self.pyaudio.terminate()
