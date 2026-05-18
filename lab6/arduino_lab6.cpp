// LAB 6 ARDUINO CODE
// This code controls the Arduino side of the two-player reaction game.
// The idea is simple: both players wait for the buzzer, then press their button.
// The faster player wins the round. First player to reach 3 points wins the game.

// Servo is used to point/show which player won the round.
#include "Servo.h"

// Stepper motor is used to move step by step depending on who wins.
#include <Stepper.h>

// The 28BYJ-48 stepper motor usually needs 2048 steps for one full rotation.
const int stepsPerRevolution = 2048;

// Here we create the stepper motor object.
// The numbers 11, 9, 10, 8 are the Arduino pins connected to the stepper driver.
Stepper myStepper(stepsPerRevolution, 11, 9, 10, 8);

// Here we create the servo object.
Servo myservo;

// Pin connections for the servo, buzzer, and both player buttons.
int servoPin = 12;
int buzzer = 3;
int buttonPlayer1 = 6;
int buttonPlayer2 = 5;

// These variables keep the current score of each player.
// At the beginning, both players start from 0.
int score1 = 0;
int score2 = 0;

// These variables are used for measuring reaction time.
// millis() gives us the time in milliseconds since Arduino started running.
unsigned long startTime;
unsigned long reactionTime1;
unsigned long reactionTime2;

// This keeps track of how far the stepper motor moved.
// We use it later to return the stepper back to its starting position.
int stepperPosition = 0;

void setup() {
  // Start serial communication with the computer.
  // The Python GUI reads messages from Arduino using this speed.
  Serial.begin(9600);

  // Set the speed of the stepper motor.
  // Higher speed makes it faster, but it can lose steps or move less accurately.
  // Lower speed makes it slower, but usually more stable.
  myStepper.setSpeed(1000);

  // Attach the servo motor to its pin.
  myservo.attach(servoPin);

  // Buttons use INPUT_PULLUP, so their normal state is HIGH.
  // When the button is pressed, the reading becomes LOW.
  pinMode(buttonPlayer1, INPUT_PULLUP);
  pinMode(buttonPlayer2, INPUT_PULLUP);

  // Buzzer pin is an output because Arduino sends sound signal to it.
  pinMode(buzzer, OUTPUT);

  // This helps random() generate different delay times each time the game starts.
  // A0 is used as a random source because it may read small noise if it is not connected.
  randomSeed(analogRead(A0));

  // Put the servo in the middle position at the beginning.
  myservo.write(90);

  // Send a message to the GUI that the Arduino game is ready.
  Serial.println("GAME STARTS AUTOMATICALLY");
}

void loop() {
  // Before each new game, reset scores and motor positions.
  resetGame();

  // Start playing the reaction game.
  playGame();

  // Small pause before the next full game starts again.
  // If this delay is increased, players wait longer before the next game.
  // If it is decreased, the game restarts faster.
  delay(5000);
}

void playGame() {
  // Keep the servo in the center at the beginning of the game.
  myservo.write(90);

  // The game continues until one of the players reaches 3 points.
  while (score1 < 3 && score2 < 3) {

    // Tell the Python GUI that a new round has started.
    Serial.println("NEW ROUND");

    // Generate a random waiting time between 1 second and 20 seconds.
    // Players must NOT press during this waiting time.
    int delayTime = random(1000, 20001);

    // Save the time when the waiting period started.
    unsigned long waitStart = millis();

    // This loop checks for false starts before the buzzer.
    while (millis() - waitStart < delayTime) {

      // If Player 1 presses before the buzzer, it is a false start.
      if (digitalRead(buttonPlayer1) == LOW) {
        Serial.println("FALSE START P1");

        // Player 2 gets the point because Player 1 pressed too early.
        score2++;

        // Move stepper in Player 2's direction.
        updateStepper(2);

        // Small pause so the result can be noticed.
        delay(1000);

        // End this game attempt and return to loop().
        return;
      }

      // If Player 2 presses before the buzzer, it is a false start.
      if (digitalRead(buttonPlayer2) == LOW) {
        Serial.println("FALSE START P2");

        // Player 1 gets the point because Player 2 pressed too early.
        score1++;

        // Move stepper in Player 1's direction.
        updateStepper(1);

        delay(1000);
        return;
      }
    }

    // If nobody pressed early, the buzzer gives the signal to press.
    tone(buzzer, 1000);   // Start buzzer sound at 1000 Hz.
    delay(200);           // Sound lasts for 200 ms.
    noTone(buzzer);       // Stop the buzzer.

    // Save the exact moment when players are allowed to press.
    startTime = millis();

    // These bool variables tell us whether each player has pressed already.
    bool p1Pressed = false;
    bool p2Pressed = false;

    // Reaction phase:
    // The program waits until both players press their buttons.
    while (!p1Pressed || !p2Pressed) {

      // If Player 1 has not pressed yet and now presses the button,
      // save Player 1's reaction time.
      if (!p1Pressed && digitalRead(buttonPlayer1) == LOW) {
        reactionTime1 = millis() - startTime;
        p1Pressed = true;
      }

      // If Player 2 has not pressed yet and now presses the button,
      // save Player 2's reaction time.
      if (!p2Pressed && digitalRead(buttonPlayer2) == LOW) {
        reactionTime2 = millis() - startTime;
        p2Pressed = true;
      }
    }

    // Now compare both reaction times.
    // Smaller reaction time means faster response.
    if (reactionTime1 < reactionTime2) {
      // Player 1 was faster, so Player 1 gets one point.
      score1++;

      // Send the winner and reaction time to the Python GUI.
      Serial.print("P1 WIN: ");
      Serial.println(reactionTime1);

      // Move the servo toward Player 1's side.
      moveServo(1);

      // Move the stepper motor in Player 1's direction.
      updateStepper(1);
    } 
    else {
      // Player 2 was faster, so Player 2 gets one point.
      score2++;

      // Send the winner and reaction time to the Python GUI.
      Serial.print("P2 WIN: ");
      Serial.println(reactionTime2);

      // Move the servo toward Player 2's side.
      moveServo(2);

      // Move the stepper motor in Player 2's direction.
      updateStepper(2);
    }

    // Short pause before the next round starts.
    delay(1500);
  }

  // When the loop ends, one player has reached 3 points.
  // Send the final winner to the Python GUI.
  if (score1 == 3) {
    Serial.println("GAME WINNER: P1");
  } else {
    Serial.println("GAME WINNER: P2");
  }

  // Make the stepper motor spin once as a victory effect.
  victorySpin();
}

void moveServo(int player) {
  // This function moves the servo to show who won the round.
  if (player == 1) {
    // Move servo to one side for Player 1.
    myservo.write(0);
  } else {
    // Move servo to the other side for Player 2.
    myservo.write(180);
  }
}

void updateStepper(int player) {
  // This function moves the stepper motor depending on who scored.
  if (player == 1) {
    // Move 50 steps in Player 1's direction.
    myStepper.step(50);

    // Save this movement so we can reset the motor later.
    stepperPosition += 50;
  } else {
    // Move 50 steps in the opposite direction for Player 2.
    myStepper.step(-50);

    // Save this movement as a negative position.
    stepperPosition -= 50;
  }
}

void victorySpin() {
  // This makes the stepper motor complete one full rotation
  // after the final winner is announced.
  myStepper.step(stepsPerRevolution);
}

void resetGame() {
  // Reset both scores before a new game starts.
  score1 = 0;
  score2 = 0;

  // Move the stepper motor back to where it started.
  // If it moved +150 steps before, this moves it -150 steps.
  // If it moved -100 steps before, this moves it +100 steps.
  myStepper.step(-stepperPosition);

  // After resetting, the stored position becomes zero again.
  stepperPosition = 0;

  // Put the servo back to the center position.
  myservo.write(90);
}
