import network
import utime
from machine import Pin, I2C, WDT, reset
import bme280
from umqtt.simple import MQTTClient
try:
    # Senko ist eine beliebte, minimalistische OTA-Bibliothek für MicroPython
    # Sie muss als senko.py auf dem ESP32 vorhanden sein.
    import senko
    OTA_AVAILABLE = True
except ImportError:
    OTA_AVAILABLE = False
    print("OTA-Bibliothek (senko) nicht gefunden. Überspringe Update-Check.")


# Version
VERSION = "1.0.1"

# WiFi Setup
SSID = "ZTE_9F7AC2"
PASSWORD = "6LE66868TE"

# MQTT Setup
MQTT_BROKER = "81.7.10.99"  # Hier die IP deines Brokers eintragen
MQTT_CLIENT_ID = "BME280_Garten_Sensor"
MQTT_USER = "klaus"            # Falls benötigt
MQTT_PASSWORD = "DHisddS!"          # Falls benötigt
MQTT_TOPIC_PUB = b"test"
TOPIC_TEMP = b"esp32/temperature"
TOPIC_PRES = b"esp32/pressure"
TOPIC_HUM = b"esp32/humidity"

# OTA Setup (Beispiel für GitHub)
OTA_REPO = {
    "user": "klaus-trausner",
    "repo": "BME280-garten-micropython",
    "branch": "main",
    "files": ["main.py", "bme280.py", "senko.py"],
    "working_dir": None  # None oder leerer String für Root-Verzeichnis
}


# Watchdog initialisieren (Timeout 60 Sekunden)
wdt = WDT(timeout=60000)

# Sicherheits-Pause für mpremote/Uploads
print("Warte 3 Sekunden vor dem Start (Strg+C zum Abbrechen)...")
utime.sleep(3)
wdt.feed()

# I2C Setup für BME280 (SCL: GPIO7, SDA: GPIO6)
i2c = I2C(0, scl=Pin(7), sda=Pin(6), freq=100000)
sensor = bme280.BME280(i2c=i2c)

wlan = network.WLAN(network.STA_IF)


def do_connect():
    wlan.active(True)

    # Kurze Pause, damit der Treiber initialisieren kann
    utime.sleep_ms(100)

    if not wlan.isconnected():
        print('Connecting to network...')
        wlan.disconnect()  # Vorherige Versuche zurücksetzen
        wlan.connect(SSID, PASSWORD)

        # Warte maximal 20 Sekunden auf Verbindung (Status 1001 beheben)
        max_wait = 20
        while max_wait > 0:
            if wlan.isconnected():
                break
            max_wait -= 1
            wdt.feed()
            print('Waiting for connection...')
            utime.sleep(1)

    if wlan.isconnected():
        print('Connected! Network config:', wlan.ifconfig())
    else:
        print('Connection failed. Status:', wlan.status())


def check_for_updates():
    if not OTA_AVAILABLE:
        return

    print("Prüfe auf Updates...")
    OTA = senko.Senko(
        user=OTA_REPO["user"],
        repo=OTA_REPO["repo"],
        branch=OTA_REPO["branch"],
        files=OTA_REPO["files"],
        working_dir=OTA_REPO["working_dir"]
    )

    if OTA.update():
        print("Update gefunden und installiert! Starte neu...")
        reset()
    else:
        print("System ist auf dem neuesten Stand.")


def connect_mqtt():
    try:
        client = MQTTClient(MQTT_CLIENT_ID, MQTT_BROKER,
                            user=MQTT_USER, password=MQTT_PASSWORD)
        client.connect()
        print('Connected to MQTT broker:', MQTT_BROKER)
        # Sende eine Testnachricht beim Start
        client.publish(MQTT_TOPIC_PUB, b"ESP32-C3 online")
        return client
    except Exception as e:
        print('Failed to connect to MQTT broker:', e)
        return None


# Hauptschleife
mqtt_client = None
ota_checked = False
print("Starte Hauptschleife...")
print("Version: ", VERSION)

while True:
    wdt.feed()  # System am Leben erhalten
    try:
        # 1. Sicherstellen, dass WLAN verbunden ist
        if not wlan.isconnected():
            ota_checked = False  # Reset für Reconnect
            do_connect()

        # 2. Einmaliger Update-Check nach erfolgreichem WLAN-Connect
        if wlan.isconnected() and not ota_checked:
            try:
                # Kurze Pause, damit sich die SSL/WLAN-Verbindung stabilisiert
                utime.sleep(2)
                check_for_updates()
                ota_checked = True
            except Exception as e:
                print(
                    "OTA-Check vorerst fehlgeschlagen (wird später erneut versucht):", e)

        # 2. Sicherstellen, dass MQTT verbunden ist
        if wlan.isconnected() and mqtt_client is None:
            mqtt_client = connect_mqtt()

        # 3. Messen und Senden
        if mqtt_client:
            temp, pres, hum = sensor.read_values()

            mqtt_client.publish(TOPIC_TEMP, "{:.2f}".format(temp).encode())
            mqtt_client.publish(TOPIC_PRES, "{:.2f}".format(pres).encode())
            mqtt_client.publish(TOPIC_HUM, "{:.2f}".format(hum).encode())

            print("Daten gesendet: {} {:.2f}C, {} {:.2f}hPa, {} {:.2f}%".format(
                TOPIC_TEMP.decode(), temp, TOPIC_PRES.decode(), pres, TOPIC_HUM.decode(), hum))

            # 60 Sekunden warten, dabei aber den Watchdog füttern
            for _ in range(60):
                utime.sleep(1)
                wdt.feed()
        else:
            # Falls kein MQTT, kurz warten und neu versuchen
            utime.sleep(5)

    except Exception as e:
        print("Kritischer Fehler in der Hauptschleife:", e)
        mqtt_client = None  # Client zurücksetzen für Reconnect im nächsten Durchlauf
        utime.sleep(10)
        # Bei massiven Problemen könnte hier auch ein machine.reset() stehen
