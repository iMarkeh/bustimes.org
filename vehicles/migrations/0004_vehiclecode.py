# Generated by Django 3.2.9 on 2021-11-27 14:13

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vehicles', '0003_auto_20211029_1901'),
    ]

    operations = [
        migrations.CreateModel(
            name='VehicleCode',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=24)),
                ('scheme', models.CharField(max_length=24)),
                ('vehicle', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='vehicles.vehicle')),
            ],
            options={
                'index_together': {('code', 'scheme')},
            },
        ),
    ]