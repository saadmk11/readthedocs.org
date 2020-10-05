# Generated by Django 2.2.16 on 2020-10-05 06:10
# Generated by Django 2.2.16 on 2020-10-10 14:55

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import django_extensions.db.fields
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('oauth', '0010_index_full_name'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='RemoteRelation',
                    fields=[
                        ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                    ],
                    options={
                        'db_table': 'oauth_remoterepository_users',
                    },
                ),
                migrations.AlterField(
                    model_name='remoterepository',
                    name='users',
                    field=models.ManyToManyField(related_name='oauth_repositories', through='oauth.RemoteRelation', to=settings.AUTH_USER_MODEL, verbose_name='Users'),
                ),
                migrations.AddField(
                    model_name='remoterelation',
                    name='remoterepository',
                    field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='remote_relations', to='oauth.RemoteRepository'),
                ),
                migrations.AddField(
                    model_name='remoterelation',
                    name='user',
                    field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='remote_relations', to=settings.AUTH_USER_MODEL),
                ),
                migrations.AlterUniqueTogether(
                    name='remoterelation',
                    unique_together={('remoterepository', 'user')},
                ),
            ]
        )
    ]
