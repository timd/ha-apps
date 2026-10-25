# Overflights

Overflights logs the aircraft that your ADS-B receiver sees pass over the
house, and charts when and where they fly. It sorts them into arrivals,
departures and transits, draws their paths on a map, and adds sensors to Home
Assistant.

![The Overflights page](https://raw.githubusercontent.com/timd/ha-apps/main/docs/screenshot.png)

## What you need

- Home Assistant OS, or a Supervised installation, on amd64 or aarch64 (for
  example a Raspberry Pi 4 or 5).
- An ADS-B receiver on your network that runs PiAware (SkyAware), tar1090,
  readsb or ultrafeeder. Home Assistant must be able to open its
  `aircraft.json`.
- Optional: an MQTT broker, such as the Mosquitto app, for the sensors.

## Install

1. In Home Assistant, open **Settings → Apps → App store**.
2. Open the menu (⋮) at the top right and choose **Repositories**.
3. Add `https://github.com/timd/ha-apps` and close the dialog.
4. Find **Overflights** in the store, open it, and select **Install**.

## Set up

All settings are on the App's **Configuration** tab.

1. **Receiver data URL**: the folder on your receiver that holds
   `aircraft.json`. Open the URL in a browser and add `/aircraft.json` to
   check it.

   | Receiver | URL |
   | --- | --- |
   | PiAware (SkyAware) | `http://<receiver>/skyaware/data` |
   | tar1090, ultrafeeder | `http://<receiver>/tar1090/data` |

2. **Airport** (optional): the ICAO or IATA code of the main airport near the
   house, for example `EDDB` or `BER`. The App then finds arrivals and
   departures for that airport, and traces them to its runways on the map.
3. **Overhead radius** and **Overhead altitude limit**: what counts as
   overhead for the sensors and the Overhead now card, and the page's
   starting filters. You can leave
   them at first and set them after a week, from the "How close they come"
   chart.
4. Select **Save**, then go to the **Info** tab and select **Start**. Check
   that **Show in sidebar** is on.

The App reads the house position from the receiver. To use another position,
set **Latitude** and **Longitude**.

## First use

Open **Overflights** in the sidebar. The page fills as aircraft pass: the map
and table straight away, the charts over the following days. To judge the page
before you have history, turn on **Demo data**. Turn it off again to delete
the demo passes.

If the page says the receiver is not reachable, check the URL in the App log
(**Log** tab).

The **Documentation** tab explains how passes are classified, every option,
and the sensors.
