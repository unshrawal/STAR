# Credit to Om Shingare, as I used some code from his ESP32 Simple Web Server, which is under the MIT license (https://github.com/shingareom/ESPProjectSimpleWebServerAuthDemoETI/tree/main)
# Import necessary modules
import time
import network
import socket

from XRPLib.defaults import *
from XRPLib.board import Board
from pestolinkSTARApp import PestoLinkAgent

# Choose the name your robot shows up as in the Bluetooth pairing menu
# Name should be 8 characters max!
robot_name = "XRProver"

# Optional WiFi mode. Leave blank to disable WiFi control.
WIFI_SSID = "Fortunet"
WIFI_PASSWORD = "WayneGretsky18!"
WIFI_PORT = 3540
WIFI_DISCOVERY_PORT = 3541
WEB_PORT = 80
DISCOVERY_REQUEST = "STAR_XRP_DISCOVER"
DISCOVERY_RESPONSE_PREFIX = "STAR_XRP_HERE:"

# Create an instance of the PestoLinkAgent class
pestolink = PestoLinkAgent(robot_name)

board = Board.get_default_board()
currentlyMoving = False
active_cmd = None


def setup_wifi_server():
    if not WIFI_SSID:
        print("WiFi control disabled (no WIFI_SSID set)")
        return None, None, None

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        for _ in range(50):
            if wlan.isconnected():
                break
            time.sleep(0.2)

    if not wlan.isconnected():
        print("WiFi connection failed; BLE-only mode")
        return None, None, None

    ip = wlan.ifconfig()[0]
    print("WiFi connected, XRP IP:", ip)

    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", WIFI_PORT))
    server.listen(1)
    server.settimeout(0)
    
    webserver = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    webserver.bind(('', 80))
    webserver.listen(50)

    discovery_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    discovery_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    discovery_server.bind(("0.0.0.0", WIFI_DISCOVERY_PORT))
    discovery_server.settimeout(0)

    print(f"WiFi command server listening on {ip}:{WIFI_PORT}")
    return server, discovery_server, ip, webserver




def service_discovery(discovery_server, wifi_ip):
    if discovery_server is None or wifi_ip is None:
        return

    try:
        payload, addr = discovery_server.recvfrom(128)
    except OSError:
        return

    req = payload.decode("utf-8").strip()
    if req != DISCOVERY_REQUEST:
        return

    response = f"{DISCOVERY_RESPONSE_PREFIX}{wifi_ip}:{WIFI_PORT}"
    try:
        discovery_server.sendto(response.encode("utf-8"), addr)
    except OSError:
        pass

def read_ble_command():
    if not pestolink.is_connected():
        return None

    if len(pestolink._byte_list) == 0 or pestolink._byte_list[0] != 0x31:
        return None

    try:
        cmd = bytes(pestolink._byte_list).decode("utf-8").strip()
        pestolink._byte_list[0] = 0
        return cmd
    except Exception:
        pestolink._byte_list[0] = 0
        return None


def read_wifi_command(server):
    if server is None:
        return None

    # If a BLE controller is connected, give BLE exclusive control.
    if pestolink.is_connected():
        return None

    conn = None
    try:
        conn, _ = server.accept()
        conn.settimeout(0.2)
        data = conn.recv(128)
        if not data:
            return None
        cmd = data.decode("utf-8").strip()
        if cmd == "ping":
            return None
        return cmd
    except OSError:
        return None
    finally:
        if conn is not None:
            conn.close()

# return webpage HTML
def webPage():
    html = """
    <html>
    <head>
    <title>XRP Web Control</title>
    <style>html{font-family: Arial; display:inline-block; text-align:center;}</style>
    <meta name="referrer" content="no-referrer" />
    </head>
    <body>
    <h1>XRP Web Control</h1>
    <form>
    <select name="direction" id="direction">
    <option>Forward</option>
    <option>Right</option>
    <option>Backward</option>
    <option>Left</option>
    <option>Arm</option>
    </select>
    <input type="number" name="amount" id="amount" placeholder="Enter distance in cm" size=25></input>
    <button type="submit">Send!</button>
	</form>
    </body>
    <script>
    var dropdown = document.getElementById("direction");
    function changePlaceholder() {
    	var selectedDir = dropdown.options[dropdown.selectedIndex].text;
    	if (selectedDir == "Forward" || selectedDir == "Backward") {
    	    document.getElementById("amount").placeholder = "Enter distance in cm";
        } else if (selectedDir == "Right" || selectedDir == "Left"){
        	document.getElementById("amount").placeholder = "Enter amount to turn in degrees";
        } else {
            document.getElementById("amount").placeholder = "Enter arm position in degrees";
        }
    }
    
    dropdown.onchange = changePlaceholder;
    </script>
    </html>
    """
    return html


def execute_command(raw_cmd):
    global currentlyMoving, active_cmd

    parts = raw_cmd.split()
    if len(parts) < 3 or parts[0] != "1":
        return

    currentlyMoving = True
    active_cmd = parts

    if parts[1] == "f":
        drivetrain.straight(float(parts[2]), 0.75)
    elif parts[1] == "r":
        drivetrain.turn(-float(parts[2]), 0.75)
    elif parts[1] == "b":
        drivetrain.straight(-float(parts[2]), 0.75)
    elif parts[1] == "l":
        drivetrain.turn(float(parts[2]), 0.75)
    elif parts[1] == "a":
        servo_one.set_angle(float(parts[2]))
        currentlyMoving = False


wifi_server, discovery_server, wifi_ip, web_server = setup_wifi_server()

# Start an infinite loop
while True:
    # Send webpage to client
    conn, addr = web_server.accept()
    request = str(conn.recv(1024))
    response = webPage()
    conn.send("HTTP/1.1 200 OK\n")
    conn.send("Content-Type: text/html\n")
    conn.send("Connection: close\n\n")
    conn.sendall(response)
    conn.close()
    service_discovery(discovery_server, wifi_ip)
    print(f"request = {request}")
    
    # Process webpage command request
    if (request.find("amount") != -1):
        cmd = request[request.find("/"):request.find("HTTP")]
        cmd = cmd.strip()
        cmd = cmd.split("&")
        cmd[0] = cmd[0][12:][0].lower()
        cmd[1] = cmd[1][7:]
        cmd.insert(0, "1")
        cmd = " ".join(cmd)
        print("Executing command (from web):", cmd)
        execute_command(cmd)

    ble_cmd = read_ble_command()
    wifi_cmd = read_wifi_command(wifi_server)

    if ble_cmd is not None or wifi_cmd is not None:
        board.led_on()
        command_text = ble_cmd if ble_cmd is not None else wifi_cmd
        print("Executing command: ", command_text)
        execute_command(command_text)
    elif not pestolink.is_connected() and wifi_server is None:
        board.led_off()
        servo_one.set_angle(60)
        drivetrain.arcade(0, 0)

    if currentlyMoving and drivetrain.left_motor.get_speed() <= 1 and drivetrain.right_motor.get_speed() <= 1:
        currentlyMoving = False
        print(f"Finished command {active_cmd}, ready for next command")
        pestolink.send(b"Ready for next command")

    time.sleep(0.1)
