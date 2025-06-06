# Generated by Django 5.1.7 on 2025-05-26 02:52

import authome.models.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('authome', '0052_alter_auth2cluster_options_alter_debuglog_options_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userauthorization',
            name='excluded_paths',
            field=authome.models.models.ArrayField(base_field=models.CharField(max_length=128), blank=True, help_text="\nList all possible paths separated by new line character.\nThe following lists all valid options in the checking order\n    1. All path      : *\n    2. Prefix path   : the paths except All path, regex path and exact path. For example /admin\n    3. Regex path    : A regex string starts with '^'. For example ^.*/add$\n    4. Exact path  : Starts with '=', represents a single request path . For example =/register\n", null=True, size=None),
        ),
        migrations.AlterField(
            model_name='userauthorization',
            name='paths',
            field=authome.models.models.ArrayField(base_field=models.CharField(max_length=512), blank=True, help_text="\nList all possible paths separated by new line character.\nThe following lists all valid options in the checking order\n    1. All path      : *\n    2. Prefix path   : the paths except All path, regex path and exact path. For example /admin\n    3. Regex path    : A regex string starts with '^'. For example ^.*/add$\n    4. Exact path  : Starts with '=', represents a single request path . For example =/register\n", null=True, size=None),
        ),
        migrations.AlterField(
            model_name='usergroup',
            name='excluded_users',
            field=authome.models.models.ArrayField(base_field=models.CharField(max_length=64), blank=True, help_text="\nList all possible user emails in this group separated by new line character.\nThe following lists all valid options in the checking order\n    1. All Emails    : *\n    2. Domain Email  : Starts with '@', followed by email domain. For example@dbca.wa.gov.au\n    3. Email Pattern : A email pattern,'*' represents any strings. For example test_*@dbca.wa.gov.au\n    4. Regex Email   : A regex email, starts with '^' and ends with '$'\n    5. User Email    : A single user email, For example test_user01@dbca.wa.gov.au\n", null=True, size=None),
        ),
        migrations.AlterField(
            model_name='usergroup',
            name='users',
            field=authome.models.models.ArrayField(base_field=models.CharField(max_length=64), help_text="\nList all possible user emails in this group separated by new line character.\nThe following lists all valid options in the checking order\n    1. All Emails    : *\n    2. Domain Email  : Starts with '@', followed by email domain. For example@dbca.wa.gov.au\n    3. Email Pattern : A email pattern,'*' represents any strings. For example test_*@dbca.wa.gov.au\n    4. Regex Email   : A regex email, starts with '^' and ends with '$'\n    5. User Email    : A single user email, For example test_user01@dbca.wa.gov.au\n", size=None),
        ),
        migrations.AlterField(
            model_name='usergroupauthorization',
            name='excluded_paths',
            field=authome.models.models.ArrayField(base_field=models.CharField(max_length=128), blank=True, help_text="\nList all possible paths separated by new line character.\nThe following lists all valid options in the checking order\n    1. All path      : *\n    2. Prefix path   : the paths except All path, regex path and exact path. For example /admin\n    3. Regex path    : A regex string starts with '^'. For example ^.*/add$\n    4. Exact path  : Starts with '=', represents a single request path . For example =/register\n", null=True, size=None),
        ),
        migrations.AlterField(
            model_name='usergroupauthorization',
            name='paths',
            field=authome.models.models.ArrayField(base_field=models.CharField(max_length=512), blank=True, help_text="\nList all possible paths separated by new line character.\nThe following lists all valid options in the checking order\n    1. All path      : *\n    2. Prefix path   : the paths except All path, regex path and exact path. For example /admin\n    3. Regex path    : A regex string starts with '^'. For example ^.*/add$\n    4. Exact path  : Starts with '=', represents a single request path . For example =/register\n", null=True, size=None),
        ),
    ]
