/*
 * ============================================================================
 * FRSC SPEED VIGIL  —  ESP32 DEV BOARD (Sensors + Upgraded TFT UI Layout)
 * Optimized for ST7735 128x160 Landscape Displays
 * ============================================================================
 */

#include <TFT_eSPI.h>

#define IR1 4
#define IR2 5
#define BUZZER 27

HardwareSerial CAMSerial(2);
TFT_eSPI tft = TFT_eSPI();

// ─── LOCAL DEPLOYMENT PARAMETERS ─────────────────────────────
const float DISTANCE_METERS = 0.3302; 
const float SPEED_LIMIT     = 2.0;    
const String SITE_LOCATION  = "FUT_Minna_GIDAN_Kwano"; 

enum SystemState {
  STATE_BOOT_WAIT_CAM,    
  STATE_MONITORING,
  STATE_IR1_DETECTED,
  STATE_SPEED_NORMAL,
  STATE_SPEED_OVERSPEED,
  STATE_CAM_PROCESSING,   
  STATE_RESULT_DISPLAY,   
  STATE_CLEANUP
};
SystemState currentState = STATE_BOOT_WAIT_CAM;

unsigned long stateStartTime = 0;
unsigned long ir1Time = 0;
unsigned long ir2Time = 0;
float lastSpeedKMH = 0.0;
bool lastIR1State = HIGH;
bool lastIR2State = HIGH;
bool globalCarDetected = false;

// ─── Camera Board Telemetry Handshakes ───────────────────────
bool camBoardSeen   = false;
bool camWifiOK      = false;
unsigned long lastPingSent  = 0;
unsigned long lastPongSeen  = 0;
uint32_t violationCount     = 0; 

const unsigned long PING_INTERVAL_MS   = 1000;
const unsigned long PONG_STALE_MS      = 5000;

// ─── Color Palette Palette Definitions ───────────────────────
#define COLOR_BG        0x0841  // Deep Midnight Navy Blue
#define COLOR_CARD      0x18E3  // Dark Charcoal/Grey Card Base
#define COLOR_ACCENT    0x0DFD  // bright Cyan
#define COLOR_TEXT_MUTED 0x94B2 // Slate Grey

// ════════════════════════════════════════════════════════════
//  UI DESIGN ELEMENTS & CANVAS DRAWING
// ════════════════════════════════════════════════════════════

void drawBaseLayout(const char* headerTitle, uint16_t headerBarColor, uint16_t headerTextColor) {
  tft.fillScreen(COLOR_BG);
  
  // Top Header Banner
  tft.fillRect(0, 0, 160, 24, headerBarColor);
  tft.setTextColor(headerTextColor, headerBarColor);
  tft.setTextSize(1);
  tft.setTextDatum(MC_DATUM);
  tft.drawString(headerTitle, 80, 12);
  tft.setTextDatum(TL_DATUM); // Reset to Top-Left standard
  
  // Bottom Console Separator
  tft.drawFastHLine(0, 95, 160, COLOR_ACCENT);
  tft.fillRect(0, 96, 160, 32, TFT_BLACK);
}

void updateConsoleFooter(String message, uint16_t color) {
  tft.fillRect(0, 96, 160, 32, TFT_BLACK);
  tft.drawFastHLine(0, 95, 160, COLOR_ACCENT);
  
  tft.setTextColor(COLOR_TEXT_MUTED, TFT_BLACK);
  tft.setTextSize(1);
  tft.drawString("SYSTEM LOG:", 6, 99);
  
  tft.setTextColor(color, TFT_BLACK);
  tft.drawString(message, 6, 114);
}

void showBootWaitCam() {
  drawBaseLayout("FRSC SPEED VIGIL v1.0", TFT_NAVY, TFT_WHITE);
  
  // Content Cards
  tft.fillRoundRect(8, 32, 144, 54, 4, COLOR_CARD);
  tft.setTextColor(TFT_WHITE, COLOR_CARD);
  tft.drawString("Core Engine:", 16, 40);
  tft.setTextColor(TFT_GREEN, COLOR_CARD);
  tft.drawString("ONLINE", 95, 40);
  
  tft.setTextColor(TFT_WHITE, COLOR_CARD);
  tft.drawString("Cam Link:", 16, 56);
  tft.setTextColor(TFT_ORANGE, COLOR_CARD);
  tft.drawString("SEARCHING...", 95, 56);
  
  updateConsoleFooter("Awaiting UART Sync Frame...", COLOR_ACCENT);
}

void updateBootCamStatus(const char* statusWord, uint16_t color) {
  tft.fillRect(95, 56, 54, 12, COLOR_CARD);
  tft.setTextColor(color, COLOR_CARD);
  tft.drawString(statusWord, 95, 56);
}

void showMonitoring() {
  drawBaseLayout("RADAR ACTIVE", TFT_DARKGREEN, TFT_WHITE);
  
  // Dashboard Metrics Grid
  tft.fillRoundRect(6, 30, 71, 60, 4, COLOR_CARD);
  tft.fillRoundRect(83, 30, 71, 60, 4, COLOR_CARD);
  
  // Left Column Card: Network Telemetry
  tft.setTextColor(COLOR_TEXT_MUTED, COLOR_CARD);
  tft.drawString("NET STATUS", 12, 36);
  tft.setTextColor(camWifiOK ? TFT_GREEN : TFT_RED, COLOR_CARD);
  tft.setTextSize(1);
  tft.drawString(camWifiOK ? "RENDER OK" : "NO CLOUD", 12, 52);
  tft.setTextColor(COLOR_TEXT_MUTED, COLOR_CARD);
  tft.drawString("WiFi AP: Link", 12, 72);
  
  // Right Column Card: Speed Parameter
  tft.setTextColor(COLOR_TEXT_MUTED, COLOR_CARD);
  tft.drawString("LIMIT VAL", 89, 36);
  tft.setTextColor(COLOR_ACCENT, COLOR_CARD);
  tft.setTextSize(2);
  tft.drawString(String(SPEED_LIMIT, 1), 89, 50);
  tft.setTextSize(1);
  tft.setTextColor(COLOR_TEXT_MUTED, COLOR_CARD);
  tft.drawString("km/h", 128, 58);

  updateConsoleFooter("Scanning IR Gates...", TFT_GREEN);
}

void refreshMonitoringFooter() {
  // Update Network Matrix locally without wiping dashboard cards
  tft.fillRect(12, 52, 60, 12, COLOR_CARD);
  tft.setTextColor(camWifiOK ? TFT_GREEN : TFT_RED, COLOR_CARD);
  tft.drawString(camWifiOK ? "RENDER OK" : "NO CLOUD", 12, 52);
  
  if (camWifiOK) {
    updateConsoleFooter("Keepalive resolved. Cloud online.", TFT_GREEN);
  } else {
    updateConsoleFooter("WARNING: Cloud node disconnected.", TFT_RED);
  }
}

void showIR1Detected(int countdown) {
  drawBaseLayout("GATE ENTRY DETECTED", TFT_MAROON, TFT_WHITE);
  
  tft.fillRoundRect(6, 30, 148, 60, 4, COLOR_CARD);
  tft.setTextColor(TFT_YELLOW, COLOR_CARD);
  tft.setTextSize(3);
  tft.drawString(String(countdown), 20, 44);
  
  tft.setTextSize(1);
  tft.setTextColor(TFT_WHITE, COLOR_CARD);
  tft.drawString("Locked Entry Window", 60, 42);
  tft.setTextColor(COLOR_TEXT_MUTED, COLOR_CARD);
  tft.drawString("Awaiting Gate B exit...", 60, 60);

  updateConsoleFooter("Timing velocity curve...", TFT_YELLOW);
}

void showSpeedNormal(int countdown) {
  drawBaseLayout("SAFE VELOCITY PROFILE", TFT_GREEN, TFT_BLACK);
  
  tft.fillRoundRect(6, 30, 148, 60, 4, COLOR_CARD);
  tft.setTextColor(TFT_GREEN, COLOR_CARD);
  tft.setTextSize(3);
  tft.drawString(String(lastSpeedKMH, 1), 16, 44);
  
  tft.setTextSize(1);
  tft.setTextColor(TFT_WHITE, COLOR_CARD);
  tft.drawString("km/h", 108, 44);
  tft.setTextColor(COLOR_TEXT_MUTED, COLOR_CARD);
  tft.drawString("Clearance OK", 108, 62);

  updateConsoleFooter("Hold frame reset counter: " + String(countdown) + "s", TFT_WHITE);
}

void showSpeedOverspeed() {
  drawBaseLayout("ALARM: CRITICAL BREACH", TFT_RED, TFT_WHITE);
  
  tft.fillRoundRect(6, 30, 148, 60, 4, COLOR_CARD);
  tft.setTextColor(TFT_RED, COLOR_CARD);
  tft.setTextSize(3);
  tft.drawString(String(lastSpeedKMH, 1), 16, 44);
  
  tft.setTextSize(1);
  tft.setTextColor(TFT_WHITE, COLOR_CARD);
  tft.drawString("km/h", 108, 44);
  tft.setTextColor(TFT_YELLOW, COLOR_CARD);
  tft.drawString("OVER LIMIT!", 108, 62);

  updateConsoleFooter("Sending trigger payload packet...", TFT_RED);
}

void showResetMessage() {
  drawBaseLayout("SYSTEM AUTO-RECOVERY", TFT_BLUE, TFT_WHITE);
  
  tft.fillRoundRect(6, 30, 148, 60, 4, COLOR_CARD);
  tft.setTextColor(TFT_WHITE, COLOR_CARD);
  tft.drawString("Flushing localized variables...", 14, 44);
  tft.setTextColor(COLOR_TEXT_MUTED, COLOR_CARD);
  tft.drawString("Arming infrared arrays", 14, 60);

  updateConsoleFooter("Readying monitoring profiles...", COLOR_ACCENT);
}

void beep(int count) {
  for (int i = 0; i < count; i++) {
    digitalWrite(BUZZER, HIGH);
    delay(100);
    digitalWrite(BUZZER, LOW);
    delay(100);
  }
}

void sendPing() {
  CAMSerial.println("PING");
  lastPingSent = millis();
}

bool processCamLine(const String& line) {
  if (line == "CAM_READY") {
    camBoardSeen = true;
    camWifiOK    = true;
    lastPongSeen = millis();
    Serial.println("[CAM] Reported READY (Camera + Render Server Online)");
    return true;
  }
  if (line.startsWith("PONG:")) {
    camBoardSeen = true;
    camWifiOK    = (line.charAt(5) == '1');
    lastPongSeen = millis();
    Serial.print("[CAM] Status Ping received — network=");
    Serial.println(camWifiOK ? "OK" : "DOWN");
    return true;
  }
  return false;
}

void setup() {
  Serial.begin(115200);
  CAMSerial.begin(115200, SERIAL_8N1, 16, 17);

  pinMode(IR1, INPUT_PULLUP);
  pinMode(IR2, INPUT_PULLUP);
  pinMode(BUZZER, OUTPUT);
  digitalWrite(BUZZER, LOW);

  tft.init();
  tft.setRotation(1); // Standard 160x128 Landscape deployment

  Serial.println("\n═══════════════════════════════════");
  Serial.println("SPEED-VIGIL-001 :: Main Controller  ");
  Serial.println("═══════════════════════════════════\n");
  
  currentState = STATE_BOOT_WAIT_CAM;
  stateStartTime = millis();
  showBootWaitCam();
}

void loop() {
  bool curIR1 = digitalRead(IR1);
  bool curIR2 = digitalRead(IR2);
  unsigned long elapsedMS = millis() - stateStartTime;

  // ── Unified Asynchronous UART Listener Block ─────────────────
  if (CAMSerial.available()) {
    String msg = CAMSerial.readStringUntil('\n');
    msg.trim();
    if (msg.length() > 0) {
      bool handled = processCamLine(msg);
      
      if (handled && currentState == STATE_MONITORING) {
        refreshMonitoringFooter();
      }
      if (handled && currentState == STATE_BOOT_WAIT_CAM) {
        updateBootCamStatus(camWifiOK ? "ONLINE" : "NO WIFI", camWifiOK ? TFT_GREEN : TFT_ORANGE);
      }

      if (!handled && currentState == STATE_CAM_PROCESSING) {
          if (msg == "CAM_CAPTURING") {
            Serial.println("[CAM STATUS] Processing mechanical lens shutter...");
            updateConsoleFooter("Camera Lens Shutter Fired", TFT_YELLOW);
          }
          else if (msg == "CAM_UPLOADING") {
            Serial.println("[CAM STATUS] Streaming multi-part form package...");
            updateConsoleFooter("Cloud Processing (POST Request)", COLOR_ACCENT);
          }
          else if (msg == "RESP_CAR_DETECTED") {
            Serial.println("[AI VERDICT] Target Confirmed. Logging Violation Entry.");
            globalCarDetected = true;
            currentState = STATE_RESULT_DISPLAY;
            stateStartTime = millis();
            
            // Draw result context UI immediately
            drawBaseLayout("VIOLATION LOGGED", TFT_RED, TFT_WHITE);
            tft.fillRoundRect(6, 30, 148, 60, 4, COLOR_CARD);
            tft.setTextColor(TFT_RED, COLOR_CARD); tft.setTextSize(2);
            tft.drawString("TARGET FILED", 12, 38);
            tft.setTextColor(TFT_WHITE, COLOR_CARD); tft.setTextSize(1);
            tft.drawString("AI Inference: Vehicle Found", 12, 64);
            
            updateConsoleFooter("Render API code 200: Email Out", TFT_RED);
            beep(3);
          }
          else if (msg == "RESP_NO_CAR") {
            Serial.println("[AI VERDICT] Target Cleared. Anomalous speed signature.");
            globalCarDetected = false;
            currentState = STATE_RESULT_DISPLAY;
            stateStartTime = millis();
            
            drawBaseLayout("VIOLATION REJECTED", TFT_DARKGREEN, TFT_WHITE);
            tft.fillRoundRect(6, 30, 148, 60, 4, COLOR_CARD);
            tft.setTextColor(TFT_GREEN, COLOR_CARD); tft.setTextSize(2);
            tft.drawString("GHOST ALARM", 12, 38);
            tft.setTextColor(TFT_WHITE, COLOR_CARD); tft.setTextSize(1);
            tft.drawString("Roboflow: No Object Detected", 12, 64);
            
            updateConsoleFooter("Aborted log entry pipeline.", TFT_GREEN);
          }
          else if (msg == "RESP_ERROR") {
            Serial.println("[PIPELINE ERROR] Cloud Transaction Fault.");
            currentState = STATE_RESULT_DISPLAY;
            stateStartTime = millis();
            
            drawBaseLayout("PIPELINE ERROR", TFT_MAGENTA, TFT_WHITE);
            tft.fillRoundRect(6, 30, 148, 60, 4, COLOR_CARD);
            tft.setTextColor(TFT_MAGENTA, COLOR_CARD); tft.setTextSize(2);
            tft.drawString("SERVER FAULT", 12, 38);
            tft.setTextColor(TFT_WHITE, COLOR_CARD); tft.setTextSize(1);
            tft.drawString("JSON Check Fail / HTTP 500", 12, 64);
            
            updateConsoleFooter("Render runtime error caught.", TFT_MAGENTA);
          }
      }
    }
  }

  // ── System Logic State Machine ────────────────────────────────
  switch (currentState) {
    case STATE_BOOT_WAIT_CAM:
      if (millis() - lastPingSent >= PING_INTERVAL_MS) {
        sendPing();
      }

      if (camBoardSeen) {
        Serial.println("[BOOT] Active verification link resolved.");
        currentState = STATE_MONITORING;
        showMonitoring();
      }

      if (elapsedMS > 20000) { 
        Serial.println("[WARN] Handshake timed out. Proceeding blind...");
        camBoardSeen = false;
        camWifiOK    = false;
        currentState = STATE_MONITORING;
        showMonitoring();
      }
      break;

    case STATE_MONITORING:
      if (millis() - lastPingSent >= PING_INTERVAL_MS * 3) {
        sendPing();
      }
      if (camBoardSeen && (millis() - lastPongSeen > PONG_STALE_MS)) {
        if (camWifiOK) {           
          camWifiOK = false;
          refreshMonitoringFooter();
        }
      }

      if (curIR1 == LOW && lastIR1State == HIGH) {
        Serial.println("\n[IR-1] Gate A entered.");
        beep(1);
        ir1Time = millis();
        stateStartTime = millis();
        currentState = STATE_IR1_DETECTED;
        showIR1Detected(2);
      }
      break;

    case STATE_IR1_DETECTED:
      {
        int countdownIR1 = 2 - (elapsedMS / 1000);
        if (countdownIR1 < 0) countdownIR1 = 0;
        
        // Non-flickering inline loop countdown update
        tft.setTextColor(TFT_YELLOW, COLOR_CARD);
        tft.setTextSize(3);
        tft.drawString(String(countdownIR1), 20, 44);

        if (curIR2 == LOW && lastIR2State == HIGH) {
          ir2Time = millis();
          float elapsedSeconds = (ir2Time - ir1Time) / 1000.0;
          lastSpeedKMH = (DISTANCE_METERS / elapsedSeconds) * 3.6;

          Serial.printf("[MATH] Calculated Speed: %.2f km/h\n", lastSpeedKMH);

          if (lastSpeedKMH > SPEED_LIMIT) {
            Serial.println("[ALARM] Speed breach caught!");
            currentState = STATE_SPEED_OVERSPEED;
            stateStartTime = millis();
            showSpeedOverspeed();

            violationCount++;
            
            String payload = "CAPTURE:speed=" + String(lastSpeedKMH, 2) +
                             "&location=" + SITE_LOCATION +
                             "&travel_time=" + String(elapsedSeconds, 3) +
                             "&frame_index=" + String(violationCount);
                                             
            CAMSerial.println(payload);
            Serial.println("[UART] Dispatched Payload Struct -> " + payload);
          } else {
            Serial.println("[OK] Safe velocity profile verified.");
            beep(1);
            currentState = STATE_SPEED_NORMAL;
            stateStartTime = millis();
            showSpeedNormal(2);
          }
        }
        else if (countdownIR1 == 0 && elapsedMS >= 2000) {
          Serial.println("[TIMEOUT] Gate B clearance window expired. Clearing frame.");
          beep(2);
          currentState = STATE_MONITORING;
          showMonitoring();
        }
      }
      break;

    case STATE_SPEED_NORMAL:
      {
        int countdownNormal = 2 - (elapsedMS / 1000);
        if (countdownNormal < 0) countdownNormal = 0;
        
        // Direct print layout protection
        tft.setTextColor(COLOR_TEXT_MUTED, COLOR_CARD); tft.setTextSize(1);
        tft.drawString("Hold reset: " + String(countdownNormal) + "s ", 108, 62);
        updateConsoleFooter("Hold frame reset counter: " + String(countdownNormal) + "s", TFT_WHITE);

        if (countdownNormal == 0 && elapsedMS >= 2000) {
          currentState = STATE_MONITORING;
          showMonitoring();
        }
      }
      break;

    case STATE_SPEED_OVERSPEED:
      currentState = STATE_CAM_PROCESSING;
      stateStartTime = millis();
      break;

    case STATE_CAM_PROCESSING:
      if (millis() - stateStartTime > 15000) { 
        Serial.println("[TIMEOUT] Camera transaction window lost.");
        currentState = STATE_CLEANUP;
        stateStartTime = millis();
        showResetMessage();
      }
      break;

    case STATE_RESULT_DISPLAY:
      if (elapsedMS >= 5000) {
        currentState = STATE_CLEANUP;
        stateStartTime = millis();
        showResetMessage();
      }
      break;

    case STATE_CLEANUP:
      if (elapsedMS > 1500) {
        globalCarDetected = false;
        currentState = STATE_MONITORING;
        showMonitoring();
        Serial.println("[READY] System idle. Gate active.\n");
      }
      break;
  }

  lastIR1State = curIR1;
  lastIR2State = curIR2;
  delay(10);
}
