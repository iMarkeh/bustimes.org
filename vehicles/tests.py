from unittest.mock import patch

import fakeredis
import time_machine
from ciso8601 import parse_datetime
from django.contrib.gis.geos import Point
from django.db.transaction import TransactionManagementError
from django.test import TestCase, override_settings

from accounts.models import User
from busstops.models import DataSource, Operator, Region, Service

from .models import (
    Livery,
    SiriSubscription,
    Vehicle,
    VehicleEdit,
    VehicleEditFeature,
    VehicleFeature,
    VehicleJourney,
    VehicleLocation,
    VehicleRevision,
    VehicleType,
)


@patch(
    "vehicles.views.redis_client",
    fakeredis.FakeStrictRedis(),
)
class VehiclesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.datetime = "2020-10-19 23:47+00:00"

        source = DataSource.objects.create(name="HP", datetime=cls.datetime)

        ea = Region.objects.create(id="EA", name="East Anglia")

        cls.wifi = VehicleFeature.objects.create(name="Wi-Fi")
        cls.usb = VehicleFeature.objects.create(name="USB")

        cls.bova = Operator.objects.create(
            region=ea,
            name="Bova and Over",
            noc="BOVA",
            slug="bova-and-over",
            parent="Madrigal Electromotive",
        )
        cls.lynx = Operator.objects.create(
            region=ea,
            name="Lynx",
            noc="LYNX",
            slug="lynx",
            parent="Madrigal Electromotive",
        )
        cls.chicken = Operator.objects.create(
            region=ea, name="Chicken Bus", noc="CLUCK", slug="chicken"
        )

        tempo = VehicleType.objects.create(name="Optare Tempo", fuel="diesel")
        spectra = VehicleType.objects.create(
            name="Optare Spectra",
            fuel="diesel",
            style="double decker",
        )

        service = Service.objects.create(
            service_code="49",
            region=ea,
            tracking=True,
            description="Spixworth - Hunworth - Happisburgh",
        )
        service.operator.add(cls.lynx)
        service.operator.add(cls.bova)

        cls.vehicle_1 = Vehicle.objects.create(
            code="2",
            fleet_number=1,
            reg="FD54JYA",
            vehicle_type=tempo,
            colours="#FF0000",
            notes="Trent Barton",
            operator=cls.lynx,
            branding="",
        )
        cls.livery = Livery.objects.create(
            name="black with lemon piping", colours="#FF0000 #0000FF", published=True
        )
        cls.vehicle_2 = Vehicle.objects.create(
            code="50",
            fleet_number=50,
            reg="UWW2X",
            livery=cls.livery,
            vehicle_type=spectra,
            operator=cls.lynx,
        )

        cls.vehicle_3 = Vehicle.objects.create(
            code="10", branding="Coastliner", colours="#c0c0c0"
        )

        cls.journey = VehicleJourney.objects.create(
            vehicle=cls.vehicle_1,
            datetime=cls.datetime,
            source=source,
            service=service,
            route_name="2",
        )
        VehicleJourney.objects.create(
            vehicle=cls.vehicle_1,
            datetime="2020-10-16 12:00:00+00:00",
            source=source,
            service=service,
            route_name="2",
        )
        VehicleJourney.objects.create(
            vehicle=cls.vehicle_1,
            datetime="2020-10-20 12:00:00+00:00",
            source=source,
            service=service,
            route_name="2",
        )

        cls.vehicle_1.latest_journey = cls.journey
        cls.vehicle_1.save()

        cls.vehicle_1.features.set([cls.wifi])

        cls.staff_user = User.objects.create(
            username="josh",
            is_staff=True,
            is_superuser=True,
            email="j@example.com",
            date_joined="2020-10-19 23:47+00:00",
        )
        cls.trusted_user = User.objects.create(
            username="norma", trusted=True, email="n@example.com"
        )
        cls.user = User.objects.create(
            username="ken",
            trusted=None,
            email="ken@example.com",
            date_joined="2020-10-19 23:47+00:00",
        )
        cls.untrusted_user = User.objects.create(
            username="clem", trusted=False, email="c@example.com"
        )

    def test_untrusted_user(self):
        self.client.force_login(self.untrusted_user)

        with self.assertNumQueries(2):
            response = self.client.get(self.vehicle_1.get_edit_url())
        self.assertEqual(response.status_code, 403)

        with self.assertNumQueries(3):
            response = self.client.get("/operators/lynx/vehicles/edit")
        self.assertEqual(response.status_code, 403)

    def test_parent(self):
        with self.assertNumQueries(3):
            response = self.client.get("/groups/Madrigal Electromotive/vehicles")
        self.assertContains(response, "Lynx")
        self.assertContains(response, "Madrigal Electromotive")
        self.assertContains(response, "Optare")

        with self.assertNumQueries(1):
            response = self.client.get("/groups/Shatton Group/vehicles")
        self.assertEqual(404, response.status_code)

    def test_fleet_lists(self):
        # operator has no vehicles
        with self.assertNumQueries(2):
            response = self.client.get("/operators/bova-and-over/vehicles")
        self.assertEqual(404, response.status_code)
        self.assertFalse(str(response.context["exception"]))

        # operator doesn't exist
        with self.assertNumQueries(2):
            response = self.client.get("/operators/shatton-east/vehicles")
        self.assertEqual(404, response.status_code)

        # last seen today - should only show time, should link to map
        with time_machine.travel("2020-10-20 12:00+01:00"):
            with self.assertNumQueries(3):
                response = self.client.get("/operators/lynx/vehicles")
        self.assertNotContains(response, "20 Oct")
        self.assertContains(response, "00:47")
        self.assertContains(response, "/operators/lynx/map")
        self.assertContains(response, "/vehicles/history?vehicle__operator=LYNX")
        self.assertContains(response, "/vehicles/edits?vehicle__operator=LYNX")
        self.assertContains(response, "/operators/lynx/map")

        with self.assertNumQueries(6):
            response = self.client.get("/operators/lynx")
        self.assertContains(response, "/operators/lynx/vehicles")
        self.assertNotContains(response, "/operators/lynx/map")

        # last seen yesterday - should show date
        with time_machine.travel("2020-10-21 00:10+01:00"):
            with self.assertNumQueries(3):
                response = self.client.get("/operators/lynx/vehicles")
        self.assertContains(response, "20 Oct 00:47")
        self.assertNotContains(response, "/operators/lynx/map")

    def test_vehicle_views(self):
        with self.assertNumQueries(8):
            response = self.client.get(self.vehicle_1.get_absolute_url() + "?date=poop")
        self.assertContains(response, "Optare Tempo")
        self.assertContains(response, "Trent Barton")
        self.assertContains(response, "#FF0000")

        self.assertContains(response, ">00:47<")
        self.assertContains(response, ">13:00<")
        self.assertContains(response, ">&larr; Friday 16 October 2020<")

        with self.assertNumQueries(7):
            response = self.client.get(self.vehicle_2.get_absolute_url())
        self.assertEqual(200, response.status_code)

        # can't connect to redis - no drama
        with override_settings(REDIS_URL="redis://localhose:69"):
            with self.assertNumQueries(3):
                response = self.client.get(
                    f"/vehicles/{self.vehicle_1.id}/journeys/{self.journey.id}.json"
                )
        self.assertEqual(
            {
                "code": "",
                "datetime": "2020-10-19T23:47:00Z",
                "destination": "",
                "direction": "",
                "next": {"datetime": "2020-10-20T12:00:00Z", "id": self.journey.id + 2},
                "previous": {
                    "datetime": "2020-10-16T12:00:00Z",
                    "id": self.journey.id + 1,
                },
                "route_name": "2",
            },
            response.json(),
        )

        self.journey.refresh_from_db()
        self.assertEqual(str(self.journey), "19 Oct 20 23:47 2  ")
        self.assertEqual(
            self.journey.get_absolute_url(),
            f"/vehicles/{self.vehicle_1.id}?date=2020-10-19#journeys/{self.journey.id}",
        )

    def test_location_json(self):
        location = VehicleLocation(latlong=Point(0, 51))
        location.id = 1
        location.journey = self.journey
        location.datetime = parse_datetime(self.datetime)

        self.assertEqual(str(location), "19 Oct 2020 23:47:00")

        self.assertEqual(location.get_redis_json()["coordinates"], (0.0, 51.0))

        location.occupancy = "seatsAvailable"
        self.assertEqual(location.get_redis_json()["seats"], "Seats available")

        location.wheelchair_occupancy = 0
        location.wheelchair_capacity = 0
        self.assertNotIn("wheelchair", location.get_redis_json())

        location.wheelchair_capacity = 1
        self.assertEqual(location.get_redis_json()["wheelchair"], "free")

    def test_vehicle_json(self):
        vehicle = Vehicle.objects.get(id=self.vehicle_2.id)
        vehicle.feature_names = "foo, bar"

        self.assertEqual(vehicle.get_json()["features"], "Double decker<br>foo, bar")

        vehicle = Vehicle.objects.get(id=self.vehicle_1.id)
        vehicle.feature_names = ""

        self.assertEqual(vehicle.get_json()["css"], "#FF0000")

        vehicle.colours = "#000000 #FFFFFF #FFFFFF"
        self.assertEqual(
            vehicle.get_json()["colour"], "#FFFFFF"
        )  # most frequent colour in list of colours

    def test_vehicle_admin(self):
        self.client.force_login(self.staff_user)

        # test copy type, livery actions
        self.client.post(
            "/admin/vehicles/vehicle/",
            {
                "action": "copy_type",
                "_selected_action": [self.vehicle_1.id, self.vehicle_2.id],
            },
        )
        self.client.post(
            "/admin/vehicles/vehicle/",
            {
                "action": "copy_livery",
                "_selected_action": [self.vehicle_1.id, self.vehicle_2.id],
            },
        )
        self.client.post(
            "/admin/vehicles/vehicle/",
            {
                "action": "spare_ticket_machine",
                "_selected_action": [self.vehicle_1.id, self.vehicle_2.id],
            },
        )
        response = self.client.get("/admin/vehicles/vehicle/")
        self.assertContains(response, "Copied Optare Spectra to 2 vehicles.")
        self.assertContains(response, "Copied black with lemon piping to 2 vehicles.")

        # spare ticket machine should disable form fields
        response = self.client.get(self.vehicle_1.get_edit_url())
        self.assertEqual(404, response.status_code)
        # self.assertNotContains(response, "previous_reg")

        response = self.client.get("/operators/lynx/vehicles/edit")
        self.assertContains(response, "<td>Spare ticket machine</td>")

        # test make livery
        self.client.post(
            "/admin/vehicles/vehicle/",
            {"action": "make_livery", "_selected_action": [self.vehicle_1.id]},
        )
        response = self.client.get("/admin/vehicles/vehicle/")
        self.assertContains(response, "Select a vehicle with colours and branding.")
        self.client.post(
            "/admin/vehicles/vehicle/",
            {"action": "make_livery", "_selected_action": [self.vehicle_3.id]},
        )
        response = self.client.get("/admin/vehicles/vehicle/")
        self.assertContains(response, "Updated 1 vehicles.")

        # test merge 2 vehicles:

        duplicate_1 = Vehicle.objects.create(reg="SA60TWP", code="60")
        duplicate_2 = Vehicle.objects.create(reg="SA60TWP", code="SA60TWP")

        self.assertEqual(Vehicle.objects.all().count(), 5)

        response = self.client.get("/admin/vehicles/vehicle/?duplicate=reg")
        self.assertContains(response, '2 results (<a href="?">5 total</a>')

        response = self.client.get("/admin/vehicles/vehicle/?duplicate=operator")
        self.assertContains(response, '0 results (<a href="?">5 total</a>')

        self.client.post(
            "/admin/vehicles/vehicle/",
            {
                "action": "deduplicate",
                "_selected_action": [duplicate_1.id, duplicate_2.id],
            },
        )
        self.assertEqual(Vehicle.objects.all().count(), 4)

    def test_livery_admin(self):
        self.client.force_login(self.staff_user)

        response = self.client.get("/admin/vehicles/livery/")
        self.assertContains(
            response, '<td class="field-name">black with lemon piping</td>'
        )
        self.assertContains(response, '<td class="field-vehicles">1</td>')
        self.assertContains(
            response,
            """<td class="field-left">\
<svg height="24" width="36" style="line-height:24px;font-size:24px;\
background:linear-gradient(to right,#FF0000 50%,#0000FF 50%)">
                <text x="50%" y="80%" fill="#fff" text-anchor="middle" style="">42</text>
            </svg></td>""",
        )
        self.assertContains(
            response,
            """<td class="field-right">\
<svg height="24" width="36" style="line-height:24px;font-size:24px;\
background:linear-gradient(to left,#FF0000 50%,#0000FF 50%)">
                <text x="50%" y="80%" fill="#fff" text-anchor="middle" style="">42</text>
            </svg>""",
        )

    def test_vehicle_type_admin(self):
        self.client.force_login(self.staff_user)

        response = self.client.get("/admin/vehicles/vehicletype/")
        self.assertContains(response, "Optare Spectra")
        self.assertContains(response, '<td class="field-vehicles">1</td>', 2)

        self.client.post(
            "/admin/vehicles/vehicletype/",
            {
                "action": "merge",
                "_selected_action": [
                    self.vehicle_1.vehicle_type_id,
                    self.vehicle_2.vehicle_type_id,
                ],
            },
        )
        response = self.client.get("/admin/vehicles/vehicletype/")
        self.assertContains(response, '<td class="field-vehicles">2</td>', 1)
        self.assertContains(response, '<td class="field-vehicles">0</td>', 1)

    def test_journey_admin(self):
        self.client.force_login(self.staff_user)

        response = self.client.get("/admin/vehicles/vehiclejourney/?trip__isnull=1")
        self.assertContains(response, "0 of 3 selected")

    def test_search(self):
        response = self.client.get("/search?q=fd54jya")
        self.assertContains(response, "1 vehicle")

        response = self.client.get("/search?q=11111")
        self.assertNotContains(response, "vehicle")

    def test_liveries_css(self):
        response = self.client.get("/liveries.44.css")
        self.assertEqual(
            response.content.decode(),
            f""".livery-{self.livery.id} {{
  background: linear-gradient(to right,#FF0000 50%,#0000FF 50%);
  color:#fff;fill:#fff
}}
.livery-{self.livery.id}.right {{
  background: linear-gradient(to left,#FF0000 50%,#0000FF 50%)
}}
""",
        )

    def test_vehicle_edit_1(self):
        url = self.vehicle_1.get_edit_url()

        with self.assertNumQueries(0):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/accounts/login/?next={url}")

        with self.assertNumQueries(0):
            response = self.client.get(response.url)
        self.assertContains(response, "<p>To edit vehicle details, please log in.</p>")

        self.client.force_login(self.staff_user)

        with self.assertNumQueries(11):
            response = self.client.get(url)
        self.assertNotContains(response, "already")

        initial = {
            "fleet_number": "1",
            "reg": "FD54JYA",
            "vehicle_type": self.vehicle_1.vehicle_type_id,
            "other_vehicle_type": str(self.vehicle_1.vehicle_type),
            "features": self.wifi.id,
            "operator": self.lynx.noc,
            "colours": "#FF0000",
            "notes": "Trent Barton",
        }

        # edit nothing
        with self.assertNumQueries(14):
            response = self.client.post(url, initial)
        self.assertFalse(response.context["form"].has_changed())
        self.assertNotContains(response, "already")

        # edit nothing but summary
        initial["summary"] = (
            "Poo poo pants\r\r\n"
            "https://www.flickr.com/pho"
            "tos/goodwinjoshua/51046126023/in/photolist-2n3qgFa-2n2eJqm-2mL2ptW-2k"
            "LLJR6-2hXgjnC-2hTkN9R-2gRxwqk-2g3ut3U-29p2ZiJ-ZrgH1M-WjEYtY-SFzez8-Sh"
            "KDfn-Pc9Xam-MvcHsg-2mvhSdj-FW3FiA-z9Xy5u-v8vKmD-taSCD6-uJFzob-orkudc-"
            "mjXUYS-i2nbH2-hyrrxD-fabgxp-fbM7Gf-eR4fGA-eHtfHb-eAreVh-ekmQ1E-e8sxcb"
            "-aWWgKX-aotzn6-aiadaL-adWEKk/ blah"
        )

        with self.assertNumQueries(14):
            response = self.client.post(url, initial)
        self.assertFalse(response.context["form"].has_really_changed())
        self.assertNotContains(response, "already")

        # edit fleet number
        initial["fleet_number"] = "2"
        initial["previous_reg"] = "bean"
        with self.assertNumQueries(15):
            response = self.client.post(url, initial)
        self.assertIsNone(response.context["form"])
        self.assertContains(response, "Changed fleet number from 1 to 2")
        self.assertContains(response, "I’ll update the other details")
        revision = response.context["revision"]
        self.assertEqual(
            revision.message,
            """Poo poo pants

https://www.flickr.com/photos/goodwinjoshua/51046126023/ blah""",
        )

        edit = response.context["edit"]
        self.assertEqual(edit.colours, "")
        self.assertEqual(
            edit.url,
            """Poo poo pants

https://www.flickr.com/photos/goodwinjoshua/51046126023/ blah""",
        )
        self.assertEqual(edit.get_changes(), {"previous reg": "BEAN"})

        # should not create an edit
        with self.assertNumQueries(16):
            initial["colours"] = "#FFFF00"
            response = self.client.post(url, initial)
        self.assertTrue(response.context["form"].has_changed())
        self.assertContains(
            response,
            "Select a valid choice. #FFFF00 is not one of the available choices",
        )
        self.assertContains(response, "already")

        self.assertEqual(1, VehicleEdit.objects.all().count())

        response = self.client.get("/admin/accounts/user/")
        self.assertContains(
            response,
            '<td class="field-approved">'
            f'<a href="/admin/vehicles/vehicleedit/?user={self.staff_user.id}&approved__exact=1">0</a></td>'
            '<td class="field-disapproved">'
            f'<a href="/admin/vehicles/vehicleedit/?user={self.staff_user.id}&approved__exact=0">0</a></td>'
            '<td class="field-pending">'
            f'<a href="/admin/vehicles/vehicleedit/?user={self.staff_user.id}&approved__isnull=True">1</a></td>',
        )

        with self.assertNumQueries(8):
            response = self.client.get("/vehicles/edits")
        self.assertContains(response, "previous reg: BEAN")

        del initial["colours"]

        # staff user can fully edit branding and notes
        initial["branding"] = "Crag Hopper"
        initial["notes"] = "West Coast Motors"
        with self.assertNumQueries(15):
            response = self.client.post(url, initial)
        self.assertContains(
            response, "Changed notes from Trent Barton to West Coast Motors"
        )
        self.assertContains(response, "Changed branding to Crag Hopper")

        del initial["previous_reg"]

        # remove a feature
        del initial["features"]
        with self.assertNumQueries(14):
            response = self.client.post(url, initial)

        vef = VehicleEditFeature.objects.get()
        self.assertEqual(str(vef), "<del>Wi-Fi</del>")

        edit = vef.edit
        self.assertEqual(edit.get_changes(), {"features": [vef]})

    def test_vehicle_edit_2(self):
        self.client.force_login(self.staff_user)

        url = self.vehicle_2.get_edit_url()

        initial = {
            "fleet_number": "50",
            "reg": "UWW2X",
            "operator": self.vehicle_2.operator_id,
            "vehicle_type": self.vehicle_2.vehicle_type_id,
            "other_vehicle_type": str(self.vehicle_2.vehicle_type),
            "colours": self.livery.id,
            "notes": "",
        }

        with self.assertNumQueries(13):
            response = self.client.post(url, initial)
        self.assertFalse(response.context["form"].has_changed())
        self.assertNotContains(response, "already")
        self.assertContains(response, "You haven&#x27;t changed anything")

        self.assertEqual(0, VehicleEdit.objects.count())
        self.assertEqual(0, VehicleRevision.objects.count())

        self.assertNotContains(response, "/operators/bova-and-over")

        initial["notes"] = "Ex Ipswich Buses"
        initial["name"] = "Luther Blisset"
        initial["branding"] = "Coastliner"
        initial["previous_reg"] = "k292  jvf"
        initial["reg"] = ""
        with self.assertNumQueries(14):
            response = self.client.post(url, initial)
        self.assertIsNone(response.context["form"])

        self.assertContains(response, "<p>I’ll update the other details shortly</p>")

        edit = VehicleEdit.objects.get()
        self.assertEqual(
            edit.get_changes(),
            {
                "reg": "<del>UWW2X</del>",
                "previous reg": "K292JVF",
            },
        )

        response = self.client.get("/vehicles/history")
        self.assertContains(response, "Luther Blisset")

        response = self.client.get(f"{self.vehicle_2.get_absolute_url()}/history")
        self.assertContains(response, "Luther Blisset")

        with self.assertNumQueries(13):
            response = self.client.get(url)
        self.assertContains(response, "already")

    def test_vehicle_edit_colour(self):
        self.client.force_login(self.staff_user)
        url = self.vehicle_2.get_edit_url()

        initial = {
            "fleet_number": "50",
            "reg": "UWW2X",
            "vehicle_type": self.vehicle_2.vehicle_type_id,
            "other_vehicle_type": "Optare Spectra",
            "operator": self.vehicle_2.operator_id,
            "colours": self.livery.id,
            "other_colour": "",
            "notes": "",
        }

        with self.assertNumQueries(13):
            response = self.client.post(url, initial)
            self.assertContains(response, "You haven&#x27;t changed anything")

        initial["colours"] = "Other"
        initial["other_colour"] = "Bath is my favourite spa town, and so is Harrogate"
        with self.assertNumQueries(13):
            response = self.client.post(url, initial)
            self.assertEqual(
                response.context["form"].errors,
                {
                    "other_colour": [
                        "An HTML5 simple color must be a Unicode string seven characters long."
                    ]
                },
            )

    def test_remove_fleet_number(self):
        self.client.force_login(self.staff_user)

        url = self.vehicle_1.get_edit_url()

        # create a revision and an edit
        with self.assertNumQueries(15):
            self.client.post(
                url,
                {
                    "fleet_number": "",
                    "other_vehicle_type": "Scania Fencer",
                    "reg": "",
                    "operator": self.lynx.noc,
                },
            )

        revision = VehicleRevision.objects.get()
        self.assertEqual(str(revision), "notes: Trent Barton → ")

        edit = VehicleEdit.objects.get()

        self.client.force_login(
            self.trusted_user
        )  # switch user to vote (can't vote on one's own edits)

        # vote for edit
        with self.assertNumQueries(12):
            self.client.post(f"/vehicles/edits/{edit.id}/vote/up")
        with self.assertNumQueries(10):
            self.client.post(f"/vehicles/edits/{edit.id}/vote/down")
        with self.assertNumQueries(10):
            self.client.post(f"/vehicles/edits/{edit.id}/vote/down")

        with self.assertNumQueries(5):
            response = self.client.get("/vehicles/edits?change=livery")
        self.assertEqual(len(response.context["edits"]), 0)

        with self.assertNumQueries(11):
            response = self.client.get("/vehicles/edits?change=reg")
        self.assertEqual(len(response.context["edits"]), 1)
        self.assertContains(response, '<option value="LYNX">Lynx (1)</option>')
        self.assertContains(response, '<td class="score">-1</td>')

        self.client.force_login(self.staff_user)

        # try to apply the edit
        with self.assertNumQueries(16):
            self.client.post(f"/vehicles/edits/{edit.id}/apply")

        # -not marked as approved- _vehicle type created_ cos there was no vehicle type matching name
        edit.refresh_from_db()
        self.assertTrue(edit.approved)

        vehicle = Vehicle.objects.get(id=self.vehicle_1.id)
        self.assertIsNone(vehicle.fleet_number)
        self.assertEqual("", vehicle.fleet_code)
        self.assertEqual("", vehicle.reg)

        revision = VehicleRevision.objects.last()
        self.assertEqual(
            revision.changes, {"reg": "-FD54JYA\n+", "fleet number": "-1\n+"}
        )
        revision = edit.make_revision()
        self.assertEqual(revision.changes, {"reg": "-\n+", "fleet number": "-\n+"})

        with self.assertNumQueries(4):
            self.client.post(f"/vehicles/edits/{edit.id}/approve")
        with self.assertNumQueries(4):
            self.client.post(f"/vehicles/edits/{edit.id}/disapprove")

        # test user view
        response = self.client.get(self.staff_user.get_absolute_url())
        self.assertContains(response, "Trent Barton")

    def test_vehicle_edit_3(self):
        self.client.force_login(self.user)

        with self.assertNumQueries(7):
            response = self.client.get(self.vehicle_3.get_edit_url())
        self.assertNotContains(response, "livery")
        self.assertNotContains(response, "notes")

        with self.assertNumQueries(8):
            # new user - can create a VehicleEdit
            response = self.client.post(
                self.vehicle_3.get_edit_url(),
                {"reg": "D19 FOX", "previous_reg": "QC FBPE", "withdrawn": True},
            )
        self.assertContains(response, "I’ll update those details shortly")

        edit = VehicleEdit.objects.get()
        self.assertFalse(edit.vehicle.withdrawn)
        edit.apply(save=False)
        self.assertTrue(edit.vehicle.withdrawn)

        with self.assertNumQueries(13):
            response = self.client.post(
                self.vehicle_2.get_edit_url(),
                {
                    "reg": self.vehicle_2.reg,
                    "vehicle_type": self.vehicle_2.vehicle_type_id,
                    "colours": "Other",
                    "prevous_reg": "SPIDERS",  # doesn't match regex
                },
            )
            self.assertContains(response, "I’ll update those details shortly")

        self.client.force_login(self.trusted_user)

        with self.assertNumQueries(9):
            # trusted user - can edit reg and remove branding
            response = self.client.post(
                self.vehicle_3.get_edit_url(),
                {
                    "reg": "DA04 DDA",
                    "branding": "",
                    "previous_reg": "K292  JVF,P44CEX",  # has to match regex
                },
            )
        self.assertEqual(
            str(response.context["revision"]),
            "reg:  → DA04DDA, previous reg:  → K292JVF,P44CEX, branding: Coastliner → ",
        )
        self.assertContains(response, "Changed reg to DA04DDA")
        self.assertContains(response, "Changed previous reg to K292JVF,P44CEX")
        self.assertContains(response, "Changed branding from Coastliner to")

        # test previous reg display
        response = self.client.get(self.vehicle_3.get_absolute_url())
        self.assertContains(response, ">K292 JVF, P44 CEX<")

        with self.assertNumQueries(15):
            # trusted user - can edit colour
            response = self.client.post(
                self.vehicle_2.get_edit_url(),
                {
                    "reg": self.vehicle_2.reg,
                    "vehicle_type": self.vehicle_2.vehicle_type_id,
                    "other_vehicle_type": str(self.vehicle_2.vehicle_type),
                    "operator": self.vehicle_2.operator_id,
                    "colours": "Other",
                },
            )
        self.assertContains(
            response,
            'Changed livery from <span class="livery" '
            'style="background:linear-gradient(to right,#FF0000 50%,#0000FF 50%)"></span> to None',
        )
        self.assertContains(response, "Changed colours to Other")

        revision = VehicleRevision.objects.last()
        self.assertEqual(
            list(revision.revert()),
            [
                f"vehicle {revision.vehicle_id} colours not reverted",
                f"vehicle {revision.vehicle_id} reverted ['livery']",
            ],
        )
        revision = VehicleRevision.objects.first()
        self.assertEqual(
            list(revision.revert()),
            [
                f"vehicle {revision.vehicle_id} branding not reverted",
                f"vehicle {revision.vehicle_id} previous reg not reverted",
                f"vehicle {revision.vehicle_id} reverted ['reg']",
            ],
        )
        self.assertEqual(revision.vehicle.reg, "")

        # bulk approve edit
        with self.assertRaises(AssertionError):
            response = self.client.post(
                "/vehicles/edits", {"action": "apply", "edit": edit.id}
            )

        self.client.force_login(self.staff_user)
        with self.assertNumQueries(14):
            response = self.client.post(
                "/vehicles/edits", {"action": "apply", "edit": edit.id}
            )
        revision = VehicleRevision.objects.last()
        self.assertEqual(
            revision.changes,
            {"reg": "-\n+D19FOX", "branding": "-\n+", "withdrawn": "-No\n+Yes"},
        )

    def test_vehicles_edit(self):
        # user isn't logged in
        with self.assertNumQueries(1):
            response = self.client.get("/operators/lynx/vehicles/edit")
        self.assertEqual(302, response.status_code)

        self.client.force_login(self.trusted_user)

        data = {"operator": self.lynx.noc}

        # no vehicle ids specified
        with self.assertNumQueries(11):
            response = self.client.post("/operators/lynx/vehicles/edit", data)
        self.assertContains(response, "Select some vehicles to change")

        data["vehicle"] = self.vehicle_1.id
        with self.assertNumQueries(11):
            response = self.client.post("/operators/lynx/vehicles/edit", data)
        self.assertContains(response, "You haven&#x27;t changed anything")

        self.assertFalse(VehicleEdit.objects.all())
        self.assertFalse(VehicleRevision.objects.all())

        # change vehicle type and colours:
        with self.assertNumQueries(20):
            response = self.client.post(
                "/operators/lynx/vehicles/edit",
                {
                    **data,
                    "vehicle_type": self.vehicle_2.vehicle_type_id,
                    "colours": self.livery.id,
                },
            )
        self.assertContains(response, "1 vehicle updated")
        revision = VehicleRevision.objects.get()
        self.assertIsNone(revision.from_livery)
        self.assertTrue(revision.to_livery)
        self.assertEqual("Optare Tempo", revision.from_type.name)
        self.assertEqual("Optare Spectra", revision.to_type.name)
        self.assertContains(response, "FD54 JYA")

        self.assertFalse(VehicleEdit.objects.all())

        # add feature as a trusted user
        with self.assertNumQueries(20):
            response = self.client.post(
                "/operators/lynx/vehicles/edit",
                {
                    "vehicle": self.vehicle_2.id,
                    "features": self.wifi.id,
                },
            )
            self.assertContains(response, "1 vehicle updated")

        # add feature as a normal user
        self.client.force_login(self.user)
        with self.assertNumQueries(18):
            response = self.client.post(
                "/operators/lynx/vehicles/edit",
                {
                    "vehicle": self.vehicle_2.id,
                    "features": self.usb.id,
                },
            )
            self.assertContains(
                response, "I’ll update those details (1 vehicle) shortly"
            )

        # log in to Django admin
        self.client.force_login(self.staff_user)

        # revert
        self.client.post(
            "/admin/vehicles/vehiclerevision/",
            {"action": "revert", "_selected_action": revision.id},
        )
        response = self.client.get("/admin/vehicles/vehiclerevision/")
        self.assertContains(response, "reverted [&#x27;vehicle_type&#x27;, ")
        self.assertContains(response, "colours not reverted")

    def test_vehicle_code_uniqueness(self):
        vehicle_1 = Vehicle.objects.create(code="11111", operator_id="BOVA")
        Vehicle.objects.create(
            code="11111", operator_id="LYNX"
        )  # same code, different operator

        self.client.force_login(self.staff_user)

        with self.assertRaises(TransactionManagementError):
            self.client.post(vehicle_1.get_edit_url(), {"operator": "LYNX"})

    def test_big_map(self):
        with self.assertNumQueries(1):
            self.client.get("/map")

    def test_vehicles(self):
        with self.assertNumQueries(3):
            self.client.get("/vehicles")

    def test_service_vehicle_history(self):
        with self.assertNumQueries(6):
            response = self.client.get(
                "/services/spixworth-hunworth-happisburgh/vehicles?date=poop"
            )
        with self.assertNumQueries(5):
            response = self.client.get(
                "/services/spixworth-hunworth-happisburgh/vehicles?date=2020-10-20"
            )
        self.assertContains(response, "Vehicles")
        self.assertContains(response, "/vehicles/")
        self.assertContains(
            response,
            '<input type="date" onchange="this.form.submit()" name="date" id="date" aria-label="Date" '
            'value="2020-10-20">'
            # '<option selected value="2020-10-20">Tuesday 20 October 2020</option>'
        )
        self.assertContains(response, "1 - FD54 JYA")

    def test_api(self):
        with self.assertNumQueries(2):
            response = self.client.get("/api/vehicles/?limit=2")
        self.assertEqual(
            response.json(),
            {
                "count": 3,
                "next": "http://testserver/api/vehicles/?limit=2&offset=2",
                "previous": None,
                "results": [
                    {
                        "id": self.vehicle_1.id,
                        "slug": "lynx-2",
                        "fleet_number": 1,
                        "fleet_code": "1",
                        "reg": "FD54JYA",
                        "vehicle_type": {
                            "id": self.vehicle_1.vehicle_type_id,
                            "name": "Optare Tempo",
                            "double_decker": False,
                            "coach": False,
                            "electric": False,
                            "style": "",
                            "fuel": "diesel",
                        },
                        "livery": {
                            "id": None,
                            "name": None,
                            "left": "#FF0000",
                            "right": "#FF0000",
                        },
                        "branding": "",
                        "operator": {
                            "id": "LYNX",
                            "name": "Lynx",
                            "parent": "Madrigal Electromotive",
                        },
                        "garage": None,
                        "name": "",
                        "notes": "Trent Barton",
                        "withdrawn": False,
                    },
                    {
                        "id": self.vehicle_2.id,
                        "slug": "lynx-50",
                        "fleet_number": 50,
                        "fleet_code": "50",
                        "reg": "UWW2X",
                        "vehicle_type": {
                            "id": self.vehicle_2.vehicle_type_id,
                            "name": "Optare Spectra",
                            "double_decker": True,
                            "coach": False,
                            "electric": False,
                            "style": "double decker",
                            "fuel": "diesel",
                        },
                        "livery": {
                            "id": self.vehicle_2.livery_id,
                            "name": "black with lemon piping",
                            "left": "linear-gradient(to right,#FF0000 50%,#0000FF 50%)",
                            "right": "linear-gradient(to left,#FF0000 50%,#0000FF 50%)",
                        },
                        "branding": "",
                        "operator": {
                            "id": "LYNX",
                            "name": "Lynx",
                            "parent": "Madrigal Electromotive",
                        },
                        "garage": None,
                        "name": "",
                        "notes": "",
                        "withdrawn": False,
                    },
                ],
            },
        )

        with self.assertNumQueries(1):
            response = self.client.get("/api/vehicles/?reg=sa60twp")
        self.assertEqual(0, response.json()["count"])

        with self.assertNumQueries(2):
            response = self.client.get("/api/vehicles/?search=fd54jya")
        self.assertEqual(1, response.json()["count"])

    def test_siri_post(self):
        response = self.client.post("/siri/475d1d1f-5708-4ee1-8f51-c63d948bc0b9")
        self.assertEqual(404, response.status_code)

        SiriSubscription.objects.create(
            name="Transport for Whales", uuid="475d1d1f-5708-4ee1-8f51-c63d948bc0b9"
        )
        DataSource.objects.create(name="Transport for Whales")
        response = self.client.post(
            "/siri/475d1d1f-5708-4ee1-8f51-c63d948bc0b9",
            data="""<?xml version="1.0" encoding="UTF-8" ?>
<Siri xmlns="http://www.siri.org.uk/siri" version="1.3"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.siri.org.uk/siri http://www.siri.org.uk/schema/1.3/siri.xsd">
    <HeartbeatNotification>
        <RequestTimestamp>2023-11-30T13:14:01+00:00</RequestTimestamp>
        <ProducerRef>Beluga</ProducerRef>
        <Status>true</Status>
        <ServiceStartedTime>2023-11-29T09:43:26+00:00</ServiceStartedTime>
    </HeartbeatNotification>
</Siri>""",
            content_type="text/xml",
        )
        self.assertEqual(200, response.status_code)
