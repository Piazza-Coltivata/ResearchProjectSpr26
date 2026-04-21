"""
PulseAudio/PipeWire utility functions for listing and managing audio devices.
"""
import subprocess
import time

def _pactl(*args):
    """Run a pactl command and return the result, with enhanced logging."""
    command = ["pactl"] + list(args)
    print(f"DEBUG: Running command -> {' '.join(command)}")
    try:
        result = subprocess.run(
            command,
            capture_output=True, text=True, check=True
        )
        # print(f"DEBUG: pactl stdout: {result.stdout.strip()}")
        return result
    except FileNotFoundError:
        print("DEBUG: ERROR - 'pactl' command not found. Is it installed and in your PATH?")
        return None
    except subprocess.CalledProcessError as e:
        print(f"DEBUG: ERROR - pactl command failed with exit code {e.returncode}.")
        print(f"DEBUG: stderr: {e.stderr.strip()}")
        return None
    except Exception as e:
        print(f"DEBUG: An unexpected error occurred with pactl: {e}")
        return None

def list_devices(dev_type="sinks"):
    """List sinks or sources."""
    result = _pactl("list", dev_type)
    if not result:
        return []

    devices = []
    current = {}
    key_map = {
        "Sink #": "index",
        "Source #": "index",
        "Name:": "name",
        "Description:": "description",
    }

    for line in result.stdout.splitlines():
        line = line.strip()
        for key, new_key in key_map.items():
            if line.startswith(key):
                if new_key == "index" and current:
                    devices.append(current)
                current = current.copy() if new_key != "index" else {}
                current[new_key] = line.split(key, 1)[1].strip()
                break
    if current:
        devices.append(current)
    return devices

def _normalize_mac(value):
    """Normalize Bluetooth MAC addresses to uppercase colon-separated form."""
    if not value:
        return ""

    mac = value.replace("_", ":").replace("-", ":").upper()
    parts = [part for part in mac.split(":") if part]
    if len(parts) >= 6 and all(len(part) <= 2 for part in parts[:6]):
        return ":".join(part.zfill(2) for part in parts[:6])
    return mac

def _extract_mac(name):
    """Extract a MAC address from a bluez_* PulseAudio/PipeWire object name."""
    if not name:
        return ""

    suffix = name
    for prefix in ("bluez_input.", "bluez_output.", "bluez_card.", "bluez_source."):
        if name.startswith(prefix):
            suffix = name[len(prefix):]
            break

    return _normalize_mac(suffix.split(".", 1)[0])

def _list_bt_cards():
    """Return Bluetooth card objects from pactl."""
    cards_result = _pactl("list", "cards")
    if not cards_result:
        return []

    cards = []
    current_card = {}
    for raw_line in cards_result.stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("Card #"):
            if current_card and "bluez_card" in current_card.get("name", ""):
                cards.append(current_card)
            current_card = {}
        elif line.startswith("Name:"):
            current_card["name"] = line.split("Name:", 1)[1].strip()
        elif line.startswith("Properties:"):
            current_card["properties"] = {}
        elif current_card and "properties" in current_card and "=" in line:
            key, val = line.split("=", 1)
            current_card["properties"][key.strip()] = val.strip().strip('"')

    if current_card and "bluez_card" in current_card.get("name", ""):
        cards.append(current_card)

    return cards

def _build_bt_description(source, card, device_mac):
    """Choose the best available user-facing label for a Bluetooth source."""
    card_properties = card.get("properties", {}) if card else {}
    generic_labels = {
        "BT Device",
        "Bluetooth Audio",
        "Bluetooth Speaker",
        "Bluetooth Headset",
    }

    candidates = [
        card_properties.get("device.alias"),
        card_properties.get("device.description"),
        card_properties.get("device.product.name"),
        source.get("description"),
    ]

    fallback = None
    for candidate in candidates:
        if not candidate:
            continue
        if fallback is None:
            fallback = candidate
        if candidate not in generic_labels:
            return f"{candidate} ({device_mac})" if device_mac else candidate

    if fallback:
        return f"{fallback} ({device_mac})" if device_mac else fallback
    return f"BT Device {device_mac}" if device_mac else "BT Device"

def ensure_a2dp_sink(card_name):
    """
    Checks if a card has an 'a2dp-sink' profile and sets it if not active.
    Returns True if the card is ready, False otherwise.
    """
    card_info = _pactl("list", "cards")
    if not card_info:
        return False

    in_card_section = False
    active_profile = ""
    has_a2dp_sink = False

    for line in card_info.stdout.splitlines():
        line = line.strip()
        if f"Name: {card_name}" in line:
            in_card_section = True
            continue
        
        if in_card_section:
            if line.startswith("Card #"): # Reached the next card
                break
            if "a2dp-sink" in line:
                has_a2dp_sink = True
            if line.startswith("Active Profile:") and "a2dp-sink" in line:
                # Already in the correct mode
                return True
    
    if in_card_section and has_a2dp_sink:
        print(f"Card '{card_name}' is not in a2dp-sink mode. Attempting to set it...")
        result = _pactl("set-card-profile", card_name, "a2dp-sink")
        if result and result.returncode == 0:
            print("Successfully set profile to a2dp-sink.")
            time.sleep(1) # Give the system a moment to apply the change
            return True
        else:
            print(f"Failed to set profile for '{card_name}'.")
            return False
    
    return False


def get_bt_devices():
    """
    Return Bluetooth audio inputs that can be routed by the hub.

    Active phone streams appear as bluez_input/bluez_source objects. We also keep
    Bluetooth cards around for friendly names, and include card-only devices that
    do not look like speaker outputs so the UI can still show an idle phone.
    """
    all_sources = list_devices("sources")
    all_sinks = list_devices("sinks")
    bt_input_sources = [
        source for source in all_sources
        if source.get("name", "").startswith(("bluez_input.", "bluez_source."))
    ]
    bt_output_sink_macs = {
        _extract_mac(sink.get("name", ""))
        for sink in all_sinks
        if sink.get("name", "").startswith("bluez_output.")
    }

    cards_by_mac = {}
    for card in _list_bt_cards():
        card_mac = _normalize_mac(card.get("properties", {}).get("device.string", "")) or _extract_mac(card.get("name", ""))
        if card_mac:
            cards_by_mac[card_mac] = card

    processed_devices = []
    seen_macs = set()

    for source in bt_input_sources:
        device_mac = _extract_mac(source.get("name", ""))
        card = cards_by_mac.get(device_mac)
        source["device_mac"] = device_mac
        source["is_active_source"] = True
        source["source_name"] = source.get("name")
        source["monitor_source_name"] = source.get("name")
        source["description"] = _build_bt_description(source, card, device_mac)
        processed_devices.append(source)
        if device_mac:
            seen_macs.add(device_mac)

    for device_mac, card in cards_by_mac.items():
        if device_mac in seen_macs or device_mac in bt_output_sink_macs:
            continue
        idle_description = _build_bt_description({}, card, device_mac)
        processed_devices.append({
            "name": card.get("name"),
            "description": f"{idle_description} [idle]",
            "device_mac": device_mac,
            "is_active_source": False,
            "source_name": None,
            "monitor_source_name": None,
            "properties": card.get("properties", {}),
        })

    processed_devices.sort(
        key=lambda device: (
            device.get("source_name") is None,
            device.get("description", "").lower(),
        )
    )
    return processed_devices

def debug_print_all_audio():
    print("\n=== DEBUG: pactl list sources short ===")
    subprocess.run(["pactl", "list", "sources", "short"])
    print("\n=== DEBUG: pactl list sinks short ===")
    subprocess.run(["pactl", "list", "sinks", "short"])
    print("\n=== DEBUG: pactl list cards short ===")
    subprocess.run(["pactl", "list", "cards", "short"])

# Call this at the top-level when the module is run
if __name__ == "__main__":
    debug_print_all_audio()