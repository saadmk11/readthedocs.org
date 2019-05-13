# -*- coding: utf-8 -*-
# Generated by Django 1.11.20 on 2019-03-01 14:25
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sphinx_domains', '0002_increase_max_length'),
    ]

    operations = [
        migrations.AddField(
            model_name='sphinxdomain',
            name='doc_display',
            field=models.CharField(max_length=4092, null=True, verbose_name='Doc Display'),
        ),
        migrations.AddField(
            model_name='sphinxdomain',
            name='type_display',
            field=models.CharField(max_length=4092, null=True, verbose_name='Type Display'),
        ),
    ]
