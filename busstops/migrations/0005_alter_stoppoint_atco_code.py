# Generated by Django 5.1.2 on 2024-11-04 14:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('busstops', '0004_datasource_etag_datasource_last_modified_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='stoppoint',
            name='atco_code',
            field=models.CharField(max_length=36, primary_key=True, serialize=False),
        ),
    ]
