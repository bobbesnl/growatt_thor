from datetime import datetime

class GrowattCoordinator:
    def __init__(self, hass):
        self.hass = hass
        self.charge_point_id = None
        self.status = None
        self.power = None
        self.energy = None

    def now(self):
        return datetime.utcnow().isoformat() + "Z"

    def set_charge_point(self, cp_id):
        self.charge_point_id = cp_id

    def set_status(self, status):
        self.status = status

    def process_meter_values(self, meter_values):
        for entry in meter_values:
            for sample in entry.get("sampledValue", []):
                meas = sample.get("measurand")
                val = sample.get("value")

                if meas == "Power.Active.Import":
                    self.power = float(val)
                elif meas == "Energy.Active.Import.Register":
                    self.energy = float(val)

