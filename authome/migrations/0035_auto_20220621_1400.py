# Generated by Django 3.2.12 on 2022-06-21 06:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authome', '0034_auto_20220621_1136'),
    ]

    operations = [
        migrations.AlterField(
            model_name='auth2cluster',
            name='idp_lastrefreshed',
            field=models.DateTimeField(editable=False, null=True),
        ),
        migrations.AlterField(
            model_name='auth2cluster',
            name='userflow_lastrefreshed',
            field=models.DateTimeField(editable=False, null=True),
        ),
        migrations.AlterField(
            model_name='auth2cluster',
            name='usergroup_lastrefreshed',
            field=models.DateTimeField(editable=False, null=True),
        ),
        migrations.AlterField(
            model_name='auth2cluster',
            name='usergroupauthorization_lastrefreshed',
            field=models.DateTimeField(editable=False, null=True),
        ),
    ]