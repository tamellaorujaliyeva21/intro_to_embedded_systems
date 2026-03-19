#include <LiquidCrystal.h>
#include <Wire.h> 
#include <uRTCLib.h>

uRTCLib rtc(0x68);

const int rs = 12, en = 11, d4 = 5, d5 = 4, d6 = 3, d7 = 2;
LiquidCrystal lcd(rs, en, d4, d5, d6, d7);

//bool stopCount = false;
unsigned long seconds = 0;
unsigned long lastSecond = 0;
static bool buttonLastState = false;
int buttonPin = A0;

int greenLed = 9;
int redLed = 8;


bool buttonPressed(){
  static bool last = HIGH;
  static unsigned long tLastChange = 0;
  static bool armed = true;


  bool now = digitalRead(buttonPin);

  if (now != last) {
    tLastChange = millis();
    last = now;
  }

  if ((millis() - tLastChange) > 30) {   // debounce
    if (last == LOW && armed) {
      armed = false;
      return true;
    }
    if (last == HIGH) armed = true;
  }
  return false;
}


void setup() {

Serial.begin(9600);

lcd.begin(16, 2);
lcd.print("10 SECONDS GAME");

pinMode(greenLed, OUTPUT);
pinMode(redLed, OUTPUT);

pinMode(buttonPin, INPUT);
Wire.begin();
URTCLIB_WIRE.begin();

}

void loop() {
rtc.refresh();
bool pressed = buttonPressed();
seconds = rtc.second();

if (pressed) {
    buttonLastState = !buttonLastState;
  }

//Serial.println(buttonLastState);

  if (!buttonLastState){
  
    if (seconds > 10){
      rtc.set(0, 0, 0, 0, 0, 0, 26);
      seconds  = 0;
    }
      lastSecond = seconds;
  }



  if(buttonLastState){
        rtc.set(lastSecond,rtc.minute(), rtc.hour(),
            rtc.dayOfWeek(), rtc.day(),
            rtc.month(), rtc.year());
        seconds = lastSecond;
        if (seconds == 10) {
          Serial.println("Should be green");
          digitalWrite(greenLed, HIGH);
          digitalWrite(redLed, LOW);
        } else if (seconds != 10){
          Serial.println("Should be red");
          digitalWrite(redLed, HIGH);
          digitalWrite(greenLed, LOW);
        } else {
          Serial.println("nothing");
          digitalWrite(greenLed, LOW);
          digitalWrite(redLed, LOW);
        }


  }

  Serial.println(seconds);

  lcd.setCursor(0, 1);
  lcd.print("    ");   
  lcd.setCursor(0, 1);
  lcd.print(seconds);

  
}
