"""
A simple script to debug audio device detection.
"""
import subprocess
from audio_utils import get_bt_devices, list_devices

def run_debug():
    """
    Runs a series of checks and prints the output to help diagnose
    why Bluetooth devices might not be appearing in the app.
    """
    print("--- 1. Running 'pactl list cards' ---")
    try:
        pactl_output = subprocess.run(
            ["pactl", "list", "cards"],
            capture_output=True, text=True, check=True
        ).stdout
        print(pactl_output)
    except Exception as e:
        print(f"ERROR: Could not run 'pactl list cards'. {e}")
        print("Please ensure 'pactl' is installed and in your PATH.")
    print("--- End of 'pactl list cards' ---\n")


    print("--- 2. Running 'pactl list sources' ---")
    try:
        sources_output = subprocess.run(
            ["pactl", "list", "sources"],
            capture_output=True, text=True, check=True
        ).stdout
        print(sources_output)
    except Exception as e:
        print(f"ERROR: Could not run 'pactl list sources'. {e}")
    print("--- End of 'pactl list sources' ---\n")


    print("--- 3. Testing get_bt_devices() function ---")
    try:
        bt_devices = get_bt_devices()
        if not bt_devices:
            print("RESULT: get_bt_devices() returned an EMPTY list. No devices found.")
        else:
            print(f"RESULT: get_bt_devices() found {len(bt_devices)} device(s):")
            for i, device in enumerate(bt_devices):
                print(f"\n--- Device {i+1} ---")
                print(f"  Description: {device.get('description')}")
                print(f"  Device Name: {device.get('name')}")
                print(f"  Source Name: {device.get('source_name')}")
                print(f"  Device MAC: {device.get('device_mac')}")
                print(f"  All Properties: {device.get('properties')}")

    except Exception as e:
        print(f"ERROR: The get_bt_devices() function crashed. {e}")
    print("--- End of get_bt_devices() test ---\n")


if __name__ == "__main__":
    run_debug()
