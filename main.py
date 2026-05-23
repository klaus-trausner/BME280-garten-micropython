import network
import utime
import gc
from machine import Pin, I2C, WDT, reset
import bme280
from umqtt.simple import MQTTClient
import config

try:
    import senko
    OTA_AVAILABLE = True
except ImportError:
    OTA_AVAILABLE = False
    print("OTA-Bibliothek (senko) nicht gefunden. Überspringe Update-Check.")


# Version

VERSION = "1.1.0"

# MQTT Topics
MQTT_CLIENT_ID = "BME280_Garten_Sensor"
MQTT_TOPIC_PUB = b"test"
TOPIC_TEMP     = b"esp32/temperature"
TOPIC_PRES     = b"esp32/pressure"
TOPIC_HUM      = b"esp32/humidity"
TOPIC_STATUS   = b"esp32/status"
TOPIC_VERSION  = b"esp32/version"

# OTA Setup (GitHub)
OTA_REPO = {
    "user":        "klaus-trausner",
    "repo":        "BME280-garten-micropython",
    "branch":      "main",
    "files":       ["main.py", "bme280.py", "senko.py"],  # config.py NICHT updaten!
    "working_dir": ""
}

# Resilienz-Parameter
MAX_ERRORS      = 5     # Anzahl aufeinanderfolgender Fehler → machine.reset()
SLEEP_INTERVAL  = 60    # Sekunden zwischen den Messungen
MQTT_KEEPALIVE  = 30    # Sekunden – muss < Broker-Timeout sein
ERROR_BACKOFF   = 10    # Sekunden warten nach einem Fehler


# =============================================================================
# Watchdog (Timeout 90 s, > 60 s Schlafzeit + Puffer für OTA/MQTT)
# =============================================================================
wdt = WDT(timeout=90000)

# Sicherheits-Pause für mpremote/Uploads
print("Version:", VERSION)
print("Warte 3 Sekunden vor dem Start (Strg+C zum Abbrechen)...")
utime.sleep(3)
wdt.feed()


# =============================================================================
# Globale Objekte
# =============================================================================
wlan        = network.WLAN(network.STA_IF)
sensor      = None
mqtt_client = None
error_count = 0


# =============================================================================
# Hilfsfunktionen
# =============================================================================

def init_sensor():
    """I2C und BME280 einmalig initialisieren. Gibt True bei Erfolg zurück."""
    global sensor
    try:
        i2c    = I2C(0, scl=Pin(7), sda=Pin(6), freq=100000)
        sensor = bme280.BME280(i2c=i2c)
        print("BME280 initialisiert.")
        return True
    except Exception as e:
        print("BME280 Init-Fehler:", e)
        sensor = None
        return False


def do_connect():
    """WiFi verbinden. Gibt True zurück, wenn verbunden."""
    wlan.active(True)
    utime.sleep_ms(100)

    if wlan.isconnected():
        return True

    print("Verbinde mit WLAN:", config.SSID)
    wlan.disconnect()
    wlan.connect(config.SSID, config.PASSWORD)

    for _ in range(20):          # max. 20 s warten
        wdt.feed()
        if wlan.isconnected():
            print("WLAN verbunden:", wlan.ifconfig())
            return True
        print("  ... warte auf WLAN")
        utime.sleep(1)

    print("WLAN-Verbindung fehlgeschlagen. Status:", wlan.status())
    return False


def check_for_updates():
    """OTA-Update prüfen und bei Bedarf installieren."""
    if not OTA_AVAILABLE or not wlan.isconnected():
        return

    gc.collect()
    print("Prüfe auf OTA-Updates...")
    try:
        ota = senko.Senko(
            user=OTA_REPO["user"],
            repo=OTA_REPO["repo"],
            branch=OTA_REPO["branch"],
            files=OTA_REPO["files"],
            working_dir=OTA_REPO["working_dir"]
        )
        wdt.feed()
        if ota.update():
            print("Update installiert – starte neu...")
            reset()
        else:
            print("System ist aktuell.")
    except Exception as e:
        print("OTA-Fehler (nicht kritisch):", e)
    wdt.feed()


def connect_mqtt():
    """MQTT-Verbindung aufbauen. Gibt Client-Objekt oder None zurück."""
    try:
        client = MQTTClient(
            MQTT_CLIENT_ID,
            config.MQTT_BROKER,
            user=config.MQTT_USER,
            password=config.MQTT_PASSWORD,
            keepalive=MQTT_KEEPALIVE
        )
        # Last Will einrichten (Broker sendet "offline" bei Verbindungsverlust)
        client.set_last_will(TOPIC_STATUS, b"offline", retain=True)
        
        client.connect()
        print("MQTT verbunden:", config.MQTT_BROKER)
        
        # Status und Version als Retained Messages veröffentlichen
        client.publish(TOPIC_STATUS, b"online", retain=True)
        client.publish(TOPIC_VERSION, VERSION.encode(), retain=True)
        
        # Optionaler abwärtskompatibler Test-Publish
        client.publish(MQTT_TOPIC_PUB, b"ESP32-C3 online v" + VERSION.encode())
        
        return client
    except Exception as e:
        print("MQTT-Verbindungsfehler:", e)
        return None


def disconnect_mqtt():
    """MQTT sauber trennen, Fehler ignorieren."""
    global mqtt_client
    if mqtt_client:
        try:
            mqtt_client.disconnect()
        except Exception:
            pass
        mqtt_client = None


def sleep_with_wdt(seconds):
    """Schläft `seconds` Sekunden und füttert dabei den WDT jede Sekunde.
    Sendet außerdem alle MQTT_KEEPALIVE Sekunden einen Ping."""
    global mqtt_client
    for i in range(seconds):
        utime.sleep(1)
        wdt.feed()
        # MQTT Keep-Alive Ping
        if mqtt_client and (i + 1) % MQTT_KEEPALIVE == 0:
            try:
                mqtt_client.ping()
            except Exception as e:
                print("MQTT-Ping fehlgeschlagen:", e)
                disconnect_mqtt()


# =============================================================================
# Einmalige Initialisierung
# =============================================================================

# Sensor beim Start initialisieren
if not init_sensor():
    print("WARNUNG: Sensor nicht verfügbar beim Start.")

# WLAN verbinden und OTA-Check beim ersten Boot
if do_connect():
    check_for_updates()


# =============================================================================
# Hauptschleife
# =============================================================================
print("Starte Hauptschleife...")

while True:
    wdt.feed()

    try:
        # --- 1. WLAN sicherstellen ---
        if not wlan.isconnected():
            disconnect_mqtt()
            if not do_connect():
                print("Kein WLAN – warte", ERROR_BACKOFF, "s")
                sleep_with_wdt(ERROR_BACKOFF)
                error_count += 1
                continue
            # Nach erneutem WLAN-Connect auf Updates prüfen
            check_for_updates()

        # --- 2. Sensor sicherstellen ---
        if sensor is None:
            if not init_sensor():
                print("Sensor nicht verfügbar – warte", ERROR_BACKOFF, "s")
                sleep_with_wdt(ERROR_BACKOFF)
                error_count += 1
                continue

        # --- 3. MQTT sicherstellen ---
        if mqtt_client is None:
            mqtt_client = connect_mqtt()
            if mqtt_client is None:
                print("MQTT nicht erreichbar – warte", ERROR_BACKOFF, "s")
                sleep_with_wdt(ERROR_BACKOFF)
                error_count += 1
                continue

        # --- 4. Messen ---
        temp, pres, hum = sensor.read_values()

        # --- 5. Senden ---
        mqtt_client.publish(TOPIC_TEMP, "{:.2f}".format(temp).encode())
        mqtt_client.publish(TOPIC_PRES, "{:.2f}".format(pres).encode())
        mqtt_client.publish(TOPIC_HUM,  "{:.2f}".format(hum).encode())

        print("Gesendet: {:.2f}°C  {:.2f} hPa  {:.2f}%".format(temp, pres, hum))

        # Fehler-Zähler zurücksetzen nach Erfolg
        error_count = 0

        # --- 6. Schlafen ---
        sleep_with_wdt(SLEEP_INTERVAL)

    except Exception as e:
        error_count += 1
        print("Fehler ({}/{}):".format(error_count, MAX_ERRORS), e)

        # MQTT als ungültig markieren – wird im nächsten Durchlauf neu aufgebaut
        disconnect_mqtt()

        if error_count >= MAX_ERRORS:
            print("Zu viele Fehler – starte neu...")
            utime.sleep(2)
            reset()

        sleep_with_wdt(ERROR_BACKOFF)
