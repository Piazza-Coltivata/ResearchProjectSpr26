import time
import threading
import subprocess
import pulsectl


class AudioManager:

    def __init__(self, usb_audio_device):
        self.usb_audio_device = usb_audio_device
        self._cycling = False
        self._cycle_thread = None

    def _pulse(self):
        return pulsectl.Pulse("bt-audio-router")

    def setup(self):
        print("Setting up audio routing...")

        print("   Restarting PulseAudio to apply changes...")
        subprocess.run(["pulseaudio", "-k"], capture_output=True)
        time.sleep(1)
        subprocess.run(["pulseaudio", "--start"], capture_output=True)
        time.sleep(2)

        print("   Loading Bluetooth audio modules...")
        with self._pulse() as pulse:
            try:
                pulse.module_load("module-bluetooth-discover")
            except pulsectl.PulseOperationFailed:
                pass
            try:
                pulse.module_load("module-bluetooth-policy")
            except pulsectl.PulseOperationFailed:
                pass
            try:
                pulse.module_load("module-switch-on-connect")
            except pulsectl.PulseOperationFailed:
                pass

        self._set_default_sink()
        self._print_available_devices()
        return True

    def _set_default_sink(self):
        if self.usb_audio_device != "default":
            try:
                with self._pulse() as pulse:
                    for sink in pulse.sink_list():
                        if self.usb_audio_device in sink.description or self.usb_audio_device == sink.name:
                            pulse.default_set(sink)
                            print(f"Audio routing configured successfully. Default sink set to: '{sink.name}'")
                            return
                    print(f"ERROR: No sink matching '{self.usb_audio_device}' found.")
            except Exception as e:
                print(f"ERROR: Failed to set default audio sink: {e}")
        else:
            print("Using default audio sink.")

    def _print_available_devices(self):
        print("\nAvailable audio devices:")
        try:
            with self._pulse() as pulse:
                for sink in pulse.sink_list():
                    print(f"   [sink] {sink.name} — {sink.description}")
                for source in pulse.source_list():
                    print(f"   [source] {source.name} — {source.description}")
        except Exception as e:
            print(f"   Could not list devices: {e}")

    def get_sources(self):
        try:
            with self._pulse() as pulse:
                return [{"id": str(s.index), "name": s.name} for s in pulse.source_list()]
        except Exception:
            return []

    def set_default_source(self, source_name):
        try:
            with self._pulse() as pulse:
                for source in pulse.source_list():
                    if source.name == source_name:
                        pulse.default_set(source)
                        return True
            return False
        except Exception:
            return False

    def get_sinks(self):
        try:
            with self._pulse() as pulse:
                return [{"id": str(s.index), "name": s.name} for s in pulse.sink_list()]
        except Exception:
            return []

    def set_default_sink_by_name(self, sink_name):
        try:
            with self._pulse() as pulse:
                for sink in pulse.sink_list():
                    if sink.name == sink_name:
                        pulse.default_set(sink)
                        return True
            return False
        except Exception:
            return False

    def start_cycle_test(self, interval=2):
        sources = self.get_sources()
        if len(sources) < 2:
            print(f"Only {len(sources)} source(s) available — need at least 2 to cycle.")
            for s in sources:
                print(f"   {s['id']}: {s['name']}")
            return

        print(f"\nStarting source cycle test ({interval}s per source).")
        print(f"Found {len(sources)} sources:")
        for s in sources:
            print(f"   {s['id']}: {s['name']}")
        print("Press Ctrl+C to stop.\n")

        self._cycling = True
        self._cycle_thread = threading.Thread(
            target=self._cycle_loop, args=(interval,), daemon=True
        )
        self._cycle_thread.start()

    def stop_cycle_test(self):
        self._cycling = False
        if self._cycle_thread:
            self._cycle_thread.join(timeout=5)
            self._cycle_thread = None

    def _cycle_loop(self, interval):
        idx = 0
        while self._cycling:
            sources = self.get_sources()
            if not sources:
                print("No sources available, stopping cycle.")
                break
            source = sources[idx % len(sources)]
            if self.set_default_source(source["name"]):
                print(f"[cycle] Switched to source: {source['name']}")
            else:
                print(f"[cycle] Failed to switch to source: {source['name']}")
            idx += 1
            time.sleep(interval)
    
    # ----------------------------------------------------------------
    # Bluetooth output (A2DP sink) — uncomment when ready to test
    # ----------------------------------------------------------------
    # def setup_bluetooth_output(self, bt_device_address):
    #     """Route audio output to a paired Bluetooth speaker/headphones.
    #     bt_device_address should be in the form 'XX:XX:XX:XX:XX:XX'.
    #     BlueZ registers the device as a PulseAudio sink automatically
    #     once connected via A2DP. This method finds that sink and sets
    #     it as the default output."""
    #     formatted = bt_device_address.replace(":", "_")
    #     try:
    #         with self._pulse() as pulse:
    #             for sink in pulse.sink_list():
    #                 if formatted in sink.name:
    #                     pulse.default_set(sink)
    #                     print(f"Bluetooth output set to: {sink.name}")
    #                     return True
    #         print(f"ERROR: No sink found for Bluetooth device {bt_device_address}")
    #         return False
    #     except Exception as e:
    #         print(f"ERROR: Failed to set Bluetooth output: {e}")
    #         return False
