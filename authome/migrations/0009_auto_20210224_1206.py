# Generated by Django 3.1.6 on 2021-02-24 04:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authome', '0008_auto_20210222_0905'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='customizableuserflow',
            name='email_signup',
        ),
        migrations.AddField(
            model_name='customizableuserflow',
            name='mfa_set',
            field=models.CharField(blank=True, help_text='The mfa set user flow', max_length=64, null=True),
        ),
    ]
