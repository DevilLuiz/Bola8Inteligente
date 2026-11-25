#line 1 "/mnt/hd/Projetos/BolaMagica/projetoBola/firmware/bola/main.cpp"
// Bola 8 Mágica — firmware integrado (ESP32-S3)
//
// Fluxo:
//   1. MPU6050 detecta a chacoalhada
//   2. ESP chama GET /perguntar no notebook (a conexão fica aberta enquanto
//      o notebook escuta a pergunta, transcreve, gera a resposta e sintetiza)
//   3. O WAV chega inteiro na PSRAM e só então toca no MAX98357A
//
// Ligações:
//   MAX98357A DIN -> GPIO4 | BCLK -> GPIO5 | LRC -> GPIO6
//   MPU6050 SDA/SCL -> pinos I2C padrão do Wire (os mesmos do teste anterior)

#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <driver/i2s.h> // core 2.x (driver legado)

// ---------------------------------------------------------------- config ---
#define I2S_DOUT 4
#define I2S_BCLK 5
#define I2S_LRC 6

const char *WIFI_SSID = "LuizG";
const char *WIFI_PASS = "12345678";

// IP do notebook (mude aqui se a rede trocar o IP)
const char *URL_PERGUNTAR = "http://10.158.134.84:8000/perguntar";

// Quanto a ESP espera o notebook terminar o pipeline inteiro
// (escutar + Whisper + resposta + Piper).
constexpr uint32_t TIMEOUT_PIPELINE_MS = 60000;

constexpr size_t MAX_WAV_BYTES = 4 * 1024 * 1024;
constexpr int VOLUME_PCT = 40;

// Detecção de chacoalhada (mesmos valores do teste)
const float SHAKE_THRESHOLD = 15.0;        // m/s^2 de variação entre leituras
const unsigned long SHAKE_COOLDOWN = 1000; // ms entre detecções

// ------------------------------------------------------------------ MPU ---
Adafruit_MPU6050 mpu;
float magAnterior = 0.0;
bool primeiraLeitura = true;
unsigned long ultimoShake = 0;

bool mpuIniciar() {
  if (!mpu.begin())
    return false;
  mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
  return true;
}

bool detectouShake() {
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  float mag = sqrt(a.acceleration.x * a.acceleration.x +
                   a.acceleration.y * a.acceleration.y +
                   a.acceleration.z * a.acceleration.z);

  bool shake = false;
  if (!primeiraLeitura) {
    float delta = fabs(mag - magAnterior);
    unsigned long agora = millis();
    if (delta > SHAKE_THRESHOLD && (agora - ultimoShake) > SHAKE_COOLDOWN) {
      ultimoShake = agora;
      shake = true;
    }
  }
  magAnterior = mag;
  primeiraLeitura = false;
  return shake;
}

// ------------------------------------------------------------------ I2S ---
bool i2sIniciar(uint32_t taxa, uint16_t canais) {
  i2s_config_t cfg = {};
  cfg.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX);
  cfg.sample_rate = taxa;
  cfg.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  cfg.channel_format =
      (canais == 1) ? I2S_CHANNEL_FMT_ONLY_LEFT : I2S_CHANNEL_FMT_RIGHT_LEFT;
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags = 0;
  cfg.dma_buf_count = 8;
  cfg.dma_buf_len = 256;
  cfg.use_apll = false;
  cfg.tx_desc_auto_clear = true;
  if (i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL) != ESP_OK)
    return false;

  i2s_pin_config_t pinos = {};
  pinos.mck_io_num = I2S_PIN_NO_CHANGE;
  pinos.bck_io_num = I2S_BCLK;
  pinos.ws_io_num = I2S_LRC;
  pinos.data_out_num = I2S_DOUT;
  pinos.data_in_num = I2S_PIN_NO_CHANGE;
  return i2s_set_pin(I2S_NUM_0, &pinos) == ESP_OK;
}
void i2sEscrever(const uint8_t *p, size_t n) {
  size_t escrito = 0;
  i2s_write(I2S_NUM_0, p, n, &escrito, portMAX_DELAY);
}
void i2sParar() { i2s_driver_uninstall(I2S_NUM_0); }

// ------------------------------------------------------------------ WAV ---
struct WavInfo {
  uint32_t sampleRate = 0;
  uint16_t channels = 0;
  uint16_t bits = 0;
  uint8_t *data = nullptr;
  size_t dataLen = 0;
};

static uint16_t rd16(const uint8_t *p) { return p[0] | (p[1] << 8); }
static uint32_t rd32(const uint8_t *p) {
  return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24);
}

bool parseWav(uint8_t *buf, size_t len, WavInfo &w) {
  if (len < 12 || memcmp(buf, "RIFF", 4) || memcmp(buf + 8, "WAVE", 4))
    return false;

  size_t pos = 12;
  bool temFmt = false;
  uint16_t formato = 0;

  while (pos + 8 <= len) {
    uint32_t sz = rd32(buf + pos + 4);
    uint8_t *corpo = buf + pos + 8;

    if (!memcmp(buf + pos, "fmt ", 4) && pos + 8 + 16 <= len) {
      formato = rd16(corpo);
      w.channels = rd16(corpo + 2);
      w.sampleRate = rd32(corpo + 4);
      w.bits = rd16(corpo + 14);
      temFmt = true;
    } else if (!memcmp(buf + pos, "data", 4)) {
      if (!temFmt)
        return false;
      size_t restante = len - (pos + 8);
      w.data = corpo;
      w.dataLen = sz < restante ? sz : restante;
      w.dataLen &= ~(size_t)1;
      return formato == 1 && w.bits == 16 &&
             (w.channels == 1 || w.channels == 2);
    }
    pos += 8 + sz + (sz & 1);
  }
  return false;
}

// ------------------------------------------------------------- download ---
uint8_t *baixar(const char *url, size_t &outLen) {
  HTTPClient http;
  http.setConnectTimeout(5000);
  http.setTimeout(TIMEOUT_PIPELINE_MS); // espera o notebook processar
  if (!http.begin(url)) {
    Serial.println("HTTP: begin falhou");
    return nullptr;
  }

  uint32_t t0 = millis();
  int code = http.GET();
  if (code != HTTP_CODE_OK) {
    Serial.printf("HTTP: codigo %d\n", code);
    http.end();
    return nullptr;
  }
  Serial.printf("Notebook respondeu em %lu ms\n",
                (unsigned long)(millis() - t0));

  int total = http.getSize();
  if (total <= 44 || (size_t)total > MAX_WAV_BYTES) {
    Serial.printf("HTTP: tamanho invalido (%d)\n", total);
    http.end();
    return nullptr;
  }

  uint8_t *buf = (uint8_t *)ps_malloc(total);
  if (!buf) {
    Serial.println("PSRAM: sem memoria");
    http.end();
    return nullptr;
  }

  WiFiClient *stream = http.getStreamPtr();
  size_t got = 0;
  uint32_t ultimo = millis();

  while (got < (size_t)total && (http.connected() || stream->available())) {
    size_t disp = stream->available();
    if (disp) {
      size_t n = min(disp, (size_t)total - got);
      got += stream->readBytes(buf + got, n);
      ultimo = millis();
    } else {
      if (millis() - ultimo > 5000)
        break;
      delay(1);
    }
  }
  http.end();

  Serial.printf("Baixado %u/%d bytes\n", (unsigned)got, total);

  if (got != (size_t)total) {
    free(buf);
    return nullptr;
  }
  outLen = got;
  return buf;
}

// ---------------------------------------------------------------- tocar ---
void tocar(WavInfo &w) {
  int16_t *s = (int16_t *)w.data;
  size_t n = w.dataLen / 2;
  for (size_t i = 0; i < n; i++)
    s[i] = (int32_t)s[i] * VOLUME_PCT / 100;

  if (!i2sIniciar(w.sampleRate, w.channels)) {
    Serial.println("I2S: iniciar falhou");
    i2sParar();
    return;
  }

  Serial.printf("Tocando: %lu Hz, %u canal(is), %u bytes\n",
                (unsigned long)w.sampleRate, w.channels, (unsigned)w.dataLen);

  const size_t BLOCO = 2048;
  for (size_t pos = 0; pos < w.dataLen; pos += BLOCO) {
    size_t q = min(BLOCO, w.dataLen - pos);
    i2sEscrever(w.data + pos, q);
  }

  uint8_t zeros[2048] = {0};
  for (int i = 0; i < 4; i++)
    i2sEscrever(zeros, sizeof(zeros));

  i2sParar();
}

// Pede ao notebook para escutar/responder e toca o resultado.
void perguntarETocar() {
  size_t len = 0;
  uint8_t *buf = baixar(URL_PERGUNTAR, len);
  if (!buf)
    return;

  WavInfo w;
  if (parseWav(buf, len, w)) {
    tocar(w);
  } else {
    Serial.println("WAV invalido (precisa ser PCM 16 bits, mono ou estereo)");
  }
  free(buf);
}

// ---------------------------------------------------------------- setup ---
void setup() {
  Serial.begin(115200);
  delay(500); // sem while(!Serial): precisa funcionar sem o PC conectado

  Serial.printf("\nPSRAM: %s (%u bytes)\n", psramFound() ? "sim" : "nao",
                (unsigned)ESP.getPsramSize());

  if (!mpuIniciar()) {
    Serial.println("Falha ao encontrar o MPU6050");
    while (true)
      delay(1000);
  }
  Serial.println("MPU6050 ok");

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED)
    delay(500);
  Serial.printf("Wi-Fi ok. IP %s, RSSI %d dBm\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());

  Serial.println("Chacoalhe a bola (ou envie 'p' pelo monitor serial).");
}

// ----------------------------------------------------------------- loop ---
void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi caiu, reconectando...");
    WiFi.reconnect();
    delay(2000);
    return;
  }

  bool pedir = detectouShake();
  if (pedir)
    Serial.println("SHAKE DETECTADO!");

  if (Serial.available() && Serial.read() == 'p')
    pedir = true;

  if (pedir) {
    perguntarETocar();
    // O som e a chacoalhada bagunçam o acelerômetro: recomeça limpo.
    primeiraLeitura = true;
    ultimoShake = millis();
    Serial.println("Pronta para a proxima pergunta.");
  }

  delay(50);
}
