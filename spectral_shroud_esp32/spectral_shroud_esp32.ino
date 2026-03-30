#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <HTTPClient.h>

// ─── CONFIG ───────────────────────────────────────────────────────────────────
const char* SSID     = "moreflops-5G";
const char* PASSWORD = "d33pW1PHY##!!25";

// Optional: set a static IP so Spectral Shroud always knows where to find this node.
// If you prefer DHCP, comment out the three lines below and the WiFi.config() call.
IPAddress LOCAL_IP(192, 168, 1, 200);
IPAddress GATEWAY(192, 168, 1, 1);
IPAddress SUBNET(255, 255, 255, 0);

const int LED_PIN      = 2;    // Onboard LED on most ESP32 devkits (active HIGH)
const int JAM_DURATION = 10;   // seconds — must match Spectral Shroud sleep value
const int TAMPER_PIN = 0;;    // BOOT button (active LOW, has internal pull-up)
// ─────────────────────────────────────────────────────────────────────────────

AsyncWebServer server(80);

// Tracks whether a timed sequence is already running so we don't double-trigger.
volatile bool sequenceActive = false;

void ledOn()  { digitalWrite(LED_PIN, HIGH); }
void ledOff() { digitalWrite(LED_PIN, LOW);  }

// Runs the JAM_DURATION countdown in a FreeRTOS task so the HTTP response
// returns immediately and the web server stays responsive.
void jamTask(void* param) {
  ledOn();
  vTaskDelay(pdMS_TO_TICKS(JAM_DURATION * 1000));
  ledOff();
  sequenceActive = false;
  vTaskDelete(NULL);
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  ledOff();
  pinMode(BOOT_PIN, INPUT_PULLUP);

  // Static IP (comment out if using DHCP)
  WiFi.config(LOCAL_IP, GATEWAY, SUBNET);

  WiFi.begin(SSID, PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Connected. IP: ");
  Serial.println(WiFi.localIP());

  // ── Routes ─────────────────────────────────────────────────────────────────

  // GET /led/on  — turn LED on immediately (manual override / test)
  server.on("/led/on", HTTP_GET, [](AsyncWebServerRequest* req) {
    ledOn();
    req->send(200, "text/plain", "LED ON");
    Serial.println("[CMD] LED ON");
  });

  // GET /led/off — turn LED off immediately (manual override / test)
  server.on("/led/off", HTTP_GET, [](AsyncWebServerRequest* req) {
    ledOff();
    sequenceActive = false;
    req->send(200, "text/plain", "LED OFF");
    Serial.println("[CMD] LED OFF");
  });

  // GET /jam — starts timed sequence: LED on for JAM_DURATION seconds, then off.
  // This is the primary endpoint Spectral Shroud should call.
  server.on("/jam", HTTP_GET, [](AsyncWebServerRequest* req) {
    if (sequenceActive) {
      req->send(200, "text/plain", "ALREADY_ACTIVE");
      return;
    }
    sequenceActive = true;
    xTaskCreate(jamTask, "jamTask", 2048, NULL, 1, NULL);
    req->send(200, "text/plain", "JAM_STARTED");
    Serial.println("[CMD] JAM sequence started");
  });

  // GET /status — health check, returns JSON with current state and uptime
  server.on("/status", HTTP_GET, [](AsyncWebServerRequest* req) {
    String state = sequenceActive ? "JAMMING" : "IDLE";
    String json  = "{\"state\":\"" + state + "\","
                   "\"ip\":\"" + WiFi.localIP().toString() + "\","
                   "\"uptime_ms\":" + String(millis()) + "}";
    req->send(200, "application/json", json);
  });

  server.begin();
  Serial.println("HTTP server started. Endpoints: /jam  /led/on  /led/off  /status");
}

void loop() {
  if (digitalRead(BOOT_PIN) == LOW) {
    delay(50);  // debounce
    if (digitalRead(BOOT_PIN) == LOW) {
      ledOn();

      if (WiFi.status() == WL_CONNECTED) {
        HTTPClient http;
        http.begin("http://192.168.1.10:5000/motion");
        http.addHeader("Content-Type", "application/json");
        http.POST("{\"node_id\":\"NODE-01\"}");
        http.end();
      }

      Serial.println("[CMD] KINETIC triggered");
      delay(1000);  // cooldown — prevents double-firing on a single press
    }
  }
}
