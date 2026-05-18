# LAB 6 GUI CODE
# This program is the computer-side interface for the two-player reaction game.
# It connects to the Arduino through the serial port, shows the live game status,
# saves each player's results into CSV files, and plots simple statistics later.

import csv
import os
import queue
import threading
import time
import tkinter as tk
from collections import defaultdict
from datetime import datetime
from tkinter import messagebox, ttk

import matplotlib

# TkAgg lets matplotlib graphs appear inside the Tkinter window.
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import serial
import serial.tools.list_ports

# All player data will be stored inside this folder.
DATA_DIR = "players"
os.makedirs(DATA_DIR, exist_ok=True)

# This separate CSV file keeps only the final match victories.
VICTORY_LOG = os.path.join(DATA_DIR, "_victories.csv")


# ======================================================================
# Serial link — reads Arduino messages without freezing the GUI
# ======================================================================
class SerialManager:
    def __init__(self):
        # This will hold the actual serial connection after we connect.
        self.ser = None

        # Arduino messages are placed here first, then the GUI reads them safely.
        self.rx_queue = queue.Queue()

        # These variables help control the background reading thread.
        self._running = False
        self._thread = None

    @staticmethod
    def list_ports():
        # Returns all available serial ports, for example COM3 on Windows.
        return [p.device for p in serial.tools.list_ports.comports()]

    def connect(self, port, baud=9600):
        # Opens the selected Arduino port.
        self.ser = serial.Serial(port, baud, timeout=0.1)

        # Arduino UNO usually resets when serial is opened, so we wait a bit.
        time.sleep(2.0)
        self.ser.reset_input_buffer()

        # Start reading serial data in the background.
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def disconnect(self):
        # Stop the background reader and close the serial connection.
        self._running = False
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            # If closing fails, we do not crash the program.
            pass
        self.ser = None

    def is_open(self):
        # Checks whether the serial port is currently connected.
        return self.ser is not None and self.ser.is_open

    def _reader(self):
        # This function runs in a separate thread.
        # Its job is to collect complete lines sent by the Arduino.
        buf = b""
        while self._running and self.ser:
            try:
                chunk = self.ser.read(128)
                if chunk:
                    buf += chunk

                    # Arduino messages end with a new line, so we split by \n.
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            text = line.decode("utf-8", errors="ignore").strip()
                        except Exception:
                            text = ""

                        # Only non-empty messages are sent to the GUI.
                        if text:
                            self.rx_queue.put(text)
            except Exception:
                # If the serial cable is removed or another error happens, stop reading.
                break

    def poll(self):
        # The GUI calls this often to check whether a new Arduino line arrived.
        try:
            return self.rx_queue.get_nowait()
        except queue.Empty:
            return None


# ======================================================================
# Saving and loading player data using CSV files
# ======================================================================
class PlayerData:
    @staticmethod
    def safe_name(name):
        # Makes the player name safe to use as a file name.
        # For example, it removes unusual symbols that could break file paths.
        clean = "".join(c for c in name if c.isalnum() or c in ("-", "_", " ")).strip()
        return clean or "unnamed"

    @classmethod
    def path_for(cls, name):
        # Each player has their own CSV file inside the players folder.
        return os.path.join(DATA_DIR, f"{cls.safe_name(name)}.csv")

    @classmethod
    def record_round(cls, player, opponent, rt_ms, won, false_start,
                     session_id, round_num):
        # Saves one round result for one player.
        # This function is called for both players after every round.
        path = cls.path_for(player)
        is_new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)

            # If this player file is new, write the column names first.
            if is_new:
                w.writerow([
                    "timestamp", "session_id", "round", "opponent",
                    "reaction_time_ms", "won", "false_start"
                ])

            # If the player did not have a reaction time, we store an empty value.
            w.writerow([
                datetime.now().isoformat(timespec="seconds"),
                session_id, round_num, opponent,
                rt_ms if rt_ms is not None else "",
                int(bool(won)), int(bool(false_start))
            ])

    @staticmethod
    def record_victory(winner, loser, session_id, final_score):
        # Saves the final result of the whole match.
        is_new = not os.path.exists(VICTORY_LOG)
        with open(VICTORY_LOG, "a", newline="") as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(["timestamp", "session_id", "winner", "loser", "final_score"])
            w.writerow([
                datetime.now().isoformat(timespec="seconds"),
                session_id, winner, loser, final_score
            ])

    @classmethod
    def load_player(cls, name):
        # Reads all saved rounds for the selected player.
        path = cls.path_for(name)
        if not os.path.exists(path):
            return []
        with open(path, newline="") as f:
            return list(csv.DictReader(f))

    @staticmethod
    def list_players():
        # Finds all saved player files, but ignores files starting with underscore.
        if not os.path.isdir(DATA_DIR):
            return []
        return sorted(
            f[:-4] for f in os.listdir(DATA_DIR)
            if f.endswith(".csv") and not f.startswith("_")
        )


# ======================================================================
# Main GUI application
# ======================================================================
class ReactionGameApp:
    # These states make it easier to understand what stage the game is in.
    IDLE   = "idle"      # no active match yet
    ACTIVE = "active"    # match is currently running
    ENDED  = "ended"     # match finished, waiting for the next one

    def __init__(self, root):
        self.root = root
        self.root.title("Lab Task 6 — Two-Player Reaction Game (Host)")
        self.root.geometry("950x760")

        # SerialManager handles all communication with Arduino.
        self.link = SerialManager()

        # These names are prepared for the next match after pressing Arm.
        self.pending_p1 = ""
        self.pending_p2 = ""
        self.armed = False

        # These are the names currently used for recording the match.
        self.p1_name = ""
        self.p2_name = ""

        # Current match information.
        self.state = self.IDLE
        self.p1_wins = 0
        self.p2_wins = 0
        self.round_num = 0
        self.session_id = ""

        # Build the interface and start checking for Arduino messages.
        self._build_ui()
        self._pump_serial()

    def _build_ui(self):
        # Notebook creates tabs: one for the game and one for statistics.
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True)

        self.game_tab = ttk.Frame(self.nb)
        self.stats_tab = ttk.Frame(self.nb)
        self.nb.add(self.game_tab, text="Game")
        self.nb.add(self.stats_tab, text="Statistics")

        self._build_game_tab()
        self._build_stats_tab()

    def _build_game_tab(self):
        # ---------------- Arduino connection area ----------------
        conn = ttk.LabelFrame(self.game_tab, text="Arduino connection")
        conn.pack(fill="x", padx=10, pady=6)

        ttk.Label(conn, text="Port:").grid(row=0, column=0, padx=4, pady=4)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(conn, textvariable=self.port_var, width=22)
        self.port_combo.grid(row=0, column=1, padx=4)
        ttk.Button(conn, text="Refresh", command=self._refresh_ports).grid(row=0, column=2, padx=4)
        self.connect_btn = ttk.Button(conn, text="Connect", command=self._toggle_connect)
        self.connect_btn.grid(row=0, column=3, padx=4)
        self.conn_status = ttk.Label(conn, text="Disconnected", foreground="red")
        self.conn_status.grid(row=0, column=4, padx=10)
        self._refresh_ports()

        # ---------------- Player name area ----------------
        names = ttk.LabelFrame(self.game_tab, text="Players for next match")
        names.pack(fill="x", padx=10, pady=6)

        ttk.Label(names, text="Player 1 (D6):").grid(row=0, column=0, padx=4, pady=4, sticky="e")
        self.p1_entry = ttk.Entry(names, width=22)
        self.p1_entry.grid(row=0, column=1, padx=4)

        ttk.Label(names, text="Player 2 (D5):").grid(row=0, column=2, padx=4, pady=4, sticky="e")
        self.p2_entry = ttk.Entry(names, width=22)
        self.p2_entry.grid(row=0, column=3, padx=4)

        # Arm means: use these names when the next new match starts.
        self.arm_btn = ttk.Button(names, text="Arm for next match", command=self._arm_names)
        self.arm_btn.grid(row=0, column=4, padx=10)

        self.armed_status = ttk.Label(names, text="Not armed", foreground="#a60")
        self.armed_status.grid(row=1, column=0, columnspan=5, sticky="w", padx=4, pady=(0, 4))

        # ---------------- Match display area ----------------
        match = ttk.LabelFrame(self.game_tab, text="Match")
        match.pack(fill="x", padx=10, pady=6)

        # Shows the score in a large font.
        self.score_label = ttk.Label(match, text="— vs —", font=("Arial", 22, "bold"), anchor="center")
        self.score_label.pack(fill="x", pady=6)

        # Shows simple instructions or match status.
        self.status_label = ttk.Label(match, text="Waiting for Arduino...", font=("Arial", 13), foreground="#333")
        self.status_label.pack(fill="x", pady=2)

        # Shows the reaction time of the round winner.
        self.rt_label = ttk.Label(match, text="", font=("Consolas", 12), foreground="#036")
        self.rt_label.pack(fill="x", pady=2)

        # ---------------- Raw serial log area ----------------
        log_frame = ttk.LabelFrame(self.game_tab, text="Event log (raw serial)")
        log_frame.pack(fill="both", expand=True, padx=10, pady=6)

        # This log is useful while testing because it shows exactly what Arduino sent.
        self.log = tk.Text(log_frame, height=14, wrap="word", bg="#111", fg="#ddd")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)
        self.log.tag_config("ard", foreground="#6af")
        self.log.tag_config("warn", foreground="#fa6")
        self.log.tag_config("win", foreground="#6f6")
        self.log.tag_config("info", foreground="#ddd")

    def _build_stats_tab(self):
        # Top row contains the controls for choosing what graph to show.
        top = ttk.Frame(self.stats_tab)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="Player:").pack(side="left", padx=4)
        self.viz_player_var = tk.StringVar()
        self.viz_player_combo = ttk.Combobox(top, textvariable=self.viz_player_var, width=22)
        self.viz_player_combo.pack(side="left", padx=4)

        ttk.Label(top, text="View:").pack(side="left", padx=8)
        self.viz_mode_var = tk.StringVar(value="Reaction time over sessions")
        ttk.Combobox(
            top, textvariable=self.viz_mode_var, state="readonly", width=32,
            values=["Reaction time over sessions", "Win rate by opponent", "Head-to-head reaction times"]
        ).pack(side="left", padx=4)

        ttk.Label(top, text="H2H opponent:").pack(side="left", padx=6)
        self.viz_opp_var = tk.StringVar()
        self.viz_opp_combo = ttk.Combobox(top, textvariable=self.viz_opp_var, width=18)
        self.viz_opp_combo.pack(side="left", padx=4)

        ttk.Button(top, text="Refresh list", command=self._refresh_player_list).pack(side="left", padx=8)
        ttk.Button(top, text="Plot", command=self._plot).pack(side="left", padx=4)

        # Matplotlib figure embedded inside Tkinter.
        self.fig = Figure(figsize=(8, 5), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title("Load data to begin")
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.stats_tab)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=8)
        self._refresh_player_list()

    def _refresh_ports(self):
        # Update the port dropdown with currently connected devices.
        ports = SerialManager.list_ports()
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _toggle_connect(self):
        # This same button is used for both connecting and disconnecting.
        if self.link.is_open():
            self.link.disconnect()
            self.conn_status.config(text="Disconnected", foreground="red")
            self.connect_btn.config(text="Connect")
            self._log("Disconnected.", "info")
            return

        # If not connected yet, try to open the selected serial port.
        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("No port", "Select a serial port first.")
            return
        try:
            self.link.connect(port)
            self.conn_status.config(text=f"Connected: {port}", foreground="green")
            self.connect_btn.config(text="Disconnect")
            self._log(f"Opened serial port {port}.", "info")
        except Exception as exc:
            messagebox.showerror("Serial error", f"Could not open {port}:\n{exc}")

    def _arm_names(self):
        # Read player names from the input fields.
        p1 = self.p1_entry.get().strip()
        p2 = self.p2_entry.get().strip()

        # Both names are required, otherwise the data would be unclear.
        if not p1 or not p2:
            messagebox.showwarning("Names", "Enter both player names first.")
            return
        if p1.lower() == p2.lower():
            messagebox.showwarning("Names", "Player names must be different.")
            return

        # Store these names until the next match actually begins.
        self.pending_p1 = p1
        self.pending_p2 = p2
        self.armed = True

        status_text = f"Armed — '{p1}' vs '{p2}'"
        if self.state == self.ACTIVE:
            status_text += " will take effect at next match."
        else:
            status_text += " will record from the next NEW ROUND."

        self.armed_status.config(text=status_text, foreground="#036")
        self._log(f"Armed for next match: {p1} vs {p2}.", "info")

    def _log(self, msg, tag=None):
        # Add a timestamped message to the event log.
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = "[%s] " % ts
        self.log.insert("end", prefix + msg + "\n", tag)
        self.log.see("end")

    def _pump_serial(self):
        # This function keeps checking if Arduino sent something.
        # root.after calls it again every 30 ms, so the GUI stays responsive.
        while True:
            line = self.link.poll()
            if line is None:
                break
            self._handle_arduino_line(line)
        self.root.after(30, self._pump_serial)

    def _handle_arduino_line(self, line):
        # Decide what to do depending on the message received from Arduino.
        self._log(f"ARD> {line}", "ard")
        if line == "GAME STARTS AUTOMATICALLY":
            self.state = self.IDLE
            self.status_label.config(text="Arduino ready. Enter names & arm, or just watch.", foreground="#333")
            return
        if line == "NEW ROUND":
            self._on_new_round()
            return
        if line.startswith("P1 WIN:") or line.startswith("P2 WIN:"):
            self._on_round_win(line)
            return
        if line.startswith("FALSE START"):
            self._on_false_start(line)
            return
        if line.startswith("GAME WINNER:"):
            self._on_game_winner(line)
            return

    def _begin_new_match(self):
        # Start a new match. If names were armed, use them now.
        if self.armed and self.pending_p1 and self.pending_p2:
            self.p1_name = self.pending_p1
            self.p2_name = self.pending_p2
            self.armed = False
            self.armed_status.config(text=f"Recording: {self.p1_name} vs {self.p2_name}", foreground="#060")
            self._log(f"Match started: {self.p1_name} vs {self.p2_name}.", "win")

        # Important: we do not erase names here.
        # This lets the same two players play a rematch without typing names again.

        # Reset the score and round count for this new match.
        self.p1_wins = 0
        self.p2_wins = 0
        self.round_num = 0

        # session_id separates one match from another in the saved CSV files.
        self.session_id = datetime.now().strftime("%Y%m%dT%H%M%S")
        self.state = self.ACTIVE
        self._update_scoreboard()

    def _on_new_round(self):
        # Arduino sends NEW ROUND at the start of each round.
        # If we were idle or already finished, this means a new match starts too.
        if self.state in (self.IDLE, self.ENDED):
            self._begin_new_match()

        self.round_num += 1
        if self.p1_name and self.p2_name:
            self.status_label.config(text=f"Round {self.round_num}: wait for buzzer, then press!", foreground="#a60")
        else:
            self.status_label.config(text=f"Round {self.round_num} (not recorded — no names armed).", foreground="#a60")
        self.rt_label.config(text="")

    def _on_round_win(self, line):
        # Arduino sends messages like: P1 WIN: 350
        # The number means the winning player's reaction time in milliseconds.
        try:
            prefix, rt_str = line.split(":", 1)
            winner = 1 if prefix.strip() == "P1 WIN" else 2
            rt = int(rt_str.strip())
        except ValueError:
            # Ignore the line if it was not in the expected format.
            return

        # If somehow a win comes before the app knows a match started, start one now.
        if self.state != self.ACTIVE:
            self._begin_new_match()
            self.round_num = max(self.round_num, 1)

        # Add one point to the round winner and show their reaction time.
        if winner == 1:
            self.p1_wins += 1
            self.rt_label.config(text=f"{self._name_for(1)}: {rt} ms (winner) | {self._name_for(2)}: —")
        else:
            self.p2_wins += 1
            self.rt_label.config(text=f"{self._name_for(1)}: — | {self._name_for(2)}: {rt} ms (winner)")

        self._update_scoreboard()

        # Save this round only if player names are known.
        if self.p1_name and self.p2_name:
            if winner == 1:
                PlayerData.record_round(self.p1_name, self.p2_name, rt, True, False, self.session_id, self.round_num)
                PlayerData.record_round(self.p2_name, self.p1_name, None, False, False, self.session_id, self.round_num)
            else:
                PlayerData.record_round(self.p1_name, self.p2_name, None, False, False, self.session_id, self.round_num)
                PlayerData.record_round(self.p2_name, self.p1_name, rt, True, False, self.session_id, self.round_num)

        # First player to 3 points wins the match.
        if self.p1_wins >= 3 or self.p2_wins >= 3:
            self.state = self.ENDED
            self.status_label.config(text=f"Round {self.round_num}: {self._name_for(winner)} wins. Match point reached.", foreground="#060")
        else:
            self.status_label.config(text=f"Round {self.round_num}: {self._name_for(winner)} wins ({rt} ms). Next round starts automatically.", foreground="#036")

    def _on_false_start(self, line):
        # False start means one player pressed too early.
        # The point goes to the other player.
        who = line.split()[-1].upper()
        offender = 1 if who == "P1" else 2
        winner = 2 if offender == 1 else 1

        if self.state != self.ACTIVE:
            self._begin_new_match()
            self.round_num = max(self.round_num, 1)

        if winner == 1:
            self.p1_wins += 1
        else:
            self.p2_wins += 1

        self._update_scoreboard()
        self.rt_label.config(text=f"FALSE START by {self._name_for(offender)} — round to {self._name_for(winner)}")

        # Save the false start result for both players.
        if self.p1_name and self.p2_name:
            PlayerData.record_round(self.p1_name, self.p2_name, None, (winner == 1), (offender == 1), self.session_id, self.round_num)
            PlayerData.record_round(self.p2_name, self.p1_name, None, (winner == 2), (offender == 2), self.session_id, self.round_num)

        self._log(f"FALSE START by P{offender} — point to P{winner}. (Arduino ends this match.)", "warn")
        self.state = self.ENDED
        self.status_label.config(text="Match ended on false start. Arduino restarts in ~5 s.", foreground="#a06")

        # If the false start also made the score reach 3, record the match victory.
        if self.p1_name and self.p2_name and (self.p1_wins >= 3 or self.p2_wins >= 3):
            self._finalise_match_victory()

    def _on_game_winner(self, line):
        # Arduino sends the final winner of the match, for example: GAME WINNER: P1
        winner_str = line.split(":", 1)[1].strip().upper()
        winner = 1 if winner_str == "P1" else 2

        # If the GUI score is not already at 3, correct it using Arduino's final message.
        if self.p1_wins < 3 and self.p2_wins < 3:
            if winner == 1:
                self.p1_wins = 3
            else:
                self.p2_wins = 3
            self._update_scoreboard()

        self.state = self.ENDED
        self.status_label.config(text=f"  MATCH WINNER: {self._name_for(winner)}", foreground="#060")
        self._log(f"*** MATCH WINNER: {self._name_for(winner)} ***", "win")

        if self.p1_name and self.p2_name:
            self._finalise_match_victory()

        # Keep names after the match, so a rematch is easier.
        self.armed_status.config(text=f"Match finished. Ready for rematch: {self._name_for(1)} vs {self._name_for(2)}", foreground="#060")

    def _finalise_match_victory(self):
        # Save the final winner and loser into the victory log.
        winner_name = self._name_for(1 if self.p1_wins >= self.p2_wins else 2)
        loser_name = self._name_for(2 if winner_name == self.p1_name else 1)
        final_score = f"{self.p1_wins}-{self.p2_wins}"
        PlayerData.record_victory(winner_name, loser_name, self.session_id, final_score)
        self._refresh_player_list()

    def _name_for(self, player_num):
        # Returns the real player name if available, otherwise a default label.
        if player_num == 1:
            return self.p1_name or "Player 1"
        return self.p2_name or "Player 2"

    def _update_scoreboard(self):
        # Refresh the big score text on the screen.
        self.score_label.config(text=f"{self._name_for(1)}: {self.p1_wins}    —    {self._name_for(2)}: {self.p2_wins}")

    # ==================================================================
    # Statistics visualisation
    # ==================================================================
    def _refresh_player_list(self):
        # Reload all saved player names into the dropdown menus.
        players = PlayerData.list_players()
        self.viz_player_combo["values"] = players
        self.viz_opp_combo["values"] = players
        if players:
            if not self.viz_player_var.get() or self.viz_player_var.get() not in players:
                self.viz_player_var.set(players[0])
            if len(players) > 1 and (not self.viz_opp_var.get() or self.viz_opp_var.get() not in players):
                self.viz_opp_var.set(players[1])

    def _plot(self):
        # Read the selected player and draw the selected graph.
        name = self.viz_player_var.get().strip()
        if not name:
            messagebox.showinfo("No player", "Select a player first.")
            return
        rows = PlayerData.load_player(name)
        if not rows:
            messagebox.showinfo("No data", f"No saved data for '{name}' yet.")
            return

        self.ax.clear()
        mode = self.viz_mode_var.get()
        if mode == "Reaction time over sessions":
            self._plot_rt_by_session(name, rows)
        elif mode == "Win rate by opponent":
            self._plot_winrate(name, rows)
        elif mode == "Head-to-head reaction times":
            opp = self.viz_opp_var.get().strip()
            if not opp:
                messagebox.showinfo("Opponent", "Pick an opponent for head-to-head.")
                return
            self._plot_h2h(name, opp, rows)

        self.fig.tight_layout()
        self.canvas.draw()

    def _plot_rt_by_session(self, name, rows):
        # Group all winning reaction times by match/session.
        sess_rts = defaultdict(list)
        for r in rows:
            if r.get("false_start") == "1":
                continue
            try:
                rt = float(r["reaction_time_ms"])
            except (TypeError, ValueError):
                continue
            sess_rts[r["session_id"]].append(rt)

        if not sess_rts:
            self.ax.set_title(f"{name} — no reaction times recorded")
            return

        # For every session, calculate average and best reaction time.
        sessions = sorted(sess_rts.keys())
        avg = [sum(sess_rts[s]) / len(sess_rts[s]) for s in sessions]
        best = [min(sess_rts[s]) for s in sessions]
        x = list(range(len(sessions)))

        self.ax.plot(x, avg, "o-", label="Avg RT (wins)")
        self.ax.plot(x, best, "s--", label="Best RT")
        self.ax.set_xticks(x)
        self.ax.set_xticklabels([s[:8] for s in sessions], rotation=45, ha="right")
        self.ax.set_ylabel("Reaction time (ms)")
        self.ax.set_title(f"{name} — RT across sessions")
        self.ax.grid(True, alpha=0.3)
        self.ax.legend()

    def _plot_winrate(self, name, rows):
        # Count how many rounds were played and won against each opponent.
        stats = defaultdict(lambda: [0, 0])
        for r in rows:
            opp = r["opponent"]
            stats[opp][1] += 1
            if r.get("won") == "1":
                stats[opp][0] += 1

        if not stats:
            self.ax.set_title(f"{name} — no opponents yet")
            return

        # Convert wins/total rounds into percentages.
        opps = sorted(stats.keys())
        rates = [100.0 * stats[o][0] / stats[o][1] for o in opps]
        self.ax.bar(opps, rates, color="#4a8")
        self.ax.set_ylabel("Win rate (%)")
        self.ax.set_title(f"{name} — win rate by opponent")
        self.ax.set_ylim(0, 115)
        self.ax.grid(True, alpha=0.3, axis="y")

    def _plot_h2h(self, name, opp, rows):
        # Show only reaction times for this player against one selected opponent.
        rts = []
        for r in rows:
            if r["opponent"] == opp and r.get("false_start") != "1":
                try:
                    rts.append(float(r["reaction_time_ms"]))
                except (TypeError, ValueError):
                    continue

        if not rts:
            self.ax.set_title(f"No RT data for {name} vs {opp}")
            return

        # Plot each winning reaction time and add a mean line for comparison.
        self.ax.plot(range(1, len(rts) + 1), rts, "o-", color="#c36")
        self.ax.axhline(sum(rts) / len(rts), linestyle="--", color="#888", label="mean")
        self.ax.set_ylabel("Reaction time (ms)")
        self.ax.set_title(f"{name} vs {opp} — winning reaction times")
        self.ax.grid(True, alpha=0.3)
        self.ax.legend()


# This part runs only when the file is started directly.
if __name__ == "__main__":
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        # If this theme is not available, Tkinter will just use the default style.
        pass
    app = ReactionGameApp(root)
    root.mainloop()
