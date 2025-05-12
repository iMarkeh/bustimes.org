from pathlib import Path

from django.test import TestCase
from django.core.management import call_command
from vcr import use_cassette

from ...models import (
    BankHoliday,
    BankHolidayDate,
)


class ImportTransXChangeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        bhs = BankHoliday.objects.bulk_create(
            BankHoliday(name=name)
            for name in (
                "Northern Ireland bank holidays",
                "AllHolidaysExceptChristmas",
                "DisplacementHolidays",
                "StAndrewsDayHoliday",
                "AugustBankHolidayScotland",
                "StAndrewsDay",
                "EarlyRunOffDays",
                "Christmas",
                "AllBankHolidays",
                "HolidayMondays",
                "Jan2ndScotlandHoliday",
                "Jan2ndScotland",
                "NewYearsEve",
                "ChristmasEve",
                "NewYearsDayHoliday",
                "BoxingDayHoliday",
                "ChristmasDayHoliday",
                "SpringBank",
                "EasterMonday",
                "MayDay",
                "LateSummerBankHolidayNotScotland",
                "NewYearsDay",
                "GoodFriday",
                "BoxingDay",
                "ChristmasDay",
            )
        )
        # create one Christmas Day date
        BankHolidayDate.objects.create(bank_holiday=bhs[-1], date="2025-12-25")

    def test_bank_holidays(self):
        fixtures_dir = Path(__file__).resolve().parent / "fixtures"

        with (
            use_cassette(str(fixtures_dir / "bank_holidays.yaml")) as cassette,
            self.assertNumQueries(6),
            self.assertLogs("bustimes.management.commands.bank_holidays", "WARNING"),
        ):
            call_command("bank_holidays")
            cassette.rewind()
            call_command("bank_holidays")  # test for idempotence

        # Christmas Eve and NYE are not really bank holidays,
        # only they are the world of TransXChange,
        # so we must create them manually elsewhere
        self.assertEqual(
            0, BankHolidayDate.objects.filter(bank_holiday__name="ChristmasEve").count()
        )
        self.assertEqual(
            0, BankHolidayDate.objects.filter(bank_holiday__name="NewYearsEve").count()
        )

        self.assertEqual(
            6, BankHolidayDate.objects.filter(bank_holiday__name="ChristmasDay").count()
        )

        self.assertEqual(
            93,
            BankHolidayDate.objects.filter(
                bank_holiday__name="Northern Ireland bank holidays"
            ).count(),
        )
