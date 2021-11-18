# Generated by Django 3.1.6 on 2021-02-08 03:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authome', '0004_auto_20210208_0824'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customizableuserflow',
            name='default',
            field=models.CharField(blank=True, help_text='The default user flow used by this domain', max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name='customizableuserflow',
            name='domain',
            field=models.CharField(help_text="Global setting if domain is '*'; otherwise is individual domain settings", max_length=128, unique=True),
        ),
        migrations.AlterField(
            model_name='customizableuserflow',
            name='email',
            field=models.CharField(blank=True, help_text='The email signup and signin user flow', max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name='customizableuserflow',
            name='email_enabled',
            field=models.BooleanField(default=True, help_text='Enable/Disable the email singin for this domain'),
        ),
        migrations.AlterField(
            model_name='customizableuserflow',
            name='email_signup',
            field=models.CharField(blank=True, help_text='The email signup user flow', max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name='customizableuserflow',
            name='fixed',
            field=models.CharField(blank=True, help_text='The only user flow used by this domain if configured', max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name='customizableuserflow',
            name='page_layout',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='customizableuserflow',
            name='password_reset',
            field=models.CharField(blank=True, help_text='The user password reset user flow', max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name='customizableuserflow',
            name='profile_edit',
            field=models.CharField(blank=True, help_text='The user profile edit user flow', max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='first_name',
            field=models.CharField(blank=True, max_length=150, verbose_name='first name'),
        ),
    ]
