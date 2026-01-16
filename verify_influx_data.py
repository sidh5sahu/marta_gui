from influxdb_client import InfluxDBClient
from marta_app.config import load_config

def check_data():
    config = load_config()
    influx_conf = config.get("influxdb", {})
    
    if not influx_conf.get("enabled"):
        print("InfluxDB is not enabled in config.")
        return

    url = influx_conf.get("url")
    token = influx_conf.get("token")
    org = influx_conf.get("org")
    bucket = influx_conf.get("bucket")

    print(f"Connecting to {url}, Org: {org}, Bucket: {bucket}...")
    
    try:
        client = InfluxDBClient(url=url, token=token, org=org)
        query_api = client.query_api()

        # Query last 10 points
        query = f'''
        from(bucket: "{bucket}")
          |> range(start: -1h)
          |> filter(fn: (r) => r["_measurement"] == "marta_logs")
          |> limit(n: 10)
        '''
        
        print("Querying last 1 hour of data...")
        tables = query_api.query(query)
        
        count = 0
        for table in tables:
            for record in table.records:
                print(f"Time: {record.get_time()}, Field: {record.get_field()}, Value: {record.get_value()}")
                count += 1
                
        if count == 0:
            print("No data found in the last hour. (Is the app running and polling?)")
        else:
            print(f"\nFound {count} records.")

    except Exception as e:
        print(f"Query failed: {e}")

if __name__ == "__main__":
    check_data()
