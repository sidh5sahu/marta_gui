from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

class InfluxLogger:
    def __init__(self, url, token, org, bucket):
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.client = None
        self.write_api = None
        
        try:
            self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            print(f"InfluxDB client initialized for {self.url} - {self.bucket}")
        except Exception as e:
            print(f"Failed to initialize InfluxDB client: {e}")
            self.client = None

    def log(self, data_dict):
        if not self.client or not self.write_api:
            return

        try:
            # Create a point
            # Assuming 'Event_Type' is a good measurement name, or use a specific measurement
            measurement = "marta_logs"
            
            point = Point(measurement)
            
            # Tags
            if "Event_Type" in data_dict:
                point = point.tag("Event_Type", data_dict["Event_Type"])
            if "Status" in data_dict:
                point = point.tag("Status", data_dict["Status"])
                
            # Fields
            # Iterate through all other items
            for k, v in data_dict.items():
                if k in ["Event_Type", "Status", "Timestamp"]:
                    continue
                
                # Check if value is valid number
                if v == "" or v is None:
                    continue
                
                try:
                    val_float = float(v)
                    point = point.field(k, val_float)
                except (ValueError, TypeError):
                    # If not a number, add as string field? key names suggest mostly numbers
                    point = point.field(k, str(v))
            
            # Timestamp (InfluxDB handles it automatically usually, but we can set it if present)
            # data_dict["Timestamp"] is string usually, Influx expects datetime or int ns
            # If we don't set it, Influx uses server time. Let's start with server time for simplicity unless accuracy is critical.
            
            self.write_api.write(bucket=self.bucket, org=self.org, record=point)
            
        except Exception as e:
            print(f"InfluxDB write failed: {e}")

    def close(self):
        if self.client:
            self.client.close()
