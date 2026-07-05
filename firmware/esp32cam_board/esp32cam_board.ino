#include "esp_camera.h"
#include <WiFi.h>
#include <WiFiClientSecure.h>

// ─── BROWNOUT PREVENTION CONFIGURATION ──────────────────────
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// ─── LOCAL WIFI CONFIGURATION ────────────────────────────────
const char* ssid     = "YOUR FATHER SUB FOR ME? WEREY";
const char* password = "@Jerry123";

// ─── BACKEND TARGET CONFIGURATION ────────────────────────────
const char* server_host = "frsc-speedcar-detector.onrender.com";
const int   server_port = 443; 

// ─── INTER-BOARD HIGH-SPEED SERIAL INTERFACE ─────────────────
HardwareSerial DEVBoardSerial(1); // Maps onto secondary hardware register
#define CAM_TX_PIN 12 
#define CAM_RX_PIN 13

// ─── AI-THINKER ESP32-CAM LENS MATRIX INTERFACES ─────────────
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// Forward Declarations
bool initCameraHardware();
bool checkServerHealth();
void processTelemetryCapture(String commandLine);
String parseQueryKey(String data, String key);

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0); // Terminate loop fault brownout triggers
  
  Serial.begin(115200);      // Primary USB output for serial debugging
  DEVBoardSerial.begin(115200, SERIAL_8N1, CAM_RX_PIN, CAM_TX_PIN); // Controller link

  Serial.println("\n==============================================");
  Serial.println("  FRSC SPEED VIGIL - CAMERA UNIT INITIALIZING  ");
  Serial.println("==============================================");

  if (!initCameraHardware()) {
    Serial.println("[-] Lens initialization failure encountered.");
    while (true) { delay(1000); }
  }
  Serial.println("[+] Optical hardware arrays ready.");

  WiFi.begin(ssid, password);
  Serial.print("[*] Synchronizing network link layer");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n[+] Network infrastructure matched. Local Node: " + WiFi.localIP().toString());

  // Automated Render cloud environment initialization test execution
  Serial.println("[*] Querying remote Render cluster liveness status (/health)...");
  bool cloudActive = checkServerHealth();
  
  if (cloudActive) {
    Serial.println("[+] Cloud server confirmed ACTIVE. Issuing initialization completion signal.");
    DEVBoardSerial.println("CAM_READY"); // Tell main board to unlock screen interface
  } else {
    Serial.println("[-] Cloud infrastructure unreachable or sleeping. Notifying Main Controller.");
    DEVBoardSerial.println("PONG:0");
  }
}

void loop() {
  if (DEVBoardSerial.available()) {
    String command = DEVBoardSerial.readStringUntil('\n');
    command.trim();
    if (command.length() == 0) return;

    Serial.println("[UART IN] Received Command structure: " + command);

    if (command == "PING") {
      if (WiFi.status() == WL_CONNECTED) {
        DEVBoardSerial.println("PONG:1");
      } else {
        DEVBoardSerial.println("PONG:0");
      }
    } 
    else if (command.startsWith("CAPTURE:")) {
      processTelemetryCapture(command);
    }
  }
}

// ─── REMOTE INSTANCE HEALTH ANALYSIS CHECK ───────────────────
bool checkServerHealth() {
  WiFiClientSecure client;
  client.setInsecure(); // Drops strict root cert authority loops for dynamic cloud domains

  if (!client.connect(server_host, server_port)) {
    return false;
  }

  client.print("GET /health HTTP/1.1\r\n");
  client.print("Host: " + String(server_host) + "\r\n");
  client.print("Connection: close\r\n\r\n");

  unsigned long timeout = millis();
  bool derivedSuccess = false;
  
  while (client.connected() || client.available()) {
    if (millis() - timeout > 7000) break; // 7-Second load window limit for sleeping apps
    if (client.available()) {
      String line = client.readStringUntil('\n');
      if (line.indexOf("200 OK") != -1 || line.indexOf("status") != -1) {
        derivedSuccess = true;
      }
    }
  }
  client.stop();
  return derivedSuccess;
}

// ─── INTEGRATED METADATA CONVERSION AND MULTIPART POST ───────
void processTelemetryCapture(String commandLine) {
  // Isolate parameters from payload
  String subPayload = commandLine.substring(8);
  String speedVal  = parseQueryKey(subPayload, "speed");
  String locVal    = parseQueryKey(subPayload, "location");
  String timeVal   = parseQueryKey(subPayload, "travel_time");
  String frameVal  = parseQueryKey(subPayload, "frame_index");

  // Structural sanity check fallbacks
  if (speedVal == "")  speedVal = "0.0";
  if (locVal == "")    locVal   = "FUT_Minna_Field";
  if (timeVal == "")   timeVal  = "0.000";
  if (frameVal == "")  frameVal = "1";

  Serial.println("[+] Resolving capture event frames...");
  DEVBoardSerial.println("CAM_CAPTURING");

  camera_fb_t * fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[-] Lens configuration failed to yield buffer allocations.");
    DEVBoardSerial.println("RESP_ERROR");
    return;
  }

  Serial.println("[+] Initializing safe socket parameters...");
  DEVBoardSerial.println("CAM_UPLOADING");

  WiFiClientSecure client;
  client.setInsecure();

  if (!client.connect(server_host, server_port)) {
    Serial.println("[-] Pipeline socket drop detected.");
    DEVBoardSerial.println("RESP_ERROR");
    esp_camera_fb_return(fb);
    return;
  }

  String boundary = "----FRSCVigilProductionFormBoundary";
  
  // Format string components exactly matching Python script Flask multi-part variable parsing loops
  String p_loc    = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"location\"\r\n\r\n" + locVal + "\r\n";
  String p_speed  = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"speed\"\r\n\r\n" + speedVal + "\r\n";
  String p_time   = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"travel_time\"\r\n\r\n" + timeVal + "\r\n";
  String p_frame  = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"frame_index\"\r\n\r\n" + frameVal + "\r\n";
  
  String file_header = "--" + boundary + "\r\nContent-Disposition: form-data; name=\"imageFile\"; filename=\"capture.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n";
  String file_footer = "\r\n--" + boundary + "--\r\n";

  long total_len = p_loc.length() + p_speed.length() + p_time.length() + p_frame.length() + 
                   file_header.length() + fb->len + file_footer.length();

  Serial.println("[+] Injecting form structure over network socket...");
  client.print("POST /upload_and_infer HTTP/1.1\r\n");
  client.print("Host: " + String(server_host) + "\r\n");
  client.print("Content-Type: multipart/form-data; boundary=" + boundary + "\r\n");
  client.print("Content-Length: " + String(total_len) + "\r\n");
  client.print("Connection: close\r\n\r\n");

  client.print(p_loc);
  client.print(p_speed);
  client.print(p_time);
  client.print(p_frame);
  client.print(file_header);
  
  // High-performance direct block indexing copy loop (Safe from system memory leak bugs)
  uint8_t *fbBuf = fb->buf;
  size_t fbLen = fb->len;
  for (size_t n = 0; n < fbLen; n += 1024) {
    size_t remaining = fbLen - n;
    size_t chunkSize = remaining < 1024 ? remaining : 1024;
    client.write(fbBuf + n, chunkSize);
  }
  
  client.print(file_footer);
  esp_camera_fb_return(fb); // Instantly deallocate memory safely back to the camera driver pool

// ── Processing Backend JSON Output Response Payload ─────────
  Serial.println("[+] Stream absolute. Parsing pipeline validation response payload...");
  bool processedResult = false;
  bool isCar = false;

  unsigned long readTimeout = millis();
  while (client.connected() || client.available()) {
    if (millis() - readTimeout > 10000) break; // 10s evaluation timeout limit
    if (client.available()) {
      String line = client.readStringUntil('\n');
      line.trim();
      line.toLowerCase();
      
      // Highly robust substring checks (ignores variations in spaces, quotes, or colons)
      if (line.indexOf("car_detected") != -1) {
        processedResult = true;
        if (line.indexOf("true") != -1) {
          isCar = true;
          Serial.println("[AI RESULT] Match found: Car Detected!");
        } else {
          isCar = false;
          Serial.println("[AI RESULT] Match found: No Car Detected.");
        }
      }
    }
  }
  client.stop();

  if (processedResult) {
    if (isCar) {
      DEVBoardSerial.println("RESP_CAR_DETECTED");
    } else {
      DEVBoardSerial.println("RESP_NO_CAR");
    }
  } else {
    Serial.println("[-] Error: Failed to find valid tracking flags in response.");
    DEVBoardSerial.println("RESP_ERROR");
  }
}

// Helper query function parsing parameter sequences reliably without string replacement loops
String parseQueryKey(String data, String key) {
  int keyIndex = data.indexOf(key + "=");
  if (keyIndex == -1) return "";
  int valIndex = keyIndex + key.length() + 1;
  int endIndex = data.indexOf("&", valIndex);
  if (endIndex == -1) {
    return data.substring(valIndex);
  }
  return data.substring(valIndex, endIndex);
}

bool initCameraHardware() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 10000000; // Safeguard current drop constraints
  config.pixel_format = PIXFORMAT_JPEG;
  
  if(psramFound()){
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 12;
    config.fb_count = 2;
  } else {
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) return false;

  sensor_t * s = esp_camera_sensor_get();
  s->set_vflip(s, 1);
  s->set_hmirror(s, 1);
  return true;
}
