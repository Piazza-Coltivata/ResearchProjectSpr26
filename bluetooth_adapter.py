import dbus
import dbus.mainloop.glib


class BluetoothAdapter:

    def __init__(self, device_name, discoverable, pairable):
        self.device_name = device_name
        self.discoverable = discoverable
        self.pairable = pairable

    def setup(self):
        print("Setting up Bluetooth audio routing...")

        try:
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            bus = dbus.SystemBus()

            manager = dbus.Interface(
                bus.get_object("org.bluez", "/"),
                "org.freedesktop.DBus.ObjectManager",
            )

            adapter_path = None
            for path, interfaces in manager.GetManagedObjects().items():
                if "org.bluez.Adapter1" in interfaces:
                    adapter_path = path
                    break

            if not adapter_path:
                print("ERROR: No Bluetooth adapter found.")
                return False

            adapter = dbus.Interface(
                bus.get_object("org.bluez", adapter_path),
                "org.freedesktop.DBus.Properties",
            )

            adapter.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
            adapter.Set("org.bluez.Adapter1", "Alias", dbus.String(self.device_name))
            adapter.Set(
                "org.bluez.Adapter1",
                "Discoverable",
                dbus.Boolean(self.discoverable),
            )
            adapter.Set(
                "org.bluez.Adapter1", "Pairable", dbus.Boolean(self.pairable)
            )

            print(
                f"Bluetooth adapter configured successfully. Configured as: '{self.device_name}'"
            )
            return True

        except Exception as e:
            print(f"ERROR: Failed to set up Bluetooth audio routing: {e}")
            return False
