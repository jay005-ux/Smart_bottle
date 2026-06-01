import time
import math
import threading
import requests
import queue
import json
import os
from collections import deque

import RPi.GPIO as GPIO
import board
import busio
import adafruit_dht
import smbus2
import adafruit_vl53l0x
from flask import Flask, jsonify, request


# ================= CONFIG =================

class Config:
    BUZZER = 18
    YELLOW_LED = 17
    RED_LED = 27
    LED = YELLOW_LED

    DEVICE_ID = os.environ.get("SMART_BOTTLE_DEVICE_ID", "bottle_01")

    # Empty calibration:
    # raw_empty_dist may be around 28-29 cm.
    # corrected empty distance is fixed to 20 cm.
    # distance_offset = raw_empty_dist - BOTTLE_HEIGHT.
    BOTTLE_HEIGHT = 20.0
    BOTTLE_CAPACITY = 2000.0

    BASE_GOAL = 4000
    WARM_TEMP_LIMIT = 34.0
    HOT_TEMP_LIMIT = 38.0
    VERY_HOT_TEMP_LIMIT = 40.0
    EXTREME_TEMP_LIMIT = 45.0

    WARM_TEMP_EXTRA_GOAL = 250
    HOT_TEMP_EXTRA_GOAL = 500
    VERY_HOT_TEMP_EXTRA_GOAL = 750
    EXTREME_TEMP_EXTRA_GOAL = 1000

    NORMAL_REMINDER_SECONDS = 7200      # 2 hours
    WARM_REMINDER_SECONDS = 5400        # 90 minutes
    HOT_REMINDER_SECONDS = 3600         # 60 minutes
    VERY_HOT_REMINDER_SECONDS = 2700    # 45 minutes
    EXTREME_REMINDER_SECONDS = 1800     # 30 minutes

    SCHOOL_DAY_START_HOUR = 8
    SCHOOL_DAY_END_HOUR = 20
    BEHIND_GOAL_MARGIN_ML = 300

    API_BASE_URL = os.environ.get("SMART_BOTTLE_API_BASE_URL", "http://192.168.18.73:8000/api").rstrip("/")
    SERVER = os.environ.get("SMART_BOTTLE_SERVER_URL", f"{API_BASE_URL}/add/")
    DEVICE_TOKEN = os.environ.get("SMART_BOTTLE_DEVICE_TOKEN", "")
    SENSOR_DELAY = float(os.environ.get("SMART_BOTTLE_SENSOR_DELAY", "0.5"))
    DEBUG_SENSOR = os.environ.get("SMART_BOTTLE_DEBUG_SENSOR", "0") == "1"
    TEMP_READ_INTERVAL_SECONDS = 8
    STATE_SAVE_INTERVAL_SECONDS = 30
    NETWORK_TIMEOUT_SECONDS = 2

    DIST_VALID_MIN = 0.5
    DIST_VALID_MAX = 45.0

    TOF_READS_PER_SAMPLE = 8
    TOF_MIN_VALID_READS = 6
    TOF_RAW_OUTLIER_CM = 1.2
    TOF_STABILITY_WINDOW = 4

    LEVEL_DEAD_ZONE_ML = 10.0
    LEVEL_CONFIRM_COUNT = 4

    EVENT_MIN_ML = 20.0
    EVENT_CONFIRM_COUNT = 3

    IMU_SAMPLES = 5
    UPRIGHT_LIMIT_DEG = 6.0
    TILT_CONFIRM_COUNT = 1
    RETURN_STABLE_COUNT = 5

    DROP_LATCH_SECONDS = 30
    HEARTBEAT_INTERVAL_SECONDS = 5
    DRINK_TILT_MAX_SECONDS = 8
    DRINK_TILT_MIN_SECONDS = 1.0
    POURING_TILT_DEG = 35
    SHAKING_MPU_STABILITY_LIMIT = 55
    EVENT_BLOCK_AFTER_SHAKE_SECONDS = 4.0
    EVENT_BLOCK_AFTER_TILT_SECONDS = 2.0
    LEVEL_SETTLE_SECONDS = 1.5
    MAX_AUTO_EVENT_ML = 900.0

    REMINDER_BEEP_REPEAT_SECONDS = 300
    LOW_WATER_BEEP_REPEAT_SECONDS = 300
    EMPTY_BEEP_REPEAT_SECONDS = 10
    SENSOR_ERROR_BEEP_REPEAT_SECONDS = 2
    CALIBRATION_BEEP_REPEAT_SECONDS = 5
    HIGH_TEMP_BEEP_REPEAT_SECONDS = 300
    EXTREME_HEAT_BEEP_REPEAT_SECONDS = 60

    STATE_FILE = "smart_bottle_state.json"
    OFFLINE_QUEUE_FILE = "offline_payloads.jsonl"
    CALIBRATION_POINTS_FILE = "calibration_points.json"
    DAILY_RESET_HOUR = 0
    NORMAL_PAYLOAD_INTERVAL_SECONDS = 2.0


# ================= GPIO =================

class GPIOManager:
    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        GPIO.setup(Config.BUZZER, GPIO.OUT)
        GPIO.setup(Config.YELLOW_LED, GPIO.OUT)
        GPIO.setup(Config.RED_LED, GPIO.OUT)

        GPIO.output(Config.BUZZER, False)
        GPIO.output(Config.YELLOW_LED, False)
        GPIO.output(Config.RED_LED, False)

        self.last_reminder_beep = 0
        self.last_low_water_beep = 0
        self.last_empty_beep = 0
        self.last_sensor_error_beep = 0
        self.last_calibration_beep = 0
        self.last_high_temp_beep = 0
        self.last_extreme_heat_beep = 0

    def cleanup(self):
        GPIO.cleanup()

    def _blink(self, period_seconds):
        return int(time.time() / period_seconds) % 2 == 0

    def _beep(self, duration=0.08, count=1, gap=0.08):
        for i in range(count):
            GPIO.output(Config.BUZZER, True)
            time.sleep(duration)
            GPIO.output(Config.BUZZER, False)
            if i < count - 1:
                time.sleep(gap)

    def _periodic_beep(self, attr_name, repeat_seconds, duration=0.08, count=1, gap=0.08):
        now = time.time()
        last_time = getattr(self, attr_name)

        if now - last_time >= repeat_seconds:
            setattr(self, attr_name, now)
            self._beep(duration=duration, count=count, gap=gap)

    def signal_calibration(self):
        GPIO.output(Config.YELLOW_LED, False)
        GPIO.output(Config.RED_LED, True)
        self._beep(duration=0.08, count=1)

    def set_alert_outputs(self, alert, event, percent):
        yellow = False
        red = False

        if alert == "Check sensor":
            red = True
            yellow = self._blink(0.5)
            self._periodic_beep(
                "last_sensor_error_beep",
                Config.SENSOR_ERROR_BEEP_REPEAT_SECONDS,
                duration=0.2,
                count=1,
            )

        elif alert == "Calibration Required":
            red = True
            self._periodic_beep(
                "last_calibration_beep",
                Config.CALIBRATION_BEEP_REPEAT_SECONDS,
                duration=0.1,
                count=1,
            )

        elif event == "FILL":
            yellow = True

        elif event == "DRINK":
            yellow = True
            self._beep(duration=0.08, count=2)

        elif event == "DROP":
            yellow = self._blink(0.25)
            self._beep(duration=0.35, count=1)

        elif alert == "Extreme heat - drink water and move to shade":
            yellow = self._blink(1.5)
            self._periodic_beep(
                "last_extreme_heat_beep",
                Config.EXTREME_HEAT_BEEP_REPEAT_SECONDS,
                duration=0.08,
                count=1,
            )

        elif alert == "Bottle Empty":
            red = True
            self._periodic_beep(
                "last_empty_beep",
                Config.EMPTY_BEEP_REPEAT_SECONDS,
                duration=0.08,
                count=3,
            )

        elif alert == "Low Water":
            red = True

        elif alert == "Drink water reminder":
            yellow = self._blink(1.5)
            self._periodic_beep(
                "last_reminder_beep",
                Config.REMINDER_BEEP_REPEAT_SECONDS,
                duration=0.08,
                count=2,
            )

        elif alert in {
            "High temperature - daily goal increased",
            "Very hot - take small sips often",
        }:
            yellow = self._blink(1.5)
            self._periodic_beep(
                "last_high_temp_beep",
                Config.HIGH_TEMP_BEEP_REPEAT_SECONDS,
                duration=0.08,
                count=1,
            )

        elif alert == "Behind daily water goal":
            yellow = True

        GPIO.output(Config.YELLOW_LED, yellow)
        GPIO.output(Config.RED_LED, red)


# ================= CALIBRATION =================

class CalibrationManager:
    FILE = "calibration.json"

    def __init__(self, sensor):
        self.sensor = sensor
        self.raw_empty_dist = None
        self.distance_offset = 0.0
        self.empty_dist = Config.BOTTLE_HEIGHT
        self.is_calibrating = False
        self.points = []
        self.load()
        self.load_points()

    def load(self):
        if os.path.exists(self.FILE):
            try:
                with open(self.FILE, "r") as f:
                    data = json.load(f)

                self.raw_empty_dist = data.get("raw_empty_dist")
                self.distance_offset = data.get("distance_offset", 0.0)
                self.empty_dist = data.get("empty_dist", Config.BOTTLE_HEIGHT)

                print("Calibration loaded")
                print("Raw empty distance:", self.raw_empty_dist, "cm")
                print("Distance offset:", self.distance_offset, "cm")
                print("Corrected empty distance:", self.empty_dist, "cm")
            except Exception:
                print("Calibration load failed")

    def save(self):
        with open(self.FILE, "w") as f:
            json.dump(
                {
                    "raw_empty_dist": self.raw_empty_dist,
                    "distance_offset": self.distance_offset,
                    "empty_dist": self.empty_dist,
                },
                f,
            )

    def load_points(self):
        if os.path.exists(Config.CALIBRATION_POINTS_FILE):
            try:
                with open(Config.CALIBRATION_POINTS_FILE, "r") as f:
                    self.points = json.load(f)
            except Exception:
                self.points = []

    def save_points(self):
        with open(Config.CALIBRATION_POINTS_FILE, "w") as f:
            json.dump(self.points, f)

    def reset_points(self):
        self.points = [
            {
                "ml": 0.0,
                "raw_dist": self.raw_empty_dist,
                "corrected_dist": self.empty_dist,
            }
        ]
        self.save_points()

    def add_point(self, ml):
        if self.raw_empty_dist is None:
            return {"error": "Calibrate empty bottle first"}

        values = []
        print(f"Adding calibration point for {ml} ml - keep bottle stable")

        for i in range(25):
            raw = self.sensor.read_distance_raw_no_offset()
            print(f"[{i + 1}/25] raw point distance: {raw}")

            if raw is not None and Config.DIST_VALID_MIN < raw < Config.DIST_VALID_MAX:
                values.append(raw)

            time.sleep(0.1)

        if len(values) < 12:
            return {"error": f"Only {len(values)} valid reads - try again"}

        values.sort()
        trimmed = values[4:-4] if len(values) > 10 else values
        raw_avg = sum(trimmed) / len(trimmed)
        corrected = raw_avg - self.distance_offset

        if corrected < 0:
            corrected = 0.0

        point = {
            "ml": round(float(ml), 1),
            "raw_dist": round(raw_avg, 3),
            "corrected_dist": round(corrected, 3),
        }

        self.points = [p for p in self.points if float(p.get("ml", -1)) != float(ml)]
        self.points.append(point)
        self.points.sort(key=lambda p: float(p["corrected_dist"]), reverse=True)
        self.save_points()

        return {
            "status": "saved",
            "point": point,
            "points": self.points,
        }

    def ml_from_calibration_points(self, corrected_dist):
        if len(self.points) < 2:
            return None

        points = sorted(self.points, key=lambda p: float(p["corrected_dist"]), reverse=True)

        if corrected_dist >= float(points[0]["corrected_dist"]):
            return float(points[0]["ml"])

        if corrected_dist <= float(points[-1]["corrected_dist"]):
            return float(points[-1]["ml"])

        for i in range(len(points) - 1):
            high = points[i]
            low = points[i + 1]
            high_dist = float(high["corrected_dist"])
            low_dist = float(low["corrected_dist"])

            if high_dist >= corrected_dist >= low_dist:
                span = high_dist - low_dist
                if span <= 0:
                    return float(high["ml"])

                ratio = (high_dist - corrected_dist) / span
                return float(high["ml"]) + ratio * (float(low["ml"]) - float(high["ml"]))

        return None

    def calibrate_empty(self):
        self.is_calibrating = True

        try:
            values = []
            print("Starting calibration - keep bottle EMPTY and stable")

            for i in range(35):
                d = self.sensor.read_distance_raw_no_offset()
                print(f"[{i + 1}/35] raw empty distance: {d}")

                if d is not None and Config.DIST_VALID_MIN < d < Config.DIST_VALID_MAX:
                    values.append(d)

                time.sleep(0.12)

            if len(values) < 20:
                return {"error": f"Only {len(values)} valid reads - sensor unstable, try again"}

            values.sort()
            trimmed = values[5:-5] if len(values) > 12 else values
            raw_avg = sum(trimmed) / len(trimmed)

            if raw_avg < 1 or raw_avg > Config.DIST_VALID_MAX:
                return {"error": f"Invalid raw calibration distance: {raw_avg:.2f} cm"}

            self.raw_empty_dist = round(raw_avg, 3)
            self.distance_offset = round(self.raw_empty_dist - Config.BOTTLE_HEIGHT, 3)

            if self.distance_offset < 0:
                self.distance_offset = 0.0

            self.empty_dist = Config.BOTTLE_HEIGHT
            self.save()
            self.reset_points()

            self.sensor.reset_level_filters()

            print("Calibration complete")
            print("Raw empty distance:", self.raw_empty_dist, "cm")
            print("Distance offset:", self.distance_offset, "cm")
            print("Corrected empty distance:", self.empty_dist, "cm")

            return {
                "raw_empty_dist": self.raw_empty_dist,
                "distance_offset": self.distance_offset,
                "empty_dist": self.empty_dist,
                "bottle_height_cm": Config.BOTTLE_HEIGHT,
                "bottle_capacity_ml": Config.BOTTLE_CAPACITY,
                "max_capacity_ml": Config.BOTTLE_CAPACITY,
            }
        finally:
            self.is_calibrating = False


# ================= SENSOR =================

class SensorManager:
    def __init__(self):
        self.dht = adafruit_dht.DHT22(board.D4)

        self.bus = smbus2.SMBus(1)
        self.MPU = 0x68
        self.bus.write_byte_data(self.MPU, 0x6B, 0)

        i2c = busio.I2C(board.SCL, board.SDA)
        self.vl53 = adafruit_vl53l0x.VL53L0X(i2c)
        self.vl53.measurement_timing_budget = 50000
        print("VL53L0X initialized")

        self.calibration = None

        self.last_raw_dist = None
        self.last_valid_dist = None
        self.last_water_height = 0.0

        self.dist_buffer = deque(maxlen=Config.TOF_STABILITY_WINDOW)

        self.accepted_ml = 0.0
        self.accepted_percent = 0.0

        self.pending_ml = None
        self.pending_percent = None
        self.pending_count = 0

        self.base_pitch = 0.0
        self.base_roll = 0.0
        self.last_temp = None
        self.last_humidity = None
        self.last_dht_read = 0
        self.tof_valid_percent = 0.0
        self.mpu_stability = 100.0
        self.dht_status = "UNKNOWN"

        self._init_baseline()

    def reset_level_filters(self):
        self.dist_buffer.clear()
        self.accepted_ml = 0.0
        self.accepted_percent = 0.0
        self.pending_ml = None
        self.pending_percent = None
        self.pending_count = 0
        self.last_valid_dist = None
        self.last_raw_dist = None
        self.last_water_height = 0.0

    def _init_baseline(self):
        print("Calibrating MPU6050 baseline - keep bottle upright and still")

        pitches = []
        rolls = []

        for _ in range(40):
            ax, ay, az = self._get_accel_raw()
            pitch, roll = self._calc_angles(ax, ay, az)
            pitches.append(pitch)
            rolls.append(roll)
            time.sleep(0.03)

        pitches.sort()
        rolls.sort()

        self.base_pitch = sum(pitches[5:-5]) / len(pitches[5:-5])
        self.base_roll = sum(rolls[5:-5]) / len(rolls[5:-5])

        print(f"MPU baseline Pitch: {self.base_pitch:.2f} Roll: {self.base_roll:.2f}")

    def _read_word(self, addr):
        try:
            h = self.bus.read_byte_data(self.MPU, addr)
            l = self.bus.read_byte_data(self.MPU, addr + 1)
            val = (h << 8) + l
            return val - 65536 if val > 32768 else val
        except Exception:
            return 0

    def _get_accel_raw(self):
        return (
            self._read_word(0x3B) / 16384.0,
            self._read_word(0x3D) / 16384.0,
            self._read_word(0x3F) / 16384.0,
        )

    def _get_accel_filtered(self):
        xs = []
        ys = []
        zs = []

        for _ in range(Config.IMU_SAMPLES):
            ax, ay, az = self._get_accel_raw()
            xs.append(ax)
            ys.append(ay)
            zs.append(az)
            time.sleep(0.003)

        xs.sort()
        ys.sort()
        zs.sort()

        spread = (xs[-1] - xs[0]) + (ys[-1] - ys[0]) + (zs[-1] - zs[0])
        self.mpu_stability = round(max(0.0, min(100.0, 100.0 - (spread * 120.0))), 1)

        trim = 1 if len(xs) >= 5 else 0
        x_values = xs[trim:-trim] if trim else xs
        y_values = ys[trim:-trim] if trim else ys
        z_values = zs[trim:-trim] if trim else zs

        return (
            sum(x_values) / len(x_values),
            sum(y_values) / len(y_values),
            sum(z_values) / len(z_values),
        )

    @staticmethod
    def _calc_angles(ax, ay, az):
        pitch = math.degrees(math.atan2(ax, math.sqrt(ay ** 2 + az ** 2)))
        roll = math.degrees(math.atan2(ay, math.sqrt(ax ** 2 + az ** 2)))
        return pitch, roll

    def detect_drop_action(self, pitch, roll):
        if pitch > 20:
            return "FORWARD"
        elif pitch < -20:
            return "BACKWARD"
        elif pitch < -3 and roll > -80:
            return "RIGHT"
        elif roll > -70:
            return "LEFT"
        else:
            return "NORMAL"

    def read_motion(self):
        ax, ay, az = self._get_accel_filtered()
        pitch, roll = self._calc_angles(ax, ay, az)

        dpitch = pitch - self.base_pitch
        droll = roll - self.base_roll

        direction = self.detect_drop_action(dpitch, droll)

        is_upright = abs(dpitch) <= Config.UPRIGHT_LIMIT_DEG and abs(droll) <= Config.UPRIGHT_LIMIT_DEG
        is_tilted = direction != "NORMAL" and not is_upright

        return {
            "direction": direction,
            "display_direction": "STABLE" if direction == "NORMAL" else direction,
            "is_upright": is_upright,
            "is_tilted": is_tilted,
            "pitch": round(dpitch, 2),
            "roll": round(droll, 2),
            "tilt_strength": round(max(abs(dpitch), abs(droll)), 2),
        }

    def read_distance_raw_no_offset(self):
        try:
            mm = self.vl53.range
            raw_cm = mm / 10.0

            if Config.DIST_VALID_MIN < raw_cm < Config.DIST_VALID_MAX:
                return raw_cm
        except Exception:
            pass

        return None

    def corrected_from_raw(self, raw_cm):
        offset = 0.0

        if self.calibration:
            offset = self.calibration.distance_offset

        corrected_cm = raw_cm - offset

        if corrected_cm < 0:
            corrected_cm = 0.0

        return corrected_cm

    def read_distance_raw(self):
        raw_cm = self.read_distance_raw_no_offset()

        if raw_cm is None:
            return None

        corrected_cm = self.corrected_from_raw(raw_cm)
        self.last_raw_dist = raw_cm

        if Config.DEBUG_SENSOR:
            print(
                f"VL53L0X DEBUG | raw={raw_cm:.3f} cm | "
                f"offset={(self.calibration.distance_offset if self.calibration else 0):.3f} cm | "
                f"corrected={corrected_cm:.3f} cm"
            )

        return corrected_cm

    def read_distance(self):
        corrected_values = []

        for _ in range(Config.TOF_READS_PER_SAMPLE):
            d = self.read_distance_raw()

            if d is not None:
                corrected_values.append(d)

            time.sleep(0.004)

        if len(corrected_values) < Config.TOF_MIN_VALID_READS:
            self.tof_valid_percent = round((len(corrected_values) / Config.TOF_READS_PER_SAMPLE) * 100.0, 1)
            print(f"VL53L0X unstable ({len(corrected_values)}/{Config.TOF_READS_PER_SAMPLE} valid)")
            return None

        self.tof_valid_percent = round((len(corrected_values) / Config.TOF_READS_PER_SAMPLE) * 100.0, 1)

        corrected_values.sort()
        median = corrected_values[len(corrected_values) // 2]
        filtered = [
            d for d in corrected_values
            if abs(d - median) <= Config.TOF_RAW_OUTLIER_CM
        ]

        if len(filtered) < Config.TOF_MIN_VALID_READS:
            filtered = corrected_values[1:-1] if len(corrected_values) >= 8 else corrected_values

        filtered.sort()
        best_values = filtered[1:-1] if len(filtered) >= 6 else filtered
        avg = sum(best_values) / len(best_values)

        self.dist_buffer.append(avg)

        buf = sorted(self.dist_buffer)
        stable_index = max(0, int(len(buf) * 0.35))
        stable_dist = buf[stable_index]

        self.last_valid_dist = stable_dist

        if self.calibration:
            self.last_raw_dist = stable_dist + self.calibration.distance_offset

        return stable_dist

    def _dist_to_level(self, corrected_dist):
        if not self.calibration or not self.calibration.empty_dist:
            return 0.0, 0.0

        water_height = self.calibration.empty_dist - corrected_dist

        if water_height < 0:
            water_height = 0.0
        elif water_height > Config.BOTTLE_HEIGHT:
            water_height = Config.BOTTLE_HEIGHT

        calibrated_ml = self.calibration.ml_from_calibration_points(corrected_dist)

        if calibrated_ml is None:
            percent = (water_height / Config.BOTTLE_HEIGHT) * 100.0
            percent = max(0.0, min(100.0, percent))
            ml = (percent / 100.0) * Config.BOTTLE_CAPACITY
        else:
            ml = max(0.0, min(Config.BOTTLE_CAPACITY, calibrated_ml))
            percent = (ml / Config.BOTTLE_CAPACITY) * 100.0

        self.last_water_height = water_height

        if Config.DEBUG_SENSOR:
            print(
                f"LEVEL DEBUG | corrected_current={corrected_dist:.3f} cm | "
                f"empty_dist={self.calibration.empty_dist:.3f} cm | "
                f"water_height={water_height:.3f} cm | "
                f"percent={percent:.1f}% | "
                f"ml={ml:.1f} | "
                f"calibration_points={len(self.calibration.points)}"
            )

        return round(ml, 1), round(percent, 1)

    def _accept_level_if_stable(self, ml, percent):
        diff = abs(ml - self.accepted_ml)

        if diff < Config.LEVEL_DEAD_ZONE_ML:
            self.pending_ml = None
            self.pending_percent = None
            self.pending_count = 0
            return self.accepted_ml, self.accepted_percent

        if self.pending_ml is not None and abs(ml - self.pending_ml) < Config.LEVEL_DEAD_ZONE_ML:
            self.pending_count += 1
        else:
            self.pending_ml = ml
            self.pending_percent = percent
            self.pending_count = 1

        if self.pending_count >= Config.LEVEL_CONFIRM_COUNT:
            self.accepted_ml = self.pending_ml
            self.accepted_percent = self.pending_percent
            self.pending_ml = None
            self.pending_percent = None
            self.pending_count = 0

        return self.accepted_ml, self.accepted_percent

    def read_level_when_upright(self):
        if not self.calibration or not self.calibration.empty_dist:
            return self.accepted_ml, self.accepted_percent

        corrected_dist = self.read_distance()

        if corrected_dist is None:
            return self.accepted_ml, self.accepted_percent

        ml, percent = self._dist_to_level(corrected_dist)
        return self._accept_level_if_stable(ml, percent)

    def read_level_fast(self):
        if not self.calibration or not self.calibration.empty_dist:
            return self.accepted_ml, self.accepted_percent

        corrected_dist = self.read_distance()
        if corrected_dist is None:
            return self.accepted_ml, self.accepted_percent

        return self._dist_to_level(corrected_dist)

    def read_temperature_humidity(self):
        now = time.time()
        if now - self.last_dht_read < Config.TEMP_READ_INTERVAL_SECONDS:
            return self.last_temp, self.last_humidity

        try:
            temp = self.dht.temperature
            hum = self.dht.humidity
            self.last_temp = temp
            self.last_humidity = hum
            self.last_dht_read = now
            self.dht_status = "OK" if temp is not None or hum is not None else "NO_DATA"
        except Exception:
            self.dht_status = "ERROR"

        return self.last_temp, self.last_humidity

    def sensor_health_score(self):
        dht_score = 100.0 if self.dht_status == "OK" else 50.0 if self.dht_status == "UNKNOWN" else 0.0
        score = (self.tof_valid_percent * 0.5) + (self.mpu_stability * 0.35) + (dht_score * 0.15)
        return round(max(0.0, min(100.0, score)), 1)


# ================= NETWORK =================

class NetworkManager:
    def __init__(self):
        self.queue = queue.Queue()
        self.load_offline_payloads()

    def enqueue(self, payload):
        event = payload.get("event", "NORMAL")

        if event != "NORMAL":
            self._drop_queued_normal_payloads()

        if event == "NORMAL" and self.queue.qsize() > 3:
            return

        self.queue.put(payload)

    def _drop_queued_normal_payloads(self):
        kept = []

        while True:
            try:
                item = self.queue.get_nowait()
            except queue.Empty:
                break

            if item.get("event") != "NORMAL":
                kept.append(item)

        for item in kept:
            self.queue.put(item)

    def load_offline_payloads(self):
        if not os.path.exists(Config.OFFLINE_QUEUE_FILE):
            return

        try:
            with open(Config.OFFLINE_QUEUE_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    self.queue.put(json.loads(line))

            os.remove(Config.OFFLINE_QUEUE_FILE)
            print("Loaded offline payloads")
        except Exception as e:
            print("Offline payload load failed:", e)

    def save_offline_payload(self, payload):
        try:
            with open(Config.OFFLINE_QUEUE_FILE, "a") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as e:
            print("Offline payload save failed:", e)

    def persist_pending_payloads(self, extra_payload=None):
        try:
            with self.queue.mutex:
                pending = list(self.queue.queue)

            if extra_payload is not None:
                pending.insert(0, extra_payload)

            if not pending:
                if os.path.exists(Config.OFFLINE_QUEUE_FILE):
                    os.remove(Config.OFFLINE_QUEUE_FILE)
                return

            with open(Config.OFFLINE_QUEUE_FILE, "w") as f:
                for payload in pending:
                    f.write(json.dumps(payload) + "\n")
        except Exception as e:
            print("Offline payload persist failed:", e)

    def send(self, payload):
        try:
            headers = {}
            if Config.DEVICE_TOKEN:
                headers["X-Device-Token"] = Config.DEVICE_TOKEN

            res = requests.post(
                Config.SERVER,
                json=payload,
                headers=headers,
                timeout=Config.NETWORK_TIMEOUT_SECONDS,
            )
            print("Sent:", res.status_code)
            return 200 <= res.status_code < 300
        except Exception as e:
            print("Network error:", e)
            return False

    def send_heartbeat(self):
        try:
            headers = {}
            if Config.DEVICE_TOKEN:
                headers["X-Device-Token"] = Config.DEVICE_TOKEN

            payload = {
                "device_id": Config.DEVICE_ID,
                "status": "online",
                "sensor_health": bottle.sensor.sensor_health_score() if bottle else 0,
            }
            res = requests.post(
                f"{Config.API_BASE_URL}/heartbeat/",
                json=payload,
                headers=headers,
                timeout=Config.NETWORK_TIMEOUT_SECONDS,
            )
            return 200 <= res.status_code < 300
        except Exception:
            return False

    def worker(self):
        while True:
            data = self.queue.get()

            if data is None:
                break

            if self.send(data):
                self.persist_pending_payloads()
            else:
                self.persist_pending_payloads(data)
                self.queue.put(data)
                time.sleep(1)

    def heartbeat_worker(self):
        while True:
            self.send_heartbeat()
            time.sleep(Config.HEARTBEAT_INTERVAL_SECONDS)


# ================= MAIN =================

class SmartBottle:
    def __init__(self):
        self.gpio = GPIOManager()
        self.sensor = SensorManager()

        self.calibration = CalibrationManager(self.sensor)
        self.sensor.calibration = self.calibration

        self.network = NetworkManager()

        self.water_intake = 0.0
        self.total_filled = 0.0
        self.total_dropped = 0.0

        self.fill_count = 0
        self.drop_count = 0
        self.drink_count = 0

        self.confirmed_ml = 0.0
        self.confirmed_percent = 0.0
        self.level_initialized = False

        self.normal_change_candidate = None
        self.normal_change_count = 0
        self.normal_change_started_at = 0
        self.motion_block_until = 0
        self.last_unstable_reason = "STARTUP"

        self.tilt_count = 0
        self.stable_after_tilt_count = 0
        self.was_tilted = False
        self.pre_tilt_ml = 0.0
        self.tilt_direction = "NORMAL"
        self.tilt_started_at = 0
        self.tilt_ended_at = 0
        self.tilt_max_strength = 0.0

        self.drop_latch_until = 0
        self.drop_latch_direction = "NORMAL"
        self.last_event_amount = 0.0

        self.last_drink_time = time.time()
        self.last_state_save_time = 0
        self.last_normal_payload_time = 0
        self.current_day = time.strftime("%Y-%m-%d")
        self.load_state()

    def load_state(self):
        if not os.path.exists(Config.STATE_FILE):
            return

        try:
            with open(Config.STATE_FILE, "r") as f:
                data = json.load(f)

            if data.get("day") != self.current_day:
                return

            self.water_intake = float(data.get("water_intake", 0.0))
            self.total_filled = float(data.get("total_filled", 0.0))
            self.total_dropped = float(data.get("total_dropped", 0.0))
            self.fill_count = int(data.get("fill_count", 0))
            self.drop_count = int(data.get("drop_count", 0))
            self.drink_count = int(data.get("drink_count", 0))
            self.confirmed_ml = float(data.get("confirmed_ml", data.get("balance_ml", 0.0)))
            self.confirmed_percent = (self.confirmed_ml / Config.BOTTLE_CAPACITY) * 100.0
            self.confirmed_percent = max(0.0, min(100.0, self.confirmed_percent))
            self.sensor.accepted_ml = self.confirmed_ml
            self.sensor.accepted_percent = self.confirmed_percent
            self.level_initialized = True
            self.last_drink_time = float(data.get("last_drink_time", self.last_drink_time))
            print("Daily state loaded")
        except Exception as e:
            print("State load failed:", e)

    def save_state(self):
        try:
            with open(Config.STATE_FILE, "w") as f:
                json.dump(
                    {
                        "day": self.current_day,
                        "water_intake": self.water_intake,
                        "total_filled": self.total_filled,
                        "total_dropped": self.total_dropped,
                        "confirmed_ml": self.confirmed_ml,
                        "balance_ml": self.confirmed_ml,
                        "fill_count": self.fill_count,
                        "drop_count": self.drop_count,
                        "drink_count": self.drink_count,
                        "last_drink_time": self.last_drink_time,
                    },
                    f,
                )
        except Exception as e:
            print("State save failed:", e)

    def reset_daily_if_needed(self):
        today = time.strftime("%Y-%m-%d")

        if today == self.current_day:
            return

        current_hour = time.localtime().tm_hour
        if current_hour < Config.DAILY_RESET_HOUR:
            return

        self.current_day = today
        self.water_intake = 0.0
        self.total_filled = 0.0
        self.total_dropped = 0.0
        self.fill_count = 0
        self.drop_count = 0
        self.drink_count = 0
        self.last_drink_time = time.time()
        self.save_state()
        print("Daily counters reset")

    def reset_all_counters(self):
        self.water_intake = 0.0
        self.total_filled = 0.0
        self.total_dropped = 0.0
        self.fill_count = 0
        self.drop_count = 0
        self.drink_count = 0
        self.confirmed_ml = 0.0
        self.confirmed_percent = 0.0
        self.level_initialized = False
        self.normal_change_candidate = None
        self.normal_change_count = 0
        self.normal_change_started_at = 0
        self.motion_block_until = 0
        self.last_unstable_reason = "RESET"
        self.tilt_count = 0
        self.stable_after_tilt_count = 0
        self.was_tilted = False
        self.pre_tilt_ml = 0.0
        self.tilt_direction = "NORMAL"
        self.tilt_started_at = 0
        self.tilt_ended_at = 0
        self.tilt_max_strength = 0.0
        self.drop_latch_until = 0
        self.drop_latch_direction = "NORMAL"
        self.last_event_amount = 0.0
        self.last_drink_time = time.time()
        self.sensor.reset_level_filters()
        self.save_state()

    def factory_reset(self):
        for path in [
            Config.STATE_FILE,
            Config.OFFLINE_QUEUE_FILE,
            Config.CALIBRATION_POINTS_FILE,
            CalibrationManager.FILE,
        ]:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                print("Factory reset file cleanup failed:", path, e)

        self.calibration.raw_empty_dist = None
        self.calibration.distance_offset = 0.0
        self.calibration.empty_dist = Config.BOTTLE_HEIGHT
        self.calibration.points = []
        self.reset_all_counters()
        try:
            with self.network.queue.mutex:
                self.network.queue.queue.clear()
        except Exception:
            pass
        return {
            "status": "factory_reset",
            "device_id": Config.DEVICE_ID,
            "calibration_cleared": True,
            "state_cleared": True,
            "offline_queue_cleared": True,
        }

    def initialize_level_without_event(self, ml, percent):
        self.confirmed_ml = ml
        self.confirmed_percent = percent
        self.sensor.accepted_ml = ml
        self.sensor.accepted_percent = percent
        self.level_initialized = True
        self.save_state()
        print(f"Startup balance initialized: {ml:.1f} ml ({percent:.1f}%)")

    def reset_daily_history(self):
        current_balance = self.confirmed_ml
        current_percent = self.confirmed_percent

        self.water_intake = 0.0
        self.total_filled = 0.0
        self.total_dropped = 0.0
        self.fill_count = 0
        self.drop_count = 0
        self.drink_count = 0
        self.last_event_amount = 0.0
        self.last_drink_time = time.time()
        self.confirmed_ml = current_balance
        self.confirmed_percent = current_percent
        self.sensor.accepted_ml = current_balance
        self.sensor.accepted_percent = current_percent
        self.save_state()

    def get_dynamic_goal(self, temp):
        goal = Config.BASE_GOAL

        if temp is None:
            return goal

        if temp >= Config.EXTREME_TEMP_LIMIT:
            goal += Config.EXTREME_TEMP_EXTRA_GOAL
        elif temp >= Config.VERY_HOT_TEMP_LIMIT:
            goal += Config.VERY_HOT_TEMP_EXTRA_GOAL
        elif temp >= Config.HOT_TEMP_LIMIT:
            goal += Config.HOT_TEMP_EXTRA_GOAL
        elif temp >= Config.WARM_TEMP_LIMIT:
            goal += Config.WARM_TEMP_EXTRA_GOAL

        return goal

    def get_reminder_interval(self, temp):
        if temp is None:
            return Config.NORMAL_REMINDER_SECONDS

        if temp >= Config.EXTREME_TEMP_LIMIT:
            return Config.EXTREME_REMINDER_SECONDS
        elif temp >= Config.VERY_HOT_TEMP_LIMIT:
            return Config.VERY_HOT_REMINDER_SECONDS
        elif temp >= Config.HOT_TEMP_LIMIT:
            return Config.HOT_REMINDER_SECONDS
        elif temp >= Config.WARM_TEMP_LIMIT:
            return Config.WARM_REMINDER_SECONDS

        return Config.NORMAL_REMINDER_SECONDS

    def get_next_reminder_time(self, temp):
        return self.last_drink_time + self.get_reminder_interval(temp)

    def is_behind_goal(self, goal):
        now = time.localtime()
        current_hour = now.tm_hour + (now.tm_min / 60.0)

        if current_hour < Config.SCHOOL_DAY_START_HOUR:
            return False

        if current_hour > Config.SCHOOL_DAY_END_HOUR:
            current_hour = Config.SCHOOL_DAY_END_HOUR

        school_day_hours = Config.SCHOOL_DAY_END_HOUR - Config.SCHOOL_DAY_START_HOUR
        day_progress = (current_hour - Config.SCHOOL_DAY_START_HOUR) / school_day_hours
        expected_intake = goal * day_progress

        return self.water_intake + Config.BEHIND_GOAL_MARGIN_ML < expected_intake

    def _reset_normal_candidate(self):
        self.normal_change_candidate = None
        self.normal_change_count = 0
        self.normal_change_started_at = 0

    def save_state_if_needed(self, event):
        now = time.time()

        if event != "NORMAL" or now - self.last_state_save_time >= Config.STATE_SAVE_INTERVAL_SECONDS:
            self.save_state()
            self.last_state_save_time = now

    def _block_events(self, seconds, reason):
        self.motion_block_until = max(self.motion_block_until, time.time() + seconds)
        self.last_unstable_reason = reason
        self._reset_normal_candidate()

    def _events_blocked(self):
        return time.time() < self.motion_block_until

    def _commit_level(self, ml):
        self.confirmed_ml = max(0.0, min(Config.BOTTLE_CAPACITY, ml))
        self.sensor.accepted_ml = self.confirmed_ml
        self.sensor.accepted_percent = (self.confirmed_ml / Config.BOTTLE_CAPACITY) * 100.0

    def _process_normal_change(self, ml, allow_upright_decrease=False):
        diff = ml - self.confirmed_ml
        self.last_event_amount = 0.0

        if self._events_blocked():
            return "NORMAL"

        if abs(diff) < Config.EVENT_MIN_ML:
            self._reset_normal_candidate()
            return "NORMAL"

        sign = 1 if diff > 0 else -1

        if sign < 0 and not allow_upright_decrease:
            self._reset_normal_candidate()
            return "NORMAL"

        if (
            self.normal_change_candidate is not None
            and self.normal_change_candidate["sign"] == sign
            and abs(ml - self.normal_change_candidate["ml"]) < Config.LEVEL_DEAD_ZONE_ML
        ):
            self.normal_change_count += 1
        else:
            self.normal_change_candidate = {
                "ml": ml,
                "sign": sign,
            }
            self.normal_change_count = 1
            self.normal_change_started_at = time.time()

        if self.normal_change_count < Config.EVENT_CONFIRM_COUNT:
            return "NORMAL"

        if time.time() - self.normal_change_started_at < Config.LEVEL_SETTLE_SECONDS:
            return "NORMAL"

        final_ml = self.normal_change_candidate["ml"]
        final_diff = final_ml - self.confirmed_ml

        if abs(final_diff) > Config.MAX_AUTO_EVENT_ML:
            self._reset_normal_candidate()
            self._block_events(Config.EVENT_BLOCK_AFTER_SHAKE_SECONDS, "JUMP")
            return "NORMAL"

        self._commit_level(final_ml)
        self._reset_normal_candidate()

        if final_diff > 0:
            self.total_filled += final_diff
            self.fill_count += 1
            self.last_event_amount = abs(final_diff)
            return "FILL"

        removed_ml = abs(final_diff)

        if time.time() <= self.drop_latch_until:
            self.total_dropped += removed_ml
            self.drop_count += 1
            self.drop_latch_until = 0
            self.last_event_amount = removed_ml
            return "DROP"

        self.water_intake += removed_ml
        self.drink_count += 1
        self.last_drink_time = time.time()
        self.last_event_amount = removed_ml
        return "DRINK"

    def _start_tilt_if_confirmed(self, motion):
        if self.was_tilted and motion["is_tilted"]:
            self.tilt_max_strength = max(self.tilt_max_strength, motion["tilt_strength"])

            if motion["direction"] in {"LEFT", "RIGHT"}:
                self.tilt_direction = motion["direction"]

            return

        if motion["is_tilted"] and motion["direction"] != "NORMAL":
            self.tilt_count += 1
        else:
            self.tilt_count = 0

        if not self.was_tilted and self.tilt_count >= Config.TILT_CONFIRM_COUNT:
            self.was_tilted = True
            self.pre_tilt_ml = self.confirmed_ml
            self.tilt_direction = motion["direction"]
            self.tilt_started_at = time.time()
            self.tilt_ended_at = 0
            self.tilt_max_strength = motion["tilt_strength"]
            self.stable_after_tilt_count = 0
            self._reset_normal_candidate()

            self.drop_latch_until = time.time() + Config.DROP_LATCH_SECONDS
            self.drop_latch_direction = motion["direction"]

            print(
                f"Tilt started: {self.tilt_direction}, "
                f"pre_tilt_ml={self.pre_tilt_ml}"
            )

    def _finish_tilt_if_stable(self, motion, ml):
        self.last_event_amount = 0.0

        if not self.was_tilted:
            return "NORMAL"

        if self.sensor.mpu_stability < Config.SHAKING_MPU_STABILITY_LIMIT:
            self.stable_after_tilt_count = 0
            self.tilt_ended_at = 0
            return "NORMAL"

        if motion["is_upright"]:
            self.stable_after_tilt_count += 1
        else:
            self.stable_after_tilt_count = 0
            self.tilt_ended_at = 0

        if self.stable_after_tilt_count < Config.RETURN_STABLE_COUNT:
            return "NORMAL"

        if self.tilt_ended_at == 0:
            self.tilt_ended_at = time.time()

        if time.time() - self.tilt_ended_at < Config.EVENT_BLOCK_AFTER_TILT_SECONDS:
            return "NORMAL"

        diff = ml - self.pre_tilt_ml
        tilt_duration = time.time() - self.tilt_started_at if self.tilt_started_at else 0

        self.was_tilted = False
        self.tilt_count = 0
        self.stable_after_tilt_count = 0
        self.tilt_ended_at = 0
        self.tilt_max_strength = 0.0

        if abs(diff) < Config.EVENT_MIN_ML:
            return "NORMAL"

        if abs(diff) > Config.MAX_AUTO_EVENT_ML:
            self._block_events(Config.EVENT_BLOCK_AFTER_SHAKE_SECONDS, "TILT_JUMP")
            return "NORMAL"

        self._commit_level(ml)

        if diff > 0:
            self.total_filled += diff
            self.fill_count += 1
            self.last_event_amount = abs(diff)
            return "FILL"

        dropped_ml = abs(diff)

        if self.tilt_direction != "NORMAL":
            self.total_dropped += dropped_ml
            self.drop_count += 1
            self.drop_latch_until = 0
            self.last_event_amount = dropped_ml
            return "DROP"

        self.water_intake += dropped_ml
        self.drink_count += 1
        self.last_drink_time = time.time()
        self.last_event_amount = dropped_ml
        return "DRINK"

    def get_movement_state(self, motion):
        if self.sensor.mpu_stability < Config.SHAKING_MPU_STABILITY_LIMIT:
            return "SHAKING"

        if motion["is_tilted"]:
            if motion["tilt_strength"] >= Config.POURING_TILT_DEG:
                return "POURING"
            return "TILTED"

        if motion["is_upright"] and motion["tilt_strength"] > Config.UPRIGHT_LIMIT_DEG * 0.6:
            return "CARRIED"

        return "STABLE"

    def build_alert(self, percent, temp):
        if self.sensor.last_valid_dist is None:
            return "Check sensor"

        if not self.calibration.raw_empty_dist:
            return "Calibration Required"

        if percent < 3:
            return "Bottle Empty"

        if percent < 10:
            return "Low Water"

        if temp is not None and temp >= Config.EXTREME_TEMP_LIMIT:
            return "Extreme heat - drink water and move to shade"

        if temp is not None and temp >= Config.VERY_HOT_TEMP_LIMIT:
            return "Very hot - take small sips often"

        if temp is not None and temp >= Config.HOT_TEMP_LIMIT:
            return "High temperature - daily goal increased"

        goal = self.get_dynamic_goal(temp)
        reminder_interval = self.get_reminder_interval(temp)

        if time.time() - self.last_drink_time > reminder_interval:
            return "Drink water reminder"

        if self.is_behind_goal(goal):
            return "Behind daily water goal"

        return None

    def loop(self):
        while True:
            if self.calibration.is_calibrating:
                time.sleep(0.5)
                continue

            self.reset_daily_if_needed()

            motion = self.sensor.read_motion()
            movement_state = self.get_movement_state(motion)
            noisy_motion = movement_state in {"SHAKING", "CARRIED"}

            if noisy_motion and not self.was_tilted:
                self._block_events(Config.EVENT_BLOCK_AFTER_SHAKE_SECONDS, movement_state)

            if motion["direction"] != "NORMAL" and not motion["is_upright"]:
                self.drop_latch_until = time.time() + Config.DROP_LATCH_SECONDS
                self.drop_latch_direction = motion["direction"]

            temp, hum = self.sensor.read_temperature_humidity()

            event = "NORMAL"
            self.last_event_amount = 0.0

            self._start_tilt_if_confirmed(motion)

            if self.was_tilted and motion["is_upright"] and movement_state != "SHAKING":
                ml, percent = self.sensor.read_level_fast()
            elif noisy_motion or (self._events_blocked() and not self.was_tilted):
                ml = self.confirmed_ml
                percent = self.confirmed_percent
            elif motion["is_upright"]:
                ml, percent = self.sensor.read_level_when_upright()
            else:
                ml = self.confirmed_ml
                percent = self.confirmed_percent

            if self.was_tilted:
                event = self._finish_tilt_if_stable(motion, ml)
            elif (
                not self.level_initialized
                and motion["is_upright"]
                and not noisy_motion
                and not self._events_blocked()
            ):
                self.initialize_level_without_event(ml, percent)
                event = "NORMAL"
            elif motion["is_upright"]:
                event = self._process_normal_change(ml, allow_upright_decrease=True)
            else:
                event = "NORMAL"

            self.confirmed_percent = (self.confirmed_ml / Config.BOTTLE_CAPACITY) * 100.0
            self.confirmed_percent = max(0.0, min(100.0, self.confirmed_percent))

            goal = self.get_dynamic_goal(temp)
            alert = self.build_alert(self.confirmed_percent, temp)
            next_reminder_time = self.get_next_reminder_time(temp)
            drop_latch_active = event == "DROP" or time.time() <= self.drop_latch_until

            event_direction = self.drop_latch_direction if event == "DROP" else motion["display_direction"]
            sensor_health = self.sensor.sensor_health_score()

            payload = {
                "device_id": Config.DEVICE_ID,

                "water_ml": round(self.confirmed_ml, 1),
                "balance": round(self.confirmed_ml, 1),
                "balance_ml": round(self.confirmed_ml, 1),

                "water_intake": round(self.water_intake, 1),
                "goal": goal,
                "reminder_interval_seconds": self.get_reminder_interval(temp),
                "last_drink_time": round(self.last_drink_time, 3),
                "next_reminder_time": round(next_reminder_time, 3),
                "drop_latch_active": drop_latch_active,
                "drop_latch_direction": self.drop_latch_direction,
                "event_blocked": self._events_blocked(),
                "event_block_reason": self.last_unstable_reason,

                "temperature": temp,
                "humidity": hum,

                "bottle_level": round(self.confirmed_percent, 1),
                "percent": round(self.confirmed_percent, 1),

                "direction": event_direction,
                "movement_state": movement_state,
                "pitch": motion["pitch"],
                "roll": motion["roll"],

                "event": event,
                "event_amount": round(self.last_event_amount, 1),
                "alert": alert,

                "total_filled": round(self.total_filled, 1),
                "total_dropped": round(self.total_dropped, 1),

                "fill_count": self.fill_count,
                "drop_count": self.drop_count,
                "drink_count": self.drink_count,

                "raw_current_dist": round(self.sensor.last_raw_dist or 0, 3),
                "corrected_current_dist": round(self.sensor.last_valid_dist or 0, 3),
                "water_height": round(self.sensor.last_water_height, 3),
                "raw_empty_dist": self.calibration.raw_empty_dist,
                "distance_offset": self.calibration.distance_offset,
                "empty_dist": self.calibration.empty_dist,
                "calibration_points_count": len(self.calibration.points),
                "sensor_health": sensor_health,
                "tof_valid_percent": self.sensor.tof_valid_percent,
                "mpu_stability": self.sensor.mpu_stability,
                "dht_status": self.sensor.dht_status,
            }

            self.gpio.set_alert_outputs(alert, event, self.confirmed_percent)
            self.save_state_if_needed(event)

            now = time.time()
            if event != "NORMAL" or now - self.last_normal_payload_time >= Config.NORMAL_PAYLOAD_INTERVAL_SECONDS:
                print(payload)
                self.network.enqueue(payload)
                if event == "NORMAL":
                    self.last_normal_payload_time = now

            time.sleep(Config.SENSOR_DELAY)

    def start(self):
        threading.Thread(target=self.loop, daemon=True).start()
        threading.Thread(target=self.network.worker, daemon=True).start()
        threading.Thread(target=self.network.heartbeat_worker, daemon=True).start()


# ================= FLASK =================

app = Flask(__name__)
bottle = None


@app.route("/calibrate", methods=["POST"])
def calibrate_api():
    bottle.gpio.signal_calibration()
    result = bottle.calibration.calibrate_empty()

    if "error" not in result:
        bottle.reset_all_counters()

    return jsonify(result)


@app.route("/calibration", methods=["GET"])
def get_calibration():
    return jsonify({
        "raw_empty_dist": bottle.calibration.raw_empty_dist,
        "distance_offset": bottle.calibration.distance_offset,
        "empty_dist": bottle.calibration.empty_dist,
        "bottle_height_cm": Config.BOTTLE_HEIGHT,
        "bottle_capacity_ml": Config.BOTTLE_CAPACITY,
        "max_capacity_ml": Config.BOTTLE_CAPACITY,
        "calibration_points": bottle.calibration.points,
    })


@app.route("/calibration-points", methods=["GET"])
def get_calibration_points():
    return jsonify({
        "points": bottle.calibration.points,
    })


@app.route("/calibration-points", methods=["POST"])
def add_calibration_point():
    data = request.get_json(silent=True) or {}
    ml = data.get("ml")

    if ml is None:
        return jsonify({"error": "Provide ml value"}), 400

    try:
        ml = float(ml)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid ml value"}), 400

    return jsonify(bottle.calibration.add_point(ml))


@app.route("/status", methods=["GET"])
def status_api():
    motion = bottle.sensor.read_motion()
    temp, hum = bottle.sensor.read_temperature_humidity()
    next_reminder_time = bottle.get_next_reminder_time(temp)
    movement_state = bottle.get_movement_state(motion)

    return jsonify({
        "water_ml": round(bottle.confirmed_ml, 1),
        "balance": round(bottle.confirmed_ml, 1),
        "balance_ml": round(bottle.confirmed_ml, 1),

        "percent": round(bottle.confirmed_percent, 1),
        "bottle_level": round(bottle.confirmed_percent, 1),

        "direction": motion["display_direction"],
        "movement_state": movement_state,
        "pitch": motion["pitch"],
        "roll": motion["roll"],

        "temperature": temp,
        "humidity": hum,

        "water_intake": round(bottle.water_intake, 1),
        "goal": bottle.get_dynamic_goal(temp),
        "event_amount": round(bottle.last_event_amount, 1),
        "reminder_interval_seconds": bottle.get_reminder_interval(temp),
        "last_drink_time": round(bottle.last_drink_time, 3),
        "next_reminder_time": round(next_reminder_time, 3),
        "drop_latch_active": time.time() <= bottle.drop_latch_until,
        "drop_latch_direction": bottle.drop_latch_direction,

        "total_filled": round(bottle.total_filled, 1),
        "total_dropped": round(bottle.total_dropped, 1),

        "fill_count": bottle.fill_count,
        "drop_count": bottle.drop_count,
        "drink_count": bottle.drink_count,

        "raw_current_dist": round(bottle.sensor.last_raw_dist or 0, 3),
        "corrected_current_dist": round(bottle.sensor.last_valid_dist or 0, 3),
        "water_height": round(bottle.sensor.last_water_height, 3),
        "raw_empty_dist": bottle.calibration.raw_empty_dist,
        "distance_offset": bottle.calibration.distance_offset,
        "empty_dist": bottle.calibration.empty_dist,
        "calibration_points_count": len(bottle.calibration.points),
        "api_base_url": Config.API_BASE_URL,
        "device_id": Config.DEVICE_ID,
        "device_token_configured": bool(Config.DEVICE_TOKEN),
        "sensor_health": bottle.sensor.sensor_health_score(),
        "tof_valid_percent": bottle.sensor.tof_valid_percent,
        "mpu_stability": bottle.sensor.mpu_stability,
        "dht_status": bottle.sensor.dht_status,
    })


@app.route("/reset-daily", methods=["POST"])
def reset_daily_api():
    bottle.reset_daily_history()
    return jsonify({
        "status": "daily history reset",
        "water_ml": round(bottle.confirmed_ml, 1),
        "balance_ml": round(bottle.confirmed_ml, 1),
    })


@app.route("/factory-reset", methods=["POST"])
def factory_reset_api():
    return jsonify(bottle.factory_reset())


@app.route("/debug", methods=["GET"])
def debug_page():
    motion = bottle.sensor.read_motion()
    temp, hum = bottle.sensor.read_temperature_humidity()
    movement_state = bottle.get_movement_state(motion)

    rows = {
        "Device": Config.DEVICE_ID,
        "Balance": f"{bottle.confirmed_ml:.1f} ml",
        "Level": f"{bottle.confirmed_percent:.1f}%",
        "Movement": movement_state,
        "Direction": motion["display_direction"],
        "Pitch": motion["pitch"],
        "Roll": motion["roll"],
        "Sensor health": bottle.sensor.sensor_health_score(),
        "VL53L0X valid": f"{bottle.sensor.tof_valid_percent:.1f}%",
        "MPU stability": f"{bottle.sensor.mpu_stability:.1f}%",
        "DHT status": bottle.sensor.dht_status,
        "Temperature": temp,
        "Humidity": hum,
        "Raw distance": round(bottle.sensor.last_raw_dist or 0, 3),
        "Corrected distance": round(bottle.sensor.last_valid_dist or 0, 3),
        "Water height": round(bottle.sensor.last_water_height, 3),
        "Filled": f"{bottle.total_filled:.1f} ml",
        "Dropped": f"{bottle.total_dropped:.1f} ml",
        "Drink intake": f"{bottle.water_intake:.1f} ml",
    }

    table = "".join(f"<tr><th>{key}</th><td>{value}</td></tr>" for key, value in rows.items())
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta http-equiv="refresh" content="3" />
        <title>Smart Bottle Debug</title>
        <style>
          body {{ margin: 0; font-family: Arial, sans-serif; background: #f4f7fb; color: #0f172a; }}
          main {{ max-width: 720px; margin: 24px auto; background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 18px; }}
          h1 {{ margin-top: 0; }}
          table {{ width: 100%; border-collapse: collapse; }}
          th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #e5e7eb; }}
          th {{ width: 45%; color: #475569; }}
          .actions {{ display: flex; gap: 10px; margin-top: 16px; }}
          button {{ padding: 10px 12px; border: 0; border-radius: 8px; background: #2563eb; color: #fff; font-weight: 700; }}
        </style>
      </head>
      <body>
        <main>
          <h1>Smart Bottle Debug</h1>
          <table>{table}</table>
          <div class="actions">
            <form method="post" action="/reset-daily">
              <button type="submit">Reset Daily History</button>
            </form>
          </div>
        </main>
      </body>
    </html>
    """


@app.route("/deployment", methods=["GET"])
def deployment_api():
    return jsonify({
        "device_id": Config.DEVICE_ID,
        "api_base_url": Config.API_BASE_URL,
        "server_url": Config.SERVER,
        "device_token_configured": bool(Config.DEVICE_TOKEN),
        "offline_queue_file": Config.OFFLINE_QUEUE_FILE,
        "state_file": Config.STATE_FILE,
    })


@app.route("/pairing", methods=["GET"])
def pairing_page():
    pairing_url = f"{Config.API_BASE_URL}/devices/{Config.DEVICE_ID}/pairing/"
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Smart Bottle Pairing</title>
        <style>
          body {{
            margin: 0;
            font-family: Arial, sans-serif;
            background: #f4f7fb;
            color: #0f172a;
          }}
          .card {{
            max-width: 520px;
            margin: 32px auto;
            background: #fff;
            border: 1px solid #e5e7eb;
            border-radius: 10px;
            padding: 22px;
          }}
          .pill {{
            display: inline-block;
            background: #dbeafe;
            color: #1d4ed8;
            padding: 6px 10px;
            border-radius: 999px;
            font-weight: 700;
          }}
          code {{
            display: block;
            margin-top: 8px;
            padding: 12px;
            border-radius: 8px;
            background: #f8fafc;
            word-break: break-all;
          }}
        </style>
      </head>
      <body>
        <main class="card">
          <span class="pill">Smart Bottle Pairing</span>
          <h1>{Config.DEVICE_ID}</h1>
          <p>Open the React admin dashboard to display the scannable QR code.</p>
          <p>Backend pairing endpoint:</p>
          <code>{pairing_url}</code>
          <p>API base URL:</p>
          <code>{Config.API_BASE_URL}</code>
        </main>
      </body>
    </html>
    """


def run_flask():
    app.run(host="0.0.0.0", port=5001)


# ================= RUN =================

if __name__ == "__main__":
    bottle = SmartBottle()

    bottle.start()
    threading.Thread(target=run_flask, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bottle.gpio.cleanup()
