class DeviceManager:

    def __init__(self):
        self.connected_devices = {}

    def add_device(self, address, name=None):
        self.connected_devices[address] = name or address
        print(f"Device connected: {self.connected_devices[address]} ({address})")

    def remove_device(self, address):
        name = self.connected_devices.pop(address, address)
        print(f"Device disconnected: {name} ({address})")

    def list_devices(self):
        return dict(self.connected_devices)
