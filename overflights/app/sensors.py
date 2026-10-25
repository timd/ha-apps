"""Home Assistant sensors over MQTT, set up by MQTT discovery."""

import asyncio
import json
import logging
import os
import time

import aiohttp
import aiomqtt

import demo
import store
from classify import COLUMNS, JOINS

log = logging.getLogger("sensors")

BASE = "overflights"
AVAILABILITY = f"{BASE}/status"
DEVICE = {"identifiers": ["overflights"], "name": "Overflights", "model": "Overflights App"}
PUBLISH_EVERY_S = 5
RECEIVER_STALE_S = 120


def discovery():
    """Return (topic, payload) for each entity's discovery message."""
    common = {"device": DEVICE, "availability_topic": AVAILABILITY}
    return [
        ("homeassistant/sensor/overflights/today/config", {
            **common,
            "name": "Today",
            "unique_id": "overflights_today",
            "state_topic": f"{BASE}/today/state",
            "state_class": "total_increasing",
            "unit_of_measurement": "overflights",
            "icon": "mdi:airplane",
        }),
        ("homeassistant/sensor/overflights/last/config", {
            **common,
            "name": "Last",
            "unique_id": "overflights_last",
            "state_topic": f"{BASE}/last/state",
            "json_attributes_topic": f"{BASE}/last/attributes",
            "icon": "mdi:airplane-marker",
        }),
        ("homeassistant/sensor/overflights/overhead/config", {
            **common,
            "name": "Overhead",
            "unique_id": "overflights_overhead",
            "state_topic": f"{BASE}/overhead/state",
            "json_attributes_topic": f"{BASE}/overhead/attributes",
            "state_class": "measurement",
            "unit_of_measurement": "aircraft",
            "icon": "mdi:airplane-clock",
        }),
        ("homeassistant/binary_sensor/overflights/receiver/config", {
            **common,
            "name": "Receiver",
            "unique_id": "overflights_receiver",
            "state_topic": f"{BASE}/receiver/state",
            "device_class": "connectivity",
            "entity_category": "diagnostic",
        }),
    ]


async def broker_settings():
    """Ask the Supervisor for the MQTT broker that Home Assistant uses."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
        async with s.get("http://supervisor/services/mqtt",
                         headers={"Authorization": f"Bearer {token}"}) as resp:
            if resp.status != 200:
                log.warning("No MQTT service from the Supervisor (HTTP %d)", resp.status)
                return None
            return (await resp.json())["data"]


class Sensors:
    def __init__(self, db_path, collector, classify, radius_m, max_alt_ft, overhead):
        """`overhead` returns the aircraft overhead now, nearest first."""
        self.db_path = db_path
        self.overhead = overhead
        self.classify = classify
        self.collector = collector
        self.radius_m = radius_m
        self.max_alt_ft = max_alt_ft or None

    def read(self):
        """Return {topic: payload} for the current state. Demo passes never count."""
        lt = time.localtime()
        midnight = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))
        where = "p.min_dist_m <= :r AND p.hex NOT LIKE :demo"
        if self.max_alt_ft:
            where += " AND p.min_alt_ft <= :alt"
        args = {"r": self.radius_m, "alt": self.max_alt_ft, "demo": demo.DEMO_PREFIX + "%",
                "midnight": midnight}
        db = store.connect(self.db_path)
        try:
            today = db.execute(f"SELECT count(*) FROM passes p WHERE p.min_ts >= :midnight AND {where}",
                               args).fetchone()[0]
            last = db.execute(f"""SELECT p.hex, p.flight, p.min_ts, p.min_dist_m, p.min_alt_ft, {COLUMNS}
                                  FROM passes p {JOINS}
                                  WHERE {where} ORDER BY p.min_ts DESC LIMIT 1""", args).fetchone()
        finally:
            db.close()

        ok = self.collector.last_ok and time.time() - self.collector.last_ok < RECEIVER_STALE_S
        states = {
            f"{BASE}/today/state": str(today),
            f"{BASE}/receiver/state": "ON" if ok else "OFF",
        }
        if last:
            hex_, flight, ts, dist, alt = last[:5]
            states[f"{BASE}/last/state"] = flight or hex_.upper()
            states[f"{BASE}/last/attributes"] = json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts)),
                "distance_km": round(dist / 1000, 2),
                "altitude_ft": alt,
                "hex": hex_,
                "callsign": flight,
                "kind": self.classify(*last[5:]),
            })
        return states

    def read_overhead(self):
        """The number of aircraft overhead, with the nearest one's details.

        Altitude and speed are rounded, so noise in them publishes nothing.
        """
        now = self.overhead()
        attrs = {"aircraft": [a["callsign"] or a["hex"].upper() for a in now]}
        if now:
            a = now[0]
            o, d = a.get("origin"), a.get("destination")
            attrs.update({
                "callsign": a["callsign"],
                "hex": a["hex"],
                "registration": a.get("registration"),
                "type": a.get("type"),
                "icao_type": a.get("icao_type"),
                "operator": a.get("airline") or a.get("owner"),
                "origin": o and o["code"],
                "origin_name": o and (o["city"] or o["name"]),
                "destination": d and d["code"],
                "destination_name": d and (d["city"] or d["name"]),
                "route_plausible": a.get("route_plausible"),
                "altitude_ft": a["altitude_ft"] if a["altitude_ft"] is None else round(a["altitude_ft"], -2),
                "distance_km": round(a["distance_m"] / 1000, 1),
                "speed_kt": a["speed_kt"] if a["speed_kt"] is None else round(a["speed_kt"], -1),
                "photo": a.get("photo"),
            })
        return {f"{BASE}/overhead/state": str(len(now)),
                f"{BASE}/overhead/attributes": json.dumps(attrs)}

    async def run(self):
        settings = await broker_settings()
        if not settings:
            log.info("MQTT is not available, so there are no sensors")
            return
        published = {}
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=settings["host"], port=int(settings["port"]),
                    username=settings.get("username"), password=settings.get("password"),
                    identifier="overflights",
                    will=aiomqtt.Will(AVAILABILITY, "offline", retain=True),
                ) as client:
                    for topic, payload in discovery():
                        await client.publish(topic, json.dumps(payload), retain=True)
                    await client.publish(AVAILABILITY, "online", retain=True)
                    log.info("Publishing sensors to MQTT at %s:%s", settings["host"], settings["port"])
                    published.clear()
                    while True:
                        # read_overhead() runs here, not in a thread, because
                        # its lookups use the event loop and the App's database.
                        states = {**await asyncio.to_thread(self.read), **self.read_overhead()}
                        for topic, payload in states.items():
                            if published.get(topic) != payload:
                                await client.publish(topic, payload, retain=True)
                                published[topic] = payload
                        await asyncio.sleep(PUBLISH_EVERY_S)
            except aiomqtt.MqttError as err:
                log.warning("MQTT error: %s. Retrying in 30 s", err)
                await asyncio.sleep(30)
