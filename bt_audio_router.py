import os
import sys
import signal
from gi.repository import GLib

from bluetooth_adapter import BluetoothAdapter
from audio_manager import AudioManager
from device_manager import DeviceManager

DEVICE_NAME = "raspberrypi"
USB_AUDIO_DEVICE = "Razer Kraken Kitty V2"
DISCOVERABLE = True
PAIRABLE = True


class BTAudioRouter:
    
    def __init__(self):
        self.bluetooth = BluetoothAdapter(DEVICE_NAME, DISCOVERABLE, PAIRABLE)
        self.audio = AudioManager(USB_AUDIO_DEVICE)
        self.devices = DeviceManager()
        
        self.mainloop = None
        
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        print("\nExiting the D-Bus service...")
        self.stop()
        sys.exit(0)
    
    def start(self, test_cycle=False, cycle_interval=5, gui=False):
        print("=" * 60)
        print("Bluetooth Audio Router for Raspberry Pi 5")
        print("=" * 60)
        print()

        if os.getuid() != 0:
            print("ERROR: This script must be run as root. Please run with sudo.")
            sys.exit(1)

        if not self.bluetooth.setup():
            print("ERROR: Bluetooth setup failed. Exiting.")
            sys.exit(1)
        
        print()
        
        if not self.audio.setup():
            print("ERROR: Audio setup failed. Exiting.")
            sys.exit(1)
            
        print()
        print("=" * 60)
        print("Bluetooth Audio Router is RUNNING")
        if test_cycle:
            print("MODE: Source cycle test")
        if gui:
            print("MODE: GUI")
        print("=" * 60)
        print()
        print("Instructions:")
        print(f"1. On your phone, go to Bluetooth Settings")
        print(f"2. Look for '{DEVICE_NAME}'")
        print(f"3. Tap to connect")
        print(f"4. Play audio on your phone - it will stream to USB device!")
        print()
        print("Press Ctrl+C to stop the service.")
        print()

        if test_cycle:
            self.audio.start_cycle_test(interval=cycle_interval)

        if gui:
            from gui import AudioRouterGUI
            self.gui = AudioRouterGUI(self.audio)
            try:
                self.gui.run()
            finally:
                self.stop()
        else:
            try:
                self.mainloop = GLib.MainLoop()
                self.mainloop.run()
            except KeyboardInterrupt:
                print("\nExiting the D-Bus service...")
                self.stop()
                sys.exit(0)
    
    def stop(self):
        self.audio.stop_cycle_test()
        if self.mainloop:
            self.mainloop.quit()
        print("Bluetooth Audio Router stopped.")
