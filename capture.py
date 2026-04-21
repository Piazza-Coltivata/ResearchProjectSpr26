"""
Manages the audio capture pipeline and the null sink for exclusive audio routing.
"""
import subprocess
import threading
import time
import collections
import audio_utils

# Open a file to capture stderr from subprocesses
# The 'w' mode means it's overwritten each time the app starts
error_log_file = open("pipeline_errors.log", "w")

def log_available_ports():
    try:
        result = subprocess.run(["pw-link", "-iol"], capture_output=True, text=True)
        error_log_file.write("\n--- Available PipeWire Ports (pw-link -iol) ---\n")
        error_log_file.write(result.stdout)
        error_log_file.write("\n--- End of Ports ---\n")
        error_log_file.flush()
    except Exception as e:
        error_log_file.write(f"\nERROR: Could not run pw-link -iol: {e}\n")
        error_log_file.flush()

class CapturePipeline:
    """
    Manages a PipeWire link between a source and a sink using pw-link.
    """
    def __init__(self, source_name, sink_name):
        """
        Creates links between the given source and sink for both FL and FR channels.
        Prevents self-linking (source == sink).
        """
        self.source_name = source_name
        self.sink_name = sink_name
        if self.source_name == self.sink_name:
            print(f"Skipping self-linking for {self.source_name}")
            self.link_ports = []
            return
        self.link_ports = [
            (f"{self.source_name}:monitor_FL", f"{self.sink_name}:playback_FL"),
            (f"{self.source_name}:monitor_FR", f"{self.sink_name}:playback_FR")
        ]
        log_available_ports()
        for src_port, sink_port in self.link_ports:
            print(f"DEBUG: Attempting to link {src_port} -> {sink_port}")
            error_log_file.write(f"Attempting to link {src_port} -> {sink_port}\n")
            error_log_file.flush()
            command = ["pw-link", src_port, sink_port]
            proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=error_log_file
            )
            proc.communicate()
            if proc.returncode != 0:
                print(f"ERROR: pw-link command failed for {src_port} -> {sink_port} with exit code {proc.returncode}. Check pipeline_errors.log")

    def stop(self):
        for src_port, sink_port in self.link_ports:
            print(f"DEBUG: Attempting to unlink {src_port} -> {sink_port}")
            error_log_file.write(f"Attempting to unlink {src_port} -> {sink_port}\n")
            error_log_file.flush()
            command = ["pw-link", "-d", src_port, sink_port]
            proc = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=error_log_file
            )
            proc.communicate()
            if proc.returncode != 0:
                print(f"ERROR: pw-link -d command failed for {src_port} -> {sink_port} with exit code {proc.returncode}. Check pipeline_errors.log")
        print("PipeWire links stopped.")

    def is_running(self):
        return True # Simplified check

class NullSinkManager:
    """
    Creates and manages a 'null' sink to act as an audio black hole,
    allowing for one stream to be selectively captured while others are silenced.
    """
    NULL_SINK_NAME = "party_mode_null_sink"

    def __init__(self):
        self._module_id = None
        self._monitor_thread = None
        self._monitoring = False
        self.stop_event = threading.Event()

    def setup(self):
        """Creates the null sink."""
        self.teardown() # Clean up any old instance
        result = subprocess.run(
            ["pactl", "load-module", "module-null-sink", f"sink_name={self.NULL_SINK_NAME}"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            self._module_id = result.stdout.strip()
            print(f"Null sink created (module {self._module_id}).")
            self.start_monitoring()
            return True
        print(f"Error creating null sink: {result.stderr}")
        return False

    def teardown(self):
        """Removes the null sink."""
        self.stop_monitoring()
        if self._module_id:
            subprocess.run(["pactl", "unload-module", self._module_id])
            print("Null sink removed.")
            self._module_id = None
        # Also find and remove by name if it's stuck
        sinks_result = subprocess.run(["pactl", "list", "short", "modules"], capture_output=True, text=True)
        for line in sinks_result.stdout.splitlines():
            if self.NULL_SINK_NAME in line:
                mod_id = line.split()[0]
                subprocess.run(["pactl", "unload-module", mod_id])
                print(f"Found and removed stale null sink (module {mod_id}).")


    def start_monitoring(self):
        """Starts a thread to automatically move all BT streams to the null sink."""
        self._monitoring = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self):
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)

    def _monitor_loop(self):
        """Periodically moves any new Bluetooth audio streams to the null sink."""
        while self._monitoring:
            try:
                inputs_result = subprocess.run(["pactl", "list", "short", "sink-inputs"], capture_output=True, text=True, check=True)
                for line in inputs_result.stdout.splitlines():
                    parts = line.split()
                    stream_id = parts[0]
                    # Check if it's a bluetooth stream before moving
                    props_result = subprocess.run(["pactl", "list", "sink-inputs"], capture_output=True, text=True, check=True)
                    if f"Sink Input #{stream_id}" in props_result.stdout and "bluez" in props_result.stdout:
                         subprocess.run(["pactl", "move-sink-input", stream_id, self.NULL_SINK_NAME])
            except (subprocess.CalledProcessError, FileNotFoundError):
                pass # pactl might fail if no streams exist
            time.sleep(2)

    def _move_new_streams(self):
        """Check for new sink-inputs and move them if they are not our playback stream."""
        while not self.stop_event.is_set():
            sink_inputs = audio_utils.list_devices("sink-inputs")
            for si in sink_inputs:
                # Check if it's a BT stream AND not our special playback stream
                is_bt_stream = "bluez" in si.get("properties", {}).get("media.role", "") or \
                               "bluez" in si.get("properties", {}).get("node.name", "")
                is_our_playback = si.get("properties", {}).get("application.name", "") == "BT_HUB_PLAYBACK"

                if is_bt_stream and not is_our_playback:
                    if si.get("sink") != self.null_sink_index:
                        print(f"Moving new stream {si['index']} to null sink.")
                        audio_utils.move_sink_input(si["index"], self.null_sink_index)
            
            time.sleep(self.monitor_interval)
