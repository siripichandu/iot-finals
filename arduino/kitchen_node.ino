#include "WiFi.h"
#include "WiFiMulti.h"
#include "PubSubClient.h"
#include "DHT.h"

// ── Pin definitions ───────────────────────────────────
#define DHTPIN    5       // DHT22 data pin
#define DHTTYPE   DHT22
#define MQ135PIN  35      // MQ-135 analog pin (use GPIO35, not GPIO34)
#define PIRPIN    13      // PIR motion sensor

// ── Objects ───────────────────────────────────────────
DHT dht(DHTPIN, DHTTYPE);
WiFiMulti wifiMulti;
WiFiClient espClient;
PubSubClient client(espClient);

// ── Configuration — update these before flashing ──────
const char* mqtt_server = "YOUR_LAPTOP_IP";   // run: ipconfig getifaddr en0
const char* room        = "kitchen";

// ── MQTT reconnect ────────────────────────────────────
void connectMQTT() {
  while (!client.connected()) {
    Serial.print("Connecting to MQTT...");
    // NOTE: client ID must be different from bedroom node
    if (client.connect("ESP32Client_Kitchen")) {
      Serial.println("connected!");
    } else {
      Serial.print("failed rc=");
      Serial.print(client.state());
      Serial.println(" retrying in 5s");
      delay(5000);
    }
  }
}

// ── Setup ─────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  dht.begin();
  pinMode(PIRPIN, INPUT);

  // ── Add your WiFi networks here ───────────────────
  wifiMulti.addAP("YOUR_WIFI_NAME_1", "YOUR_PASSWORD_1");
  wifiMulti.addAP("YOUR_WIFI_NAME_2", "YOUR_PASSWORD_2");
  // add more networks if needed:
  // wifiMulti.addAP("YOUR_WIFI_NAME_3", "YOUR_PASSWORD_3");

  Serial.print("Connecting to WiFi...");
  while (wifiMulti.run() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.println("WiFi connected!");
  Serial.print("IP address: ");
  Serial.println(WiFi.localIP());

  client.setServer(mqtt_server, 1883);
  connectMQTT();
}

// ── Loop ──────────────────────────────────────────────
void loop() {
  if (!client.connected()) connectMQTT();
  client.loop();

  delay(10000);  // publish every 10 seconds

  float humidity    = dht.readHumidity();
  float temperature = dht.readTemperature();
  int   airquality  = analogRead(MQ135PIN);
  int   motion      = digitalRead(PIRPIN);

  if (isnan(humidity) || isnan(temperature)) {
    Serial.println("Failed to read DHT22 — retrying next cycle");
    return;
  }

  String payload = "{\"room\":\""       + String(room)        + "\""
                 + ",\"temperature\":"  + String(temperature)
                 + ",\"humidity\":"     + String(humidity)
                 + ",\"airquality\":"   + String(airquality)
                 + ",\"motion\":"       + String(motion)
                 + "}";

  client.publish("home/airquality", payload.c_str());
  Serial.print("Published: ");
  Serial.println(payload);
}
