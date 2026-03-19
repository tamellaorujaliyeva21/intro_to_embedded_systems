int red = 5;
int green = 7; 
int blue = 10;

void setup()
{
  pinMode(red, OUTPUT);
  pinMode(blue, OUTPUT);
  pinMode(green, OUTPUT);
}

void loop()
{
  digitalWrite(red, HIGH);
  delay(500);
  digitalWrite(red, LOW);

  digitalWrite(blue, HIGH);
  delay(500);
  digitalWrite(blue, LOW);

  digitalWrite(green, HIGH);
  delay(500);
  digitalWrite(green, LOW);
  
	
}
