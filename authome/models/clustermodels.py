import logging

from django.conf import settings
from django.db import models
from django.db.models.signals import pre_delete, pre_save, post_save, post_delete
from django.utils import timezone
from django.dispatch import receiver

from ..  import exceptions
from ..cache import cache,get_defaultcache,get_usercache
from .models import UserGroup,UserGroupAuthorization,CustomizableUserflow,IdentityProvider,User,UserToken

logger = logging.getLogger(__name__)

defaultcache = get_defaultcache()

class Auth2Cluster(models.Model):
    clusterid = models.CharField(max_length=32,unique=True,null=False)
    endpoint = models.CharField(max_length=512,null=False)
    default = models.BooleanField(default=False,editable=False)
    usergroup_lastrefreshed = models.DateTimeField(editable=False,null=True)
    usergroupauthorization_lastrefreshed = models.DateTimeField(editable=False,null=True)
    userflow_lastrefreshed = models.DateTimeField(editable=False,null=True)
    idp_lastrefreshed = models.DateTimeField(editable=False,null=True)
    last_heartbeat = models.DateTimeField(editable=False)
    registered = models.DateTimeField(auto_now_add=timezone.now)
    modified = models.DateTimeField(editable=False,auto_now=True)

    class Meta:
        verbose_name_plural = "{}auth2 clusters".format(" " * 0)

    @classmethod
    def register(cls):
        if settings.DEFAULT_AUTH2_CLUSTER:
            #update the previous default cluster server to non cluster server
            cls.objects.filter(default=True).exclude(clusterid=settings.AUTH2_CLUSTERID).update(default=False,modified=timezone.localtime())
        cls.objects.update_or_create(clusterid=settings.AUTH2_CLUSTERID,defaults={
            "endpoint" : settings.AUTH2_CLUSTER_ENDPOINT,
            "default" : settings.DEFAULT_AUTH2_CLUSTER,
            "last_heartbeat":timezone.localtime(),
            "modified":timezone.localtime()
        })


    def __str__(self):
        return self.clusterid

def refresh_cache_wrapper(cls,column):
    _original_func = getattr(cls,"refresh_cache")
    def _func(cls):
        try:
            refreshtime = _original_func()
            setattr(cache.current_auth2_cluster,column,refreshtime)
            cache.current_auth2_cluster.save(update_fields=[column,"modified"])
        except:
            logger.error("Failed to save the latest refresh time({1}) to auth2 cluster '{0}'".format(cache.current_auth2_cluster.cluserid,column))
        return refreshtime
    return _func

def change_wrapper(cls):
    _original_func = getattr(cls.get_model_change_cls(),"change")
    def _func(cls,timeout=None,localonly=False):
        _original_func(timeout)
        if not localonly:
            changed_clusters,not_changed_clusters,failed_clusters = cache.config_changed(cls) 
            if failed_clusters:
                raise exceptions.Auth2ClusterException("Failed to send change event of the model '{0}'  to some cluseters.{1} ".format(cls.__name__,["{}:{}".format(c,str(e)) for c,e in failed_clusters]))

    return _func

if settings.AUTH2_CLUSTER_ENABLED:
    #auth2 cluster feature is enabled
    #Override method 'fresh_cache' of models to update cache's last refresh time in model 'Auth2Cluster'
    for cls,column in [(UserGroup,"usergroup_lastrefreshed"),(UserGroupAuthorization,"usergroupauthorization_lastrefreshed"),(CustomizableUserflow,"userflow_lastrefreshed"),(IdentityProvider,"idp_lastrefreshed")]:
        setattr(cls,"refresh_cache",classmethod(refresh_cache_wrapper(cls,column)))

    if defaultcache:
        #Override method 'change' of class 'ModelChange' to send a the model change event to other auth2 clusters.
        for cls in [UserGroup,UserGroupAuthorization,CustomizableUserflow,IdentityProvider]:
            setattr(cls.get_model_change_cls(),"change",classmethod(change_wrapper(cls)))

    class UserListener4Cluster(object):
        @staticmethod
        def user_changed(instance):
            failed_clusters = cache.user_changed(instance.id)
            if failed_clusters:
                raise exceptions.Auth2ClusterException("Failed to send change event of the user({1}<{0}>) to some cluseters.{2} ".format(instance.id,instance.email,["{}:{}".format(c,str(e)) for c,e in failed_clusters]))
            else:
                logger.debug("Sucessfully send change event of the user({1}<{0}>) to other cluseters ".format(instance.id,instance.email))
                pass
        """
        @staticmethod
        @receiver(post_save, sender=User)
        def post_save_user(sender,instance,created,**kwargs):
            if not created:
                UserListener4Cluster.user_changed(instance)
        """

        @staticmethod
        @receiver(post_delete, sender=User)
        def post_delete_user(sender,instance,**kwargs):
            UserListener4Cluster.user_changed(instance)

    class UserTokenListener4Cluster(object):
        @staticmethod
        def usertoken_changed(instance):
            user = instance.user
            changed_clusters,not_changed_clusters,failed_clusters = cache.usertoken_changed(user.id)
            if failed_clusters:
                raise exceptions.Auth2ClusterException("Failed to send token change event of the user({1}<{0}>) to some cluseters.{2} ".format(user.id,user.email,["{}:{}".format(c,str(e)) for c,e in failed_clusters]))
            else:
                logger.debug("Sucessfully send token change event of the user({1}<{0}>) to other cluseters ".format(user.id,user.email))
                pass
    
        @staticmethod
        @receiver(post_save, sender=UserToken)
        def post_save_usertoken(sender,instance,created,**kwargs):
            if not created:
                UserTokenListener4Cluster.usertoken_changed(instance)
    
        @staticmethod
        @receiver(post_delete, sender=UserToken)
        def post_delete_usertoken(sender,instance,**kwargs):
            UserTokenListener4Cluster.usertoken_changed(instance)
    


    
