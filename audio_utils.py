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
            capture_output=True,
        )
        # Decode with replacement so non-UTF-8 device names don't crash the app.
        result_text = type('R', (), {
            'stdout': result.stdout.decode('utf-8', errors='replace'),
            'stderr': result.stderr.decode('utf-8', errors='replace'),
            'returncode': result.returncode,
        })()
        return result_text
    except FileNotFoundError:
        print("DEBUG: ERROR - 'pactl' command not found. Is it installed and in your PATH?")
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

def _normalize_profile_name(value):
    """Normalize PulseAudio/PipeWire profile names for comparison."""
    return (value or "").strip().replace("_", "-")

def _profile_matches(profile_name, desired_profile):
    """Return True when a profile matches a base role, including codec suffixes."""
    normalized_profile = _normalize_profile_name(profile_name)
    normalized_desired = _normalize_profile_name(desired_profile)
    return (
        normalized_profile == normalized_desired
        or normalized_profile.startswith(f"{normalized_desired}-")
    )

def _choose_card_profile(card, desired_profile):
    """Pick the best available profile on a card for the requested BT role."""
    active_profile = card.get("active_profile", "")
    if _profile_matches(active_profile, desired_profile):
        return active_profile

    matching_profiles = [
        profile for profile in card.get("profiles", [])
        if _profile_matches(profile.get("name", ""), desired_profile)
    ]
    if not matching_profiles:
        return None

    def _profile_rank(profile):
        availability = (profile.get("available") or "").lower()
        normalized_name = _normalize_profile_name(profile.get("name", ""))
        normalized_desired = _normalize_profile_name(desired_profile)
        return (
            0 if availability == "yes" else 1 if availability in ("", "unknown") else 2,
            0 if normalized_name == normalized_desired else 1,
            normalized_name,
        )

    return sorted(matching_profiles, key=_profile_rank)[0].get("name")

def _list_bt_cards():
    """Return Bluetooth card objects from pactl."""
    cards_result = _pactl("list", "cards")
    if not cards_result:
        return []

    cards = []
    all_card_names = []
    current_card = None
    current_section = None

    def finalize_current_card(card):
        if not card:
            return
        card.setdefault("properties", {})
        card.setdefault("profiles", [])
        card.setdefault("active_profile", "")
        name = card.get("name", "")
        all_card_names.append(name)
        if "bluez_card" in name:
            cards.append(card)

    for raw_line in cards_result.stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("Card #"):
            finalize_current_card(current_card)
            current_card = {}
            current_section = None
        elif line.startswith("Name:"):
            current_card["name"] = line.split("Name:", 1)[1].strip()
            current_section = None
        elif line.startswith("Properties:"):
            current_card["properties"] = {}
            current_section = "properties"
        elif line.startswith("Profiles:"):
            current_card["profiles"] = []
            current_section = "profiles"
        elif line.startswith("Active Profile:"):
            current_card["active_profile"] = line.split("Active Profile:", 1)[1].strip()
            current_section = None
        elif line.startswith(("Ports:", "Active Port:")):
            current_section = None
        elif current_section == "properties" and current_card and "=" in line:
            key, val = line.split("=", 1)
            current_card["properties"][key.strip()] = val.strip().strip('"')
        elif current_section == "profiles" and current_card and ":" in line:
            profile_name, profile_details = line.split(":", 1)
            profile_name = profile_name.strip()
            if profile_name:
                availability = ""
                if "available:" in profile_details:
                    availability = profile_details.rsplit("available:", 1)[1].rstrip(")").strip()
                current_card["profiles"].append({
                    "name": profile_name,
                    "available": availability,
                })

    finalize_current_card(current_card)

    print(f"BT_CARDS: all cards found: {all_card_names}")
    return cards

def _list_pipewire_bluez_input_nodes():
    """Return active Bluetooth input/source nodes discovered from pw-link."""
    try:
        result = subprocess.run(
            ["pw-link", "-iol"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    node_ports = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("|") or " (" in line or ":" not in line:
            continue

        node_name, port_name = line.rsplit(":", 1)
        node_ports.setdefault(node_name, set()).add(port_name)

    active_nodes = []
    for node_name, ports in node_ports.items():
        if not node_name.startswith(("bluez_input.", "bluez_source.")):
            continue
        if any(port.startswith(("output_", "monitor_", "capture_")) for port in ports):
            active_nodes.append(node_name)

    return sorted(active_nodes)

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

def _format_card_profiles(card):
    """Render a card's available profile names and availability for logs."""
    profiles = card.get("profiles", [])
    if not profiles:
        return "[none]"
    return ", ".join(
        f"{profile.get('name')} [{profile.get('available') or 'unknown'}]"
        for profile in profiles
        if profile.get("name")
    )

def _append_to_log_file(log_file, content):
    """Append debug information to the shared pipeline log."""
    if not log_file or not content:
        return
    try:
        with open(log_file, "a") as log_handle:
            log_handle.write(content)
    except IOError as error:
        print(f"Error writing to log file {log_file}: {error}")

def _ensure_card_profile(card, desired_profile, log_file=None, action_label="PROFILE"):
    """Ensure a BT card is using the best matching available profile."""
    card_name = card.get("name", "")
    active_profile = card.get("active_profile", "")
    target_profile = _choose_card_profile(card, desired_profile)
    desired_label = _normalize_profile_name(desired_profile)
    log_lines = [
        f"{action_label}: {card_name}\n",
        f"  Active Profile: {active_profile or '[none]'}\n",
        f"  Available Profiles: {_format_card_profiles(card)}\n",
        f"  Selected Target Profile: {target_profile or '[none]'}\n",
    ]

    if not target_profile:
        log_lines.append(f"  Result: no matching {desired_label} profile was found.\n\n")
        _append_to_log_file(log_file, "".join(log_lines))
        print(
            f"{action_label}: {card_name} has no matching {desired_label} profile. "
            f"Profiles: {_format_card_profiles(card)}"
        )
        return False

    if _profile_matches(active_profile, desired_profile):
        log_lines.append("  Result: already active.\n\n")
        _append_to_log_file(log_file, "".join(log_lines))
        print(f"{action_label}: {card_name} already using {active_profile}.")
        return True

    command = ["pactl", "set-card-profile", card_name, target_profile]
    log_lines.append(f"  Command: {' '.join(command)}\n")
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        log_lines.append("  Result: command timed out.\n\n")
        _append_to_log_file(log_file, "".join(log_lines))
        print(f"{action_label}: Timed out while setting {card_name} to {target_profile}.")
        return False
    except Exception as error:
        log_lines.append(f"  Exception: {error}\n  Result: failed.\n\n")
        _append_to_log_file(log_file, "".join(log_lines))
        print(f"{action_label}: Exception while setting {card_name}: {error}")
        return False

    log_lines.extend([
        f"  Return Code: {result.returncode}\n",
        f"  Stdout: {result.stdout.strip()}\n",
        f"  Stderr: {result.stderr.strip()}\n",
        "  Result: success.\n\n" if result.returncode == 0 else "  Result: failed.\n\n",
    ])
    _append_to_log_file(log_file, "".join(log_lines))

    if result.returncode == 0:
        print(f"{action_label}: Successfully set {card_name} to {target_profile}.")
        return True

    print(f"{action_label}: Failed to set {card_name} to {target_profile}.")
    return False

def ensure_a2dp_sink(card_name):
    """
    Checks if a card has an A2DP sink profile and sets the best match if needed.
    Returns True if the card is ready, False otherwise.
    """
    card = next((card for card in _list_bt_cards() if card.get("name") == card_name), None)
    if not card:
        print(f"Card '{card_name}' was not found in 'pactl list cards'.")
        return False

    if _ensure_card_profile(card, "a2dp-sink", action_label="ENSURE_A2DP_SINK"):
        time.sleep(1)
        return True
    return False

def ensure_a2dp_source(card_name, log_file=None):
    """Ensure a BT source card is using its best available A2DP source profile."""
    card = next((card for card in _list_bt_cards() if card.get("name") == card_name), None)
    if not card:
        _append_to_log_file(
            log_file,
            f"ENSURE_A2DP_SOURCE: {card_name}\n  Result: card not found in pactl list cards.\n\n",
        )
        print(f"ENSURE_A2DP_SOURCE: Card '{card_name}' was not found.")
        return False

    return _ensure_card_profile(
        card,
        "a2dp-source",
        log_file=log_file,
        action_label="ENSURE_A2DP_SOURCE",
    )


def get_bt_devices():
    """
    Return Bluetooth audio inputs that can be routed by the hub.

    Active phone streams appear as bluez_input/bluez_source objects. We also keep
    Bluetooth cards around for friendly names, and include card-only devices that
    do not look like speaker outputs so the UI can still show an idle phone.
    """
    all_sources = list_devices("sources")
    all_sinks = list_devices("sinks")
    sources_by_name = {
        source.get("name"): dict(source)
        for source in all_sources
        if source.get("name")
    }
    bt_input_source_names = {
        source_name for source_name in sources_by_name
        if source_name.startswith(("bluez_input.", "bluez_source."))
    }
    bt_input_source_names.update(_list_pipewire_bluez_input_nodes())
    bt_output_sink_macs = {
        _extract_mac(sink.get("name", ""))
        for sink in all_sinks
        if sink.get("name", "").startswith("bluez_output.")
    }

    # Exclude any BT input whose MAC matches a BT output sink — those are the
    # speaker's own HFP/SCO microphone, not a phone source.
    bt_input_source_names = {
        name for name in bt_input_source_names
        if _extract_mac(name) not in bt_output_sink_macs
    }

    cards_by_mac = {}
    for card in _list_bt_cards():
        card_mac = _normalize_mac(card.get("properties", {}).get("device.string", "")) or _extract_mac(card.get("name", ""))
        if card_mac:
            cards_by_mac[card_mac] = card

    processed_devices = []
    seen_macs = set()

    for source_name in sorted(bt_input_source_names):
        source = dict(sources_by_name.get(source_name, {"name": source_name, "description": source_name}))
        device_mac = _extract_mac(source_name)
        card = cards_by_mac.get(device_mac)
        source["device_mac"] = device_mac
        source["is_active_source"] = True
        source["source_name"] = source_name
        source["monitor_source_name"] = source_name
        source["description"] = _build_bt_description(source, card, device_mac)
        processed_devices.append(source)
        if device_mac:
            seen_macs.add(device_mac)

    for device_mac, card in cards_by_mac.items():
        if device_mac in seen_macs or device_mac in bt_output_sink_macs:
            continue
        if not _choose_card_profile(card, "a2dp-source"):
            print(
                f"BT_DISCOVERY: skipping {card.get('name')} because it has no "
                f"A2DP source profile."
            )
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

    print(f"BT_DISCOVERY: sink MACs (excluded from sources): {bt_output_sink_macs}")
    print(f"BT_DISCOVERY: active input nodes: {sorted(bt_input_source_names)}")
    print(f"BT_DISCOVERY: cards by MAC: {list(cards_by_mac.keys())}")
    print(f"BT_DISCOVERY: final device list: {[d['description'] for d in processed_devices]}")

    return processed_devices

def activate_bt_source_cards(exclude_macs=None, log_file=None):
    """
    Set all BT phone cards to their best matching A2DP source profile,
    skipping any whose MAC is in exclude_macs (typically the speaker).
    Called on startup to wake up phones that were set to 'off' on the last
    close, and before hub start. Returns the count of cards that are ready.
    """
    if exclude_macs is None:
        exclude_macs = set()
    exclude_macs = {_normalize_mac(m) for m in exclude_macs}

    activated = 0
    _append_to_log_file(log_file, "--- Activating BT Source Cards ---\n")

    for card in _list_bt_cards():
        card_name = card.get("name", "")
        card_mac = _normalize_mac(
            card.get("properties", {}).get("device.string", "")
        ) or _extract_mac(card_name)
        
        if card_mac in exclude_macs:
            _append_to_log_file(
                log_file,
                f"ACTIVATE: Skipping {card_name} (identified as speaker)\n",
            )
            continue
        _append_to_log_file(
            log_file,
            f"Attempted to activate card: {card_name} (MAC: {card_mac})\n",
        )
        if _ensure_card_profile(card, "a2dp-source", log_file=log_file, action_label="ACTIVATE"):
            activated += 1
            
    return activated


def deactivate_bt_source_cards(exclude_macs=None):
    """
    Set all BT phone cards to 'off' profile, skipping the speaker.
    Called on app close so WirePlumber cannot auto-route phones after exit.
    Uses _list_bt_cards() directly so it catches cards not currently streaming.
    """
    if exclude_macs is None:
        exclude_macs = set()
    exclude_macs = {_normalize_mac(m) for m in exclude_macs}

    for card in _list_bt_cards():
        card_name = card.get("name", "")
        card_mac = _normalize_mac(
            card.get("properties", {}).get("device.string", "")
        ) or _extract_mac(card_name)
        if card_mac in exclude_macs:
            continue
        _pactl("set-card-profile", card_name, "off")
        print(f"DEACTIVATE: {card_name} -> off")


def debug_print_all_audio():
    print("\n=== DEBUG: pactl list sources short ===")
    subprocess.run(["pactl", "list", "sources", "short"])
    print("\n=== DEBUG: pactl list sinks short ===")
    subprocess.run(["pactl", "list", "sinks", "short"])
    print("\n=== DEBUG: pactl list cards short ===")
    subprocess.run(["pactl", "list", "cards", "short"])
    print("\n=== DEBUG: active Bluetooth input nodes from pw-link ===")
    for node_name in _list_pipewire_bluez_input_nodes():
        print(node_name)

# Call this at the top-level when the module is run
if __name__ == "__main__":
    debug_print_all_audio()