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

log = logging.getLogger("sensors")

BASE = "overflights"
AVAILABILITY = f"{BASE}/status"
DEVICE = {"identifiers": ["overflights"], "name": "Overflights", "model": "Overflights App"}
PUBLISH_EVERY_S = 15
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
    def __init__(self, db_path, collector, radius_m, max_alt_ft):
        self.db_path = db_path
        self.collector = collector
        self.radius_m = radius_m
        self.max_alt_ft = max_alt_ft or None

    def read(self):
        """Return {topic: payload} for the current state. Demo passes never count."""
        lt = time.localtime()
        midnight = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))
        where = "min_dist_m <= :r AND hex NOT LIKE :demo"
        if self.max_alt_ft:
            where += " AND min_alt_ft <= :alt"
        args = {"r": self.radius_m, "alt": self.max_alt_ft, "demo": demo.DEMO_PREFIX + "%",
                "midnight": midnight}
        db = store.connect(self.db_path)
        try:
            today = db.execute(f"SELECT count(*) FROM passes WHERE min_ts >= :midnight AND {where}",
                               args).fetchone()[0]
            last = db.execute(f"""SELECT hex, flight, min_ts, min_dist_m, min_alt_ft FROM passes
                                  WHERE {where} ORDER BY min_ts DESC LIMIT 1""", args).fetchone()
        finally:
            db.close()

        ok = self.collector.last_ok and time.time() - self.collector.last_ok < RECEIVER_STALE_S
        states = {
            f"{BASE}/today/state": str(today),
            f"{BASE}/receiver/state": "ON" if ok else "OFF",
        }
        if last:
            hex_, flight, ts, dist, alt = last
            states[f"{BASE}/last/state"] = flight or hex_.upper()
            states[f"{BASE}/last/attributes"] = json.dumps({
                "time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts)),
                "distance_km": round(dist / 1000, 2),
                "altitude_ft": alt,
                "hex": hex_,
                "callsign": flight,
            })
        return states

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
                        for topic, payload in (await asyncio.to_thread(self.read)).items():
                            if published.get(topic) != payload:
                                await client.publish(topic, payload, retain=True)
                                published[topic] = payload
                        await asyncio.sleep(PUBLISH_EVERY_S)
            except aiomqtt.MqttError as err:
                log.warning("MQTT error: %s. Retrying in 30 s", err)
                await asyncio.sleep(30)
