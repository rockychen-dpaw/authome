
from django import forms
from django.contrib.postgres.forms import SimpleArrayField
from django.utils.safestring import mark_safe

from  .models import UserGroup,UserGroupAuthorization,UserAuthorization
from .widgets import (ReadonlyWidget,text_readonly_widget)

def get_help_text(model_class,field):
    return mark_safe("<pre>{}</pre>".format(model_class._meta.get_field(field).help_text))

class UserGroupForm(forms.ModelForm):
    users = SimpleArrayField(forms.CharField(required=False),delimiter="\n",widget=forms.Textarea(attrs={"style":"width:80%","rows":10}),help_text=get_help_text(UserGroup,"users"))
    excluded_users = SimpleArrayField(forms.CharField(required=False),delimiter="\n",required=False,widget=forms.Textarea(attrs={"style":"width:80%","rows":10}),help_text=get_help_text(UserGroup,"excluded_users"))
    class Meta:
        model = UserGroup
        fields = "__all__"
        

class UserGroupAuthorizationForm(forms.ModelForm):
    domain = forms.CharField(required=True,widget=forms.TextInput(attrs={"style":"width:80%"}),help_text=get_help_text(UserGroupAuthorization,"domain"))
    paths = SimpleArrayField(forms.CharField(required=False),delimiter="\n",required=False,widget=forms.Textarea(attrs={"style":"width:80%","rows":10}),help_text=get_help_text(UserGroupAuthorization,"paths"))
    excluded_paths = SimpleArrayField(forms.CharField(required=False),delimiter="\n",required=False,widget=forms.Textarea(attrs={"style":"width:80%","rows":10}),help_text=get_help_text(UserGroupAuthorization,"excluded_paths"))

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance :
            if self.instance.created:
                if "usergroup" in self.fields :
                    self.fields["usergroup"].widget = ReadonlyWidget(lambda d:UserGroup.objects.get(id = int(d)) if d else "")

    class Meta:
        model = UserGroupAuthorization
        fields = "__all__"

class UserAuthorizationForm(forms.ModelForm):
    domain = forms.CharField(required=True,widget=forms.TextInput(attrs={"style":"width:80%"}),help_text=get_help_text(UserAuthorization,"domain"))
    paths = SimpleArrayField(forms.CharField(required=False),delimiter="\n",required=False,widget=forms.Textarea(attrs={"style":"width:80%","rows":10}),help_text=get_help_text(UserAuthorization,"paths"))
    excluded_paths = SimpleArrayField(forms.CharField(required=False),delimiter="\n",required=False,widget=forms.Textarea(attrs={"style":"width:80%","rows":10}),help_text=get_help_text(UserAuthorization,"excluded_paths"))

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance :
            if self.instance.created:
                if "user" in self.fields :
                    self.fields["user"].widget = text_readonly_widget

    class Meta:
        model = UserAuthorization
        fields = "__all__"
        



