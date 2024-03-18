"""Various ways of getting live departures from some web service"""
import datetime

from django.conf import settings
from django.utils import timezone

from busstops.models import Service, SIRISource, StopPoint
from bustimes.models import Route
from bustimes.utils import get_stop_times
from vehicles import rtpi
from vehicles.tasks import log_vehicle_journey

from . import avl, gtfsr
from .sources import (
    AcisHorizonDepartures,
    EdinburghDepartures,
    SiriSmDepartures,
    TflDepartures,
    TimetableDepartures,
    WestMidlandsDepartures,
    get_departure_order,
)


def services_match(a, b):
    if type(a) is Service:
        a = a.line_name
    if type(b) is Service:
        b = b.line_name
    return a.lower() == b.lower()


def can_sort(departure):
    return (
        type(departure["time"]) is datetime.datetime
        or type(departure.get("live")) is datetime.datetime
    )


def rows_match(a, b):
    if services_match(a["service"], b["service"]):
        if a["time"] and b["time"]:
            if a.get("arrival") and b.get("arrival"):
                key = "arrival"
            else:
                key = "time"
            return abs(a[key] - b[key]) <= datetime.timedelta(minutes=2)


def blend(departures, live_rows, stop=None):
    added = False
    for live_row in live_rows:
        replaced = False
        for row in departures:
            if rows_match(row, live_row):
                if live_row.get("live"):
                    row["live"] = live_row["live"]
                if "data" in live_row:
                    row["data"] = live_row["data"]
                if "cancelled" in live_row:
                    row["cancelled"] = live_row["cancelled"]
                if "vehicle" in live_row and not row.get("vehicle"):
                    row["vehicle"] = live_row["vehicle"]
                replaced = True
                break
        if not replaced and (live_row.get("live") or live_row["time"]):
            departures.append(live_row)
            added = True
    if added and all(can_sort(departure) for departure in departures):
        departures.sort(key=get_departure_order)


def update_trip_ids(departures: list, live_rows: list) -> None:
    for live_row in live_rows:
        if live_row["time"]:
            for row in departures:
                if (
                    row["time"] == live_row["time"]
                    and row["service"] == live_row["service"]
                ):
                    live_row["link"] = row["link"]
                    trip = row["stop_time"].trip
                    if trip.ticket_machine_code != live_row["tripId"]:
                        trip.ticket_machine_code = live_row["tripId"]
                        trip.save(update_fields=["ticket_machine_code"])


def get_departures(stop, services, when) -> dict:
    live_departures = None

    # Transport for London
    if not when and type(stop) is StopPoint:
        tfl_services = [s for s in services if s.service_code[:4] == "tfl_"]
        if tfl_services:
            live_departures = TflDepartures(stop, tfl_services).get_departures()
            services = [s for s in services if s.service_code[:4] != "tfl_"]
            if not services:
                return {
                    "departures": live_departures,
                    "today": timezone.localdate(),
                }

    now = timezone.localtime()

    routes_by_service = {}
    routes = Route.objects.filter(
        service__in=[s for s in services if not s.timetable_wrong]
    ).select_related("source")

    for route in routes:
        if route.service_id in routes_by_service:
            routes_by_service[route.service_id].append(route)
        else:
            routes_by_service[route.service_id] = [route]

    departures = None

    if not when and live_departures is None:
        vehicle_locations = avl.get_tracking(stop, services)
        if vehicle_locations:
            by_trip = {
                item["trip_id"]: item for item in vehicle_locations if "trip_id" in item
            }
            if by_trip:
                departures = TimetableDepartures(
                    stop, services, now, routes_by_service, by_trip
                ).get_departures()

                for departure in departures:
                    trip_id = departure["stop_time"].trip_id
                    if "vehicle" in departure and trip_id not in by_trip:
                        departure["vehicle"] = None
                    elif trip_id in by_trip and stop.pk[:4] == "2900":
                        rtpi.add_progress_and_delay(by_trip[trip_id])
                        if "delay" in by_trip[trip_id]:
                            delay = by_trip[trip_id]["delay"]
                            if (
                                delay < 0
                                and by_trip[trip_id]["progress"]["sequence"] == 0
                            ):
                                delay = 0
                            departure["live"] = departure["time"] + datetime.timedelta(
                                seconds=delay
                            )
                        departures = [
                            dep
                            for dep in departures
                            if "live" not in dep
                            or dep["live"] >= now
                            or dep["time"] >= now
                        ]

    if departures is None:
        departures = TimetableDepartures(
            stop, services, when or now, routes_by_service
        ).get_departures()

    if live_departures:
        departures = live_departures + departures

    one_hour = datetime.timedelta(hours=1)
    one_hour_ago = now - one_hour

    if departures and any(
        route.source.name == "Realtime Transport Operators" for route in routes
    ):
        gtfsr.update_stop_departures(departures)

    if when or live_departures or type(stop) is not StopPoint:
        pass
    elif not departures or (
        (departures[0]["time"] - now) < one_hour
        or get_stop_times(
            one_hour_ago.date(),
            datetime.timedelta(hours=one_hour_ago.hour, minutes=one_hour_ago.minute),
            stop,
            routes_by_service,
        ).exists()
    ):
        live_rows = None

        operators = set()
        for service in services:
            if service.operators:
                operators.update(service.operators)

        # Belfast
        if stop.atco_code[0] == "7" and not operators.isdisjoint(
            {
                "Ulsterbus",
                "Ulsterbus Town Services",
                "Translink Metro",
                "Translink Glider",
            }
        ):
            live_rows = AcisHorizonDepartures(stop, services).get_departures()
            if live_rows:
                blend(departures, live_rows)

        # West Midlands
        elif not operators.isdisjoint(settings.TFWM_OPERATORS):
            live_rows = WestMidlandsDepartures(stop, services).get_departures()
            if live_rows:
                blend(departures, live_rows)

        elif departures:
            # Edinburgh
            if stop.naptan_code and (
                "Lothian Buses" in operators
                or "Lothian Country Buses" in operators
                or "East Coast Buses" in operators
                or "Edinburgh Trams" in operators
            ):
                live_rows = EdinburghDepartures(stop, services, now).get_departures()
                if live_rows:
                    update_trip_ids(departures, live_rows)

                    departures = live_rows
                    live_rows = None

            source = None

            # Aberdeen, Glasgow, Bristol?
            if stop.admin_area_id:
                for possible_source in SIRISource.objects.filter(
                    admin_areas=stop.admin_area_id
                ):
                    if not possible_source.is_poorly():
                        source = possible_source
                        break

            if source:
                live_rows = SiriSmDepartures(source, stop, services).get_departures()

            if live_rows:
                blend(departures, live_rows)

                if source and source.name in ("Aberdeen", "Pembrokeshire", "SPT"):
                    # Record some information about the vehicle and journey,
                    # for enthusiasts,
                    # because the source doesn't support vehicle locations
                    for row in departures:
                        if "data" in row and "VehicleRef" in row["data"]:
                            log_vehicle_journey(
                                row["service"].pk
                                if type(row["service"]) is Service
                                else None,
                                row["data"],
                                str(row["origin_departure_time"])
                                if "origin_departure_time" in row
                                else None,
                                str(row["destination"]),
                                source.name,
                                source.url,
                                row["stop_time"].trip_id
                                if "stop_time" in row
                                else None,
                            )

    return {
        "departures": departures,
        "today": now.date(),
        "now": now,
        "when": when or now,
    }
