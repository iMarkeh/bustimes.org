# Generated by Django 5.1.8 on 2025-04-18 13:11

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('busstops', '0007_sirisource_operators_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='datasource',
            name='description',
            field=models.CharField(blank=True),
        ),
    ]
