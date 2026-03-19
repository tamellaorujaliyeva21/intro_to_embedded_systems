int white = 9;
int red = 11;
int blue = 6;
int green = 10;
int xPin = A0;
int yPin = A1;


int centerMax = 530;
int centerMin = 490;


void setup() {
  
   Serial.begin(9600);
   pinMode(xPin, INPUT);
   pinMode(yPin, INPUT);
   
}

void loop() {
  
  int xVal = analogRead(xPin);
  int yVal = analogRead(yPin);
  
//  Serial.print(xVal);
//  Serial.print("|");
//  Serial.println(yVal);
  
  if ((xVal < centerMin) && (centerMin < yVal && yVal < centerMax)){
    Serial.println("LEFT");
    digitalWrite(green, HIGH);
    digitalWrite(red, LOW);
    digitalWrite(blue, LOW);
    digitalWrite(white, LOW);
    }
    
  else if ((xVal > centerMax) && (centerMin < yVal && yVal < centerMax)){
    Serial.println("RIGHT");
    digitalWrite(green, LOW);
    digitalWrite(red, LOW);
    digitalWrite(blue, HIGH);
    digitalWrite(white, LOW);
    }
    
  else if ((yVal < centerMin)&& (centerMin < xVal && xVal < centerMax)){
    Serial.println("UP");
    digitalWrite(green, LOW);
    digitalWrite(red, LOW);
    digitalWrite(blue, LOW);
    digitalWrite(white, HIGH);
    }
    
  else if ((yVal > centerMax)&& (centerMin < xVal && xVal < centerMax) ){
    Serial.println("DOWN");
    digitalWrite(green, LOW);
    digitalWrite(red, HIGH);
    digitalWrite(blue, LOW);
    digitalWrite(white, LOW);
    }
    
  else if ((yVal > centerMin && yVal < centerMax)&&(xVal > centerMin && xVal < centerMax)){
    Serial.println("CENTER");
    digitalWrite(green, LOW);
    digitalWrite(red, LOW);
    digitalWrite(blue, LOW);
    digitalWrite(white, LOW);
    }
  else{
    Serial.println("CORNER");
  }
}
