import time
import logging

# --- IMPORT HANDLING ---

from datetime import datetime
from pymodbus.client import ModbusTcpClient
from pymodbus.payload import BinaryPayloadBuilder
from pymodbus.constants import Endian

# Debugging threads requre debugpy lib
try:
    import debugpy
    debugpy.debug_this_thread()
    pymodbus_apply_logging_config("DEBUG")
except:
    print("[main] debugpy lib not imported") 

# Toggle extended console output for debugging
DEBUG_MSG = False

# --- INVERTER CONNECTION CONFIGURATION ---
INVERTER_IP = "192.168.178.101"  # Replace with your actual inverter IP
PORT = 1502                     # Kostal Modbus Port
UNIT_ID = 71                    # Kostal Default Unit ID
KEEPALIVE_INTERVAL = 20         # Write cycle in seconds

# Register mapping according to Kostal specifications
REG_WRITE_MAX_SOC = 1044

# --- TIME-BASED SOC SCHEDULE ---
# Format: "DAY": [ (Start_Hour, End_Hour, Target_Max_SoC) ]
# Hours are based on a 24h clock. 
# Make sure time ranges do not overlap on the same day!
DEFAULT_MAX_SOC   = 90.0  # Fallback rule if the current time isn't explicitly in the matrix below
MAX_SOC_CAP       = 80.0  
MAX_SOC_BALANCING = 100.0 

SCHEDULE = {
    "Monday":    [(0,  24, MAX_SOC_CAP)], # Max Soc is capped at 80 percent from 0 to 24
    "Tuesday":   [(0,  24, MAX_SOC_CAP)],
    "Wednesday": [(0,  24, MAX_SOC_CAP)],
    "Thursday":  [(0,  24, MAX_SOC_CAP)],
    "Friday":    [(0,  24, MAX_SOC_CAP)],
    "Saturday":  [(0,  24, MAX_SOC_CAP)],
    "Sunday":    [(0,  24, MAX_SOC_BALANCING)],
}

def debug_message(msg: str):
    if DEBUG_MSG:
        print(msg)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def get_scheduled_soc():
    """Calculates what the upper SoC target should be right now."""
    now = datetime.now()
    current_day = now.strftime("%A")  # Evaluates to e.g., "Monday"
    current_hour = now.hour + (now.minute / 60.0) # Converts current exact time into float format (e.g., 14:30 -> 14.5)

    # Search day configuration
    if current_day in SCHEDULE:
        for start, end, target_soc in SCHEDULE[current_day]:
            if start <= current_hour < end:
                return target_soc, f"Schedule match: {current_day} ({start}:00-{end}:00)"
                
    return DEFAULT_MAX_SOC, "No specific schedule block active; utilizing system fallback default."

def write_float_register(client, address, value):
    """Encodes a float value into Little-Endian CDAB format and transfers it via Modbus TCP."""
    builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.LITTLE) # Forces CDAB byte order
    builder.add_32bit_float(value)
    registers = builder.to_registers()
    
    response = client.write_registers(address, registers, slave=UNIT_ID)
    if response.isError():
        logging.error(f"Failed transmission of value {value} to address {address}")
        debug_message(f"Failed transmission of value {value} to address {address}")
    else:
        debug_message(f"Target Max SoC pushed successfully: {value}%")

if __name__ == "__main__":
    logging.info("Starting Time-Adaptive SoC Limiter Engine...")
    client = ModbusTcpClient(INVERTER_IP, port=PORT)
    
    if not client.connect():
        logging.error(f"Could not open network channel to Plenticore at {INVERTER_IP}:{PORT}")
        
    try:
        while True:
            # Evaluate time matrix targets
            target_soc, reason = get_scheduled_soc()
            logging.info(f"Current Target Evaluation: {target_soc}% | Reason: {reason}")
            
            # Send the value over to the Modbus stack
            write_float_register(client, REG_WRITE_MAX_SOC, float(target_soc))

            # Keep-alive loop enforcement
            time.sleep(KEEPALIVE_INTERVAL)
            
    except KeyboardInterrupt:
        logging.info("Terminating script loop execution. Inverter reverting back to factory parameters.")
    finally:
        client.close()
