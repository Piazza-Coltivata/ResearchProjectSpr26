import argparse
from bt_audio_router import BTAudioRouter


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bluetooth Audio Router")
    parser.add_argument(
        "--test-cycle", action="store_true",
        help="Enable source cycle test mode"
    )
    parser.add_argument(
        "--cycle-interval", type=int, default=5,
        help="Seconds between source switches (default: 5)"
    )
    parser.add_argument(
        "--gui", action="store_true",
        help="Launch the GUI for manual source switching"
    )
    args = parser.parse_args()

    router = BTAudioRouter()
    router.start(test_cycle=args.test_cycle, cycle_interval=args.cycle_interval, gui=args.gui)