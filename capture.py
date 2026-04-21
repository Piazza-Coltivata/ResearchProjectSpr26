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
    STEREO_SOURCE_PORTS = (
        ("output_FL", "output_FR"),
        ("monitor_FL", "monitor_FR"),
        ("capture_FL", "capture_FR"),
    )
    MONO_SOURCE_PORTS = ("output_MONO", "monitor_MONO", "capture_MONO")

    def __init__(self, source_name, sink_name):
        """
        Creates links between the given source and sink using the ports that exist.
        """
        self.source_name = source_name
        self.sink_name = sink_name
        self.link_ports = []
        self.created_link_ports = []
        self._running = False
        self.last_error = None

        if not self.source_name or not self.sink_name:
            self.last_error = "Missing source or sink selection."
            print(f"ERROR: {self.last_error}")
            return

        if self.source_name == self.sink_name:
            self.last_error = "Source and sink cannot be the same node."
            print(f"ERROR: {self.last_error}")
            return

        self._running = self._link_source_to_sink(self.source_name, self.sink_name)

    def _get_available_ports(self):
        try:
            result = subprocess.run(["pw-link", "-iol"], capture_output=True, text=True, check=True)
        except Exception as error:
            self.last_error = f"Could not inspect PipeWire ports: {error}"
            error_log_file.write(f"ERROR: {self.last_error}\n")
            error_log_file.flush()
            return set()

        error_log_file.write("\n--- Available PipeWire Ports (pw-link -iol) ---\n")
        error_log_file.write(result.stdout)
        error_log_file.write("\n--- End of Ports ---\n")
        error_log_file.flush()

        ports = set()
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("|") or " (" in line:
                continue
            ports.add(line)
        return ports

    def _resolve_link_ports(self, source_name, sink_name, ports):
        sink_left = f"{sink_name}:playback_FL"
        sink_right = f"{sink_name}:playback_FR"
        if sink_left not in ports or sink_right not in ports:
            self.last_error = f"Speaker ports were not found for {sink_name}."
            return []

        for left_suffix, right_suffix in self.STEREO_SOURCE_PORTS:
            source_left = f"{source_name}:{left_suffix}"
            source_right = f"{source_name}:{right_suffix}"
            if source_left in ports and source_right in ports:
                return [(source_left, sink_left), (source_right, sink_right)]

        for mono_suffix in self.MONO_SOURCE_PORTS:
            source_mono = f"{source_name}:{mono_suffix}"
            if source_mono in ports:
                return [(source_mono, sink_left), (source_mono, sink_right)]

        self.last_error = f"No compatible source ports were found for {source_name}."
        return []

    def _run_link_command(self, source_port, sink_port, disconnect=False):
        action = "unlink" if disconnect else "link"
        print(f"DEBUG: Attempting to {action} {source_port} -> {sink_port}")
        error_log_file.write(f"Attempting to {action} {source_port} -> {sink_port}\n")
        error_log_file.flush()

        command = ["pw-link"]
        if disconnect:
            command.append("-d")
        command.extend([source_port, sink_port])

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )
        if result.stdout:
            error_log_file.write(result.stdout)
        if result.stderr:
            error_log_file.write(result.stderr)
        error_log_file.flush()

        if result.returncode == 0:
            return "created"

        stderr_text = (result.stderr or "").lower()
        if not disconnect and "file exists" in stderr_text:
            return "exists"
        if disconnect and ("no such file" in stderr_text or "not linked" in stderr_text or "does not exist" in stderr_text):
            return "missing"
        return "error"

    def _unlink_links(self, links):
        for source_port, sink_port in links:
            outcome = self._run_link_command(source_port, sink_port, disconnect=True)
            if outcome == "error":
                print(f"ERROR: pw-link -d failed for {source_port} -> {sink_port}. Check pipeline_errors.log")

    def _link_source_to_sink(self, source_name, sink_name):
        ports = self._get_available_ports()
        if not ports:
            if not self.last_error:
                self.last_error = "No PipeWire ports were available."
            return False

        requested_links = self._resolve_link_ports(source_name, sink_name, ports)
        if not requested_links:
            error_log_file.write(f"ERROR: {self.last_error}\n")
            error_log_file.flush()
            return False

        active_links = []
        created_links = []
        for source_port, sink_port in requested_links:
            outcome = self._run_link_command(source_port, sink_port)
            if outcome in ("created", "exists"):
                active_links.append((source_port, sink_port))
                if outcome == "created":
                    created_links.append((source_port, sink_port))
                continue

            self.last_error = f"Failed to link {source_port} -> {sink_port}."
            self._unlink_links(created_links)
            self.link_ports = []
            self.created_link_ports = []
            return False

        self.source_name = source_name
        self.sink_name = sink_name
        self.link_ports = active_links
        self.created_link_ports = created_links
        self.last_error = None
        return True

    def switch_source(self, source_name):
        if not source_name:
            self.last_error = "The selected phone is not currently streaming audio."
            return False
        if not self._running:
            self.last_error = "The hub is not running."
            return False
        if source_name == self.source_name:
            return True

        previous_source = self.source_name
        previous_links = list(self.link_ports)
        previous_created_links = list(self.created_link_ports)
        self._unlink_links(previous_links)
        self.link_ports = []
        self.created_link_ports = []

        if self._link_source_to_sink(source_name, self.sink_name):
            self._running = True
            return True

        failed_error = self.last_error
        if previous_links:
            self._link_source_to_sink(previous_source, self.sink_name)
            if previous_created_links and not self.created_link_ports:
                self.created_link_ports = previous_created_links
        self._running = bool(self.link_ports)
        self.last_error = failed_error
        return False

    def stop(self):
        self._unlink_links(self.created_link_ports)
        self.link_ports = []
        self.created_link_ports = []
        self._running = False
        print("PipeWire links stopped.")

    def is_running(self):
        return self._running

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
        self._preserved_tokens = set()

    def set_active_source(self, source_name=None, device_mac=None):
        """Remember identifiers for the Bluetooth stream that should keep playing."""
        tokens = set()
        if source_name:
            lowered = source_name.lower()
            tokens.add(lowered)
            tokens.add(lowered.replace(":", "_"))
            tokens.add(lowered.replace("_", ":"))
        if device_mac:
            lowered_mac = device_mac.lower()
            tokens.add(lowered_mac)
            tokens.add(lowered_mac.replace(":", "_"))
            tokens.add(lowered_mac.replace(":", "-"))
        self._preserved_tokens = {token for token in tokens if token}

    def _should_preserve_block(self, block):
        """True when the sink-input block belongs to the selected Bluetooth source."""
        if not self._preserved_tokens:
            return False
        block_text = block.lower()
        return any(token in block_text for token in self._preserved_tokens)

    def setup(self):
        """Creates the null sink module if not already present."""
        self.teardown()
        result = subprocess.run(
            ["pactl", "load-module", "module-null-sink",
             f"sink_name={self.NULL_SINK_NAME}",
             f"sink_properties=device.description='{self.NULL_SINK_NAME}'"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            self._module_id = result.stdout.strip()
            print(f"Null sink created (module {self._module_id}).")
            return True
        print(f"Error creating null sink: {result.stderr}")
        return False

    def teardown(self):
        """Removes the null sink."""
        if self._module_id:
            subprocess.run(["pactl", "unload-module", self._module_id],
                           capture_output=True, text=True)
            print("Null sink removed.")
            self._module_id = None
        # Also sweep for any stale instance left from a previous run.
        sinks_result = subprocess.run(
            ["pactl", "list", "short", "modules"],
            capture_output=True, text=True
        )
        for line in sinks_result.stdout.splitlines():
            if self.NULL_SINK_NAME in line:
                mod_id = line.split()[0]
                subprocess.run(["pactl", "unload-module", mod_id],
                               capture_output=True, text=True)
                print(f"Found and removed stale null sink (module {mod_id}).")

    def silence_sources(self, source_names, active_source_name):
        """
        Route non-active BT sources to the null sink using pw-link at the
        PipeWire graph level, and disconnect them from all other sinks.
        The active source is left untouched.
        """
        if not self._module_id:
            return

        try:
            result = subprocess.run(["pw-link", "-iol"],
                                    capture_output=True, text=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return

        ports = set()
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if line and not line.startswith("|") and " (" not in line and ":" in line:
                ports.add(line)

        null_sink_left  = f"{self.NULL_SINK_NAME}:playback_FL"
        null_sink_right = f"{self.NULL_SINK_NAME}:playback_FR"
        if null_sink_left not in ports:
            return

        for source_name in source_names:
            if source_name == active_source_name:
                continue
            for left_s, right_s in (("output_FL", "output_FR"),
                                    ("monitor_FL", "monitor_FR"),
                                    ("capture_FL", "capture_FR")):
                src_left  = f"{source_name}:{left_s}"
                src_right = f"{source_name}:{right_s}"
                if src_left in ports and src_right in ports:
                    subprocess.run(["pw-link", src_left,  null_sink_left],
                                   capture_output=True, text=True)
                    subprocess.run(["pw-link", src_right, null_sink_right],
                                   capture_output=True, text=True)
                    print(f"Silenced {source_name} → null sink")
                    break
            for mono_s in ("output_MONO", "monitor_MONO", "capture_MONO"):
                src_mono = f"{source_name}:{mono_s}"
                if src_mono in ports:
                    subprocess.run(["pw-link", src_mono, null_sink_left],
                                   capture_output=True, text=True)
                    subprocess.run(["pw-link", src_mono, null_sink_right],
                                   capture_output=True, text=True)
                    print(f"Silenced (mono) {source_name} → null sink")
                    break
