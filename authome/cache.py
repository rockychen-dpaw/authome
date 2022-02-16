import logging
import signal
import traceback
import os
import atexit
import time
from datetime import datetime, timedelta
from collections import OrderedDict

from django.conf import settings
from django.utils import timezone
from django.core.cache import caches

from django_redis import get_redis_connection

from . import utils 

logger = logging.getLogger(__name__)

if settings.USER_CACHES == 0:
    get_usercache = lambda userid:None
elif settings.USER_CACHES == 1:
    get_usercache = lambda userid:caches[settings.USER_CACHE_ALIAS]
else:
    get_usercache = lambda userid:caches[settings.USER_CACHE_ALIAS(userid)]

if settings.CACHE_SERVER:
    get_defaultcache = lambda :caches['default']
else:
    get_defaultcache = lambda :None



defaultcache = get_defaultcache()

class TaskRunable(object):
    def can_run(self,dt=None):
        """
        Return True if the task can run;otherwise return False
        """
        return False


class IntervalTaskRunable(TaskRunable):
    """
    A interval based task runable class.
    Interval is the number of seconds between the task run
    A day can be divided by a valid interval.
    """
    def __init__(self,name,interval):
        self._name = name
        self._interval = interval
        self._next_time = None

    _seconds_4_nextrun = staticmethod(lambda seconds_in_day,interval: seconds_in_day + (interval - seconds_in_day % interval))
    def can_run(self,dt=None):
        if dt:
            dt = timezone.localtime(dt)
        else:
            dt = timezone.localtime()

        if not self._next_time:
            #not run before, don't run before the next scheduled runtime.
            today = datetime(dt.year,dt.month,dt.day,tzinfo=dt.tzinfo)
            self._next_time = today + timedelta(seconds = self._seconds_4_nextrun((dt - today).seconds,self._interval))
            #logger.debug("No need to run task({}), next runtime is {}".format(self._name,self._next_time.strftime("%Y-%m-%d %H:%M:%S")))
            return False
        elif self._next_time > dt:
            #Don't run before the next scheduled runtime
            #logger.debug("No need to run task({}), next runtime is {}".format(self._name,self._next_time.strftime("%Y-%m-%d %H:%M:%S")))
            return False
        else:
            #Run now, and set the next scheudled runtime.
            today = datetime(dt.year,dt.month,dt.day,tzinfo=dt.tzinfo)
            self._next_time = today + timedelta(seconds = self._seconds_4_nextrun((dt - today).seconds,self._interval))
            logger.debug("Run task({}) now, next runtime is {}".format(self._name,self._next_time.strftime("%Y-%m-%d %H:%M:%S")))
            return True

    @property
    def next_runtime(self):
        if not self._next_time:
            self.can_run()
        return self._next_time


class HourListTaskRunable(TaskRunable):
    """
    A hour list base task runable class
    The hour list is the list of hour(0-23) when the task should run

    """
    def __init__(self,name,hours):
        self._name = name
        self._next_time = None
        self._index = None
        self._hours = hours
        if len(self._hours) == 1:
            self._timediffs = [timedelta(hours=24)]
        else:
            self._timediffs = []

            i = 0
            while i < len(self._hours):
                if i == 0:
                    self._timediffs.append(timedelta(hours=24 + self._hours[i] - self._hours[-1]))
                else:
                    self._timediffs.append(timedelta(hours=self._hours[i] - self._hours[i-1]))
                i += 1

    def can_run(self,dt=None):
        if dt:
            dt = timezone.localtime(dt)
        else:
            dt = timezone.localtime()

        if not self._next_time:
            #not run before, don' run before the next scheduled time
            self._index = 0
            self._next_time = datetime(dt.year,dt.month,dt.day,tzinfo=dt.tzinfo) + timedelta(hours=self._hours[0])
            while self._next_time <= dt:
                if self._index == len(self._hours) - 1:
                    self._index = 0
                else:
                    self._index += 1
                self._next_time += self._timediffs[self._index]
            #logger.debug("No need to run task({}), next runtime is {}".format(self._name,self._next_time.strftime("%Y-%m-%d %H:%M:%S")))
            return False
        elif self._next_time > dt:
            #don't run before the next sheduled time
            #logger.debug("No need to run task({}), next runtime is {}".format(self._name,self._next_time.strftime("%Y-%m-%d %H:%M:%S")))
            return False
        else:
            #run and set the next scheduled time
            while self._next_time <= dt:
                if self._index == len(self._hours) - 1:
                    self._index = 0
                else:
                    self._index += 1
                self._next_time += self._timediffs[self._index]
            logger.debug("Run task({}) now, next runtime is {}".format(self._name,self._next_time.strftime("%Y-%m-%d %H:%M:%S")))
            return True

    @property
    def next_runtime(self):
        if not self._next_time:
            self.can_run()
        return self._next_time


if settings.CACHE_USER_IN_MEMORY or settings.CACHE_SESSION_IN_MEMORY or settings.DEPLOY_CONFIG_REALTIME:
    import threading

    class PubSubWorkerThread(threading.Thread):
        def __init__(self, pubsub,channels):
            super().__init__(name="PubSubWorkerThread",daemon=True)
            self.pubsub = pubsub
            self._running = threading.Event()
            self.channels = channels

        def run(self):
            if self._running.is_set():
                return
            self._running.set()
            while self._running.is_set():
                try:
                    self.pubsub.ping()
                    if not self.pubsub.subscribed:
                        raise Exception("Not subscribed")
                except:
                    while True:
                        try:
                            self.pubsub.subscribe(**self.channels)
                            logger.info("Successfully subscribe the  redis channels({}) again".format(",".join([k for k in self.channels.keys()])))
                            break
                        except Exception as ex:
                            logger.error("Failed to subscribe the  redis channels({}).{}".format(",".join([k for k in self.channels.keys()]),str(ex)))
                            #wait 1 seconds try again.
                            time.sleep(1)
                try:
                    logger.debug("Start to listen the  redis channels({}).".format(",".join([k for k in self.channels.keys()])))
                    for msg in self.pubsub.listen():
                        pass
                except Exception as e:
                    pass
            logger.debug("Stop to listen redis channels.")
    
        def stop(self):
            # trip the flag so the run loop exits. the run loop will
            # close the pubsub connection, which disconnects the socket
            # and returns the connection to the pool.
            if not self.pubsub.connection:
                self.join()
                return

            logger.debug("Begin to shutdown PubSubWorkderThread")
            self._running.clear()
            self.pubsub.close()
            self.join()
            logger.debug("End to shutdown PubSubWorkderThread")

    def signal_handler(s,exit_handler):
        _original_handler = signal.getsignal(s)
        def _handler(signum, frame):
            exit_handler()
            _original_handler(signum,frame)
        return _handler

            
class _MemoryCache(object):
    """
    Local memory cache
    """
    def __init__(self):
        super().__init__()
        #model UserGroup cache
        self._usergrouptree = None
        self._usergroups = None
        self._dbca_group = None
        self._public_group = None
        self._usergrouptree_size = None
        self._usergrouptree_ts = None

        #model UserGroupAuthorization cache
        self._usergroupauthorization = None
        self._usergroupauthorization_size = None
        self._usergroupauthorization_ts = None

        #model CustomizableUserflow cache
        self._userflows = None
        self._userflows_map = {}
        self._defaultuserflow = None
        self._userflows_size = None
        self._userflows_ts = None

        #IdentityProvider cache
        self._idps = None
        self._idps_size = None
        self._idps_ts = None

        #user authorization cache
        self._user_authorization_map = OrderedDict() 
        self._user_authorization_map_ts = None
    
        #user authentication cache
        self._auth_map = OrderedDict() 
        self._auth_map_ts = None
        #user basic authentication cache
        self._basic_auth_map = OrderedDict() 
        self._basic_auth_map_ts = None

        #the map between email and groups
        self._groupskey_map = {}
        self._email_groups_map = OrderedDict()
        self._public_email_groups_map = OrderedDict()
        self._groups_map = {}
        self._emailgroups_ts = None

        channels = self.get_channels()

        if channels:
            redis_client = get_redis_connection('pubsub')
            redis_pubsub = redis_client.pubsub()

            self.subscriber = PubSubWorkerThread(redis_pubsub,channels)

            self.subscriber.start()
            atexit.register(self.subscriber.stop)
            signal.signal(signal.SIGTERM, signal_handler(signal.SIGTERM,self.subscriber.stop))
            signal.signal(signal.SIGINT, signal_handler(signal.SIGINT,self.subscriber.stop))
            logger.debug("pid={}".format(os.getpid()))
    

    def get_channels(self):
        channels = {}
        if settings.CACHE_USER_IN_MEMORY:
            self._user_map = OrderedDict()
            channels["user"] = self._del_user

        if settings.CACHE_SESSION_IN_MEMORY:
            self._session_map = OrderedDict()
            channels["session"] = self._del_session

        if settings.DEPLOY_CONFIG_REALTIME:
            channels["model"] = self._model_changed

        return channels

    def _model_changed(self,msg):
        try:
            data = msg["data"]
            publisher,modelname = data.split("@")
            if modelname == "usergroup":
                self.refresh_usergroups()
            elif modelname == "usergroupauthorization":
                self.refresh_usergroupauthorization()
            elif modelname == "customizableuserflow":
                self.refresh_userflow_cache()
            elif modelname == "identityprovider":
                self.refresh_idp_cache()
            else:
                logger.error("Model changed event is not supported".format(modelname))

        except Exception as ex:
            logger.error("{} : Model changed event({}) - Failed to refresh model data;{}".format(utils.get_serverid(),data,str(ex)))

    def get_user(self,userid):
        data = self._user_map.get(userid)
        if data:
            if data[1] and data[1] < timezone.now():
                #expired
                del self._user_map[userid]
                return None
            else:
                return data[0]
        else:
            return None
    def set_user(self,user,expireat=None):
        self._user_map[user.id] = (user,expireat)
        self._enforce_maxsize("user map",self._user_map,settings.USER_CACHE_SIZE)

    def del_user(self,userid):
        try:
            del self._user_map[userid]
            logger.debug("{} : Remove user({}) from memory cache".format(utils.get_serverid(),userid))
        except:
            pass

    def _del_user(self,msg):
        try:
            data = msg["data"]
            publisher,userid = data.split("@",1)
            userid = int(userid)
            if publisher == utils.get_serverid():
                logger.debug("{} : This user event({}) is sent by itself, ignore.".format(utils.get_serverid(),data))
                pass
            else:
                if userid in self._user_map:
                    del self._user_map[userid]
                    logger.debug("{} : User event({}) - Remove outdated user({}) from memory cache".format(utils.get_serverid(),data,userid))
                else:
                    logger.debug("{} : User event({}) - The outdated User({}) is not in memory cache".format(utils.get_serverid(),data,userid))
                    pass

        except Exception as ex:
            logger.error("{} : User event({}) - Failed to remove outdated user({}) from memory cache;{}".format(utils.get_serverid(),data,userid,str(ex)))


    def get_session(self,session_key):
        data = self._session_map.get(session_key)
        if data:
            if data[1] and data[1] < timezone.now():
                #expired
                del self._session_map[session_key]
                return None
            else:
                return data[0]
        else:
            return None

    def set_session(self,session_key,session,expireat=None):
        self._session_map[session_key] = (session,expireat)
        self._enforce_maxsize("session map",self._session_map,settings.SESSION_CACHE_SIZE)
        logger.debug("Cache the session({}) with exipre time({}) in memory".format(session_key,expireat))

    def del_session(self,session_key):
        try:
            del self._session_map[session_key]
            logger.debug("{} : Remove session({}) from memory cache".format(utils.get_serverid(),session_key))
        except:
            pass

    def _del_session(self,msg):
        try:
            data = msg["data"]
            publisher,session_key = data.split("@")
            if publisher == utils.get_serverid():
                logger.debug("{} : This session event({}) is sent by itself, ignore.".format(utils.get_serverid(),data))
                pass
            else:
                if session_key in self._session_map:
                    del self._session_map[session_key]
                    logger.debug("{} : Session event({}) - Remove outdated session({}) from memory cache".format(utils.get_serverid(),data,session_key))
                else:
                    logger.debug("{} : Session event({}) - The outdated session({}) is not in memory cache".format(utils.get_serverid(),data,session_key))
                    pass

        except Exception as ex:
            logger.error("{} : Session event({}) - Failed to remove outdated session({}) from memory cache;{}".format(utils.get_serverid(),data,session_key,str(ex)))


    @property
    def usergrouptree(self):
        if not self._usergrouptree:
            logger.error("The usergrouptree cache is Empty, Try to refresh the data to bring the cache back to normal state")
            self.refresh_usergroups()

        return self._usergrouptree

    @property
    def usergroups(self):
        if not self._usergroups:
            logger.error("The usergroups cache is Empty, Try to refresh the data to bring the cache back to normal state")
            self.refresh_usergroups()

        return self._usergroups

    @property
    def dbca_group(self):
        return self._dbca_group

    @property
    def public_group(self):
        return self._public_group

    @usergrouptree.setter
    def usergrouptree(self,value):
        if value:
            self._usergrouptree,self._usergroups,self._public_group,self._dbca_group,self._usergrouptree_size,self._usergrouptree_ts = value
        else:
            self._usergrouptree,self._usergroups,self._public_group,self._dbca_group,self._usergrouptree_size,self._usergrouptree_ts = None,None,None,None,None,None

    @property
    def usergroupauthorization(self):
        if not self._usergroupauthorization:
            logger.error("The usergroupauthorization cache is Empty, Try to refresh the data to bring the cache back to normal state")
            self.refresh_usergroupauthorization()

        return self._usergroupauthorization

    @usergroupauthorization.setter
    def usergroupauthorization(self,value):
        if value:
            self._usergroupauthorization,self._usergroupauthorization_size,self._usergroupauthorization_ts = value
        else:
            self._usergroupauthorization,self._usergroupauthorization_size,self._usergroupauthorization_ts = None,None,None

    def get_authorizations(self,groupskey,domain):
        return self._user_authorization_map.get((groupskey,domain))

    def set_authorizations(self,groupskey,domain,authorizations):
        self._user_authorization_map[(groupskey,domain)] = authorizations
        self._enforce_maxsize("groups authorization map",self._user_authorization_map,settings.AUTHORIZATION_CACHE_SIZE)

    @property
    def idps(self):
        return self._idps

    @idps.setter
    def idps(self,value):
        if value:
            self._idps,self._idps_size,self._idps_ts = value
        else:
            self._idps,self._idps_size,self._idps_ts = None,None,None

    @property
    def userflows(self):
        return self._userflows

    def get_userflow(self,domain=None):
        """
        Get the userflow configured for that domain, if can't find, return default userflow
        if domain is None, return default userflow
        """
        if domain:
            userflow = self._userflows_map.get(domain)
            if not userflow:
                for o in self._userflows:
                    if o.request_domain.match(domain):
                        userflow = o
                        break
                userflow = userflow or self._defaultuserflow
                self._userflows_map[domain] = userflow
            logger.debug("Find the userflow({1}) for domain '{0}'".format(domain,userflow.domain))
            return userflow
        else:
            return self._defaultuserflow

    @userflows.setter
    def userflows(self,value):
        if value:
            self._userflows,self._defaultuserflow,self._userflows_size,self._userflows_ts = value
        else:
            self._userflows,self._defaultuserflow,self._userflows_size,self._userflows_ts = None,None,None,None

        self._userflows_map.clear()

    def get_groups_key(self,groups):
        """
        Use the same key instance for the same groups
        Return the group  key for the groups
        """
        key = list(g.id for g in groups)
        key.sort()
        key = tuple(key)
        groupskey = self._groupskey_map.get(key)
        if not groupskey:
            self._groupskey_map[key] = key
            return key
        else:
            return groupskey

    def get_email_groupskey(self,email):
        return self._email_groups_map.get(email) or self._public_email_groups_map.get(email)

    def set_email_groups(self,email,groups):
        """
        cache the email and groups mapping
        """
        #get the key of the groups
        groupskey = self.get_groups_key(groups[0])

        #set the map between email and groupskey
        if len(groups[0]) > 1 or groups[0][0] != self._public_group:
            self._email_groups_map[email] = groupskey
            self._enforce_maxsize("email groups map",self._email_groups_map,settings.EMAIL_GROUPS_CACHE_SIZE)
        else:
            self._public_email_groups_map[email] = groupskey
            self._enforce_maxsize("public email groups map",self._public_email_groups_map,settings.PUBLIC_EMAIL_GROUPS_CACHE_SIZE)

        #set the map between groupskey and groups
        if groupskey not in self._groups_map:
            self._groups_map[groupskey] = groups

    def get_email_groups(self,email):
        #try to get the groupskey from email_groups and then from public email groups
        groupskey = self._email_groups_map.get(email) or self._public_email_groups_map.get(email)

        if not groupskey:
            return None

        return self._groups_map.get(groupskey)

    def get_auth_key(self,email,session_key):
        return session_key

    def get_auth(self,key,last_modified=None):
        """
        Return the populated http reponse
        """
        data = self._auth_map.get(key)
        if data:
            if timezone.now() <= data[2] and (not last_modified or data[1] >= last_modified):
                return data[0]
            else:
                del self._auth_map[key]
                return None
        else:
            return None

    def set_auth(self,key,response):
        """
        cache the auth response content and return the populated http response
        """
        now = timezone.now()
        self._auth_map[key] = [response,now,now + settings.AUTH_CACHE_EXPIRETIME]

        self._enforce_maxsize("auth map",self._auth_map,settings.AUTH_CACHE_SIZE)

    def update_auth(self,key,response):
        """
        cache the updated auth response content and return the populated http response
        """
        data = self._auth_map.get(key)
        if data:
            data[0] = response
        else:
            self._auth_map[key] = [response,timezone.now() + settings.AUTH_CACHE_EXPIRETIME]

    def delete_auth(self,key):
        try:
            del self._auth_map[key]
        except:
            #not found
            pass

    def get_basic_auth_key(self,name_or_email,token):
        return (name_or_email,token)

    def get_basic_auth(self,key):
        """
        Return the populated http reponse
        """
        data = self._basic_auth_map.get(key[0])
        if data:
            if data[1] == key[1] and timezone.now() <= data[2]:
                #token is matched and not expired
                return data[0]
            else:
                #token is not matched, remove the data
                del self._basic_auth_map[key[0]]
                return None
        else:
            #not cached token found
            return None

    def set_basic_auth(self,key,response):
        """
        cache the auth token response content and return the populated http response
        """
        self._basic_auth_map[key[0]] = [response,key[1],timezone.now() + settings.AUTH_BASIC_CACHE_EXPIRETIME]

        self._enforce_maxsize("token auth map",self._basic_auth_map,settings.BASIC_AUTH_CACHE_SIZE)

    def update_basic_auth(self,key,response):
        """
        cache the updated auth token response content and return the populated http response
        """
        data = self._basic_auth_map.get(key[0])
        if data:
            if data[1] == key[1] and timezone.now() <= data[2]:
                #token is matched
                data[0] = response
            else:
                #token is not matched, remove the old one, add a new one
                del self._basic_auth_map[key[0]]
                self._basic_auth_map[key[0]] = [response,key[1],timezone.now() + settings.AUTH_BASIC_CACHE_EXPIRETIME]
        else:
            #not cached token found
            self._basic_auth_map[key[0]] = [response,key[1],timezone.now() + settings.AUTH_BASIC_CACHE_EXPIRETIME]

    def delete_basic_auth(self,key):
        try:
            del self._basic_auth_map[key[0]]
        except:
            #not found
            pass

    def _enforce_maxsize(self,name,cache,max_size):
        #clean the oversized data
        oversize = len(cache) - max_size
        if oversize > 0:
            while oversize > 0:
                cache.popitem(last=False)
                oversize -= 1
            logger.debug("Remove earliest data from cache {0} to enforce the maximum cache size {1}".format(name,max_size))

    def _remove_expireddata(self,name,cache):
        #clean the expired data
        cleaned_datas = 0
        now = timezone.now()
        more_expired_data = True
        expired_keys =[]
        index = 0
        now = timezone.now()
        for k,v in cache.items():
            if now > v[-1]:
                index += 1
            else:
                break
        if index == 0:
            return
        elif index == len(cache):
            cache.clear()
        else:
            while index > 0:
                cache.popitem(last=False)
                index -= 1
            logger.debug("Remove expired datas from cache {0}".format(name))

    def refresh_usergroups(self,force=False):
        from .models import UserGroupChange,UserGroup
        if (force or not self._usergrouptree or UserGroupChange.is_changed()):
            logger.debug("UserGroup was changed, Reload it." if self._usergrouptree else "Load UserGroup data")
            self._user_authorization_map.clear()
            self._user_authorization_map_ts = timezone.now()
            self._email_groups_map.clear()
            self._public_email_groups_map.clear()
            self._groups_map.clear()
            self._emailgroups_ts = timezone.now()
            if len(self._groupskey_map) >= 2000:
                #groupskey map is too big, clear it.
                self._groupskey_map.clear()
            #reload group trees
            UserGroup.refresh_cache()
        else :
            logger.debug("UserGroup is not changed, no need to reload.")
            pass

    def refresh_usergroupauthorization(self,force=False):
        from .models import UserGroupAuthorizationChange,UserGroupAuthorization
        if (force or not self._usergroupauthorization or UserGroupAuthorizationChange.is_changed()):
            logger.debug("UserGroupAuthorization was changed, Reload it." if self._usergroupauthorization else "Load UserGroupAuthorization data")
            self._user_authorization_map.clear()
            self._user_authorization_map_ts = timezone.now()
            #reload user group requests
            UserGroupAuthorization.refresh_cache()
        else:
            logger.debug("UserGroupAuthorization is not changed, no need to reload")
            pass

    def refresh_idp_cache(self,force=False):
        from .models import IdentityProviderChange,IdentityProvider
        if force or not self._idps or  IdentityProviderChange.is_changed():
            logger.debug("IdentityProvider was changed, Reload it." if self._idps else "Load IdentityProvider data")
            IdentityProvider.refresh_cache()
        else:
            logger.debug("IdentityProvider is not changed, no need to reload.")
            pass
    

    def refresh_userflow_cache(self,force=False):
        from .models import CustomizableUserflowChange,CustomizableUserflow
        if force or not self._userflows or CustomizableUserflowChange.is_changed():
            logger.debug("CustomizableUserflow was changed,Reload it." if self._userflows else "Load CustomizableUserflow data")
            CustomizableUserflow.refresh_cache()
        else:
            logger.debug("CustomizableUserflow is not changed, no need to reload.")
            pass

    @property
    def status(self):
        result = {}
        result["UserGroup"] = {
            "grouptree_size":None if self.usergrouptree is None else len(self.usergrouptree),
            "groupsize":None if self.usergroups is None else len(self.usergroups),
            "dbcagroup":str(self.dbca_group),
            "publicgroup":str(self.public_group),
            "latest_refresh_time":utils.format_datetime(self._usergrouptree_ts),
        }
    
        result["UserGroupAuthorization"] = {
            "usergroupauthorization_size":None if self.usergroupauthorization is None else len(self.usergroupauthorization),
            "latest_refresh_time":utils.format_datetime(self._usergroupauthorization_ts),
        }
    
        result["CustomizableUserflow"] = {
            "userflow_size":None if self.userflows is None else len(self.userflows),
            "userflowmap_size":None if self._userflows_map is None else len(self._userflows_map),
            "defaultuserflow":str(self._defaultuserflow),
            "latest_refresh_time":utils.format_datetime(self._userflows_ts),
        }
    
    
        result["IdentityProvider"] = {
            "identityprovider_size":None if self.idps is None else len(self.idps),
            "latest_refresh_time":utils.format_datetime(self._idps_ts),
        }
    
        result["userauthorizationmap"] = {
            "authorizationmap_size":None if self._user_authorization_map is None else len(self._user_authorization_map),
            "authorizationmap_maxsize":settings.AUTHORIZATION_CACHE_SIZE,
            "latest_clean_time":utils.format_datetime(self._user_authorization_map_ts),
        }
    
        result["userauthenticationmap"] = {
            "authenticationmap_size":None if self._auth_map is None else len(self._auth_map),
            "authenticationmap_maxsize":settings.AUTH_CACHE_SIZE,
            "latest_clean_time":utils.format_datetime(self._auth_map_ts),
        }
    
        result["basicauthmap"] = {
            "basicauthmap_size":None if self._basic_auth_map is None else len(self._basic_auth_map),
            "basicauthmap_maxsize":settings.BASIC_AUTH_CACHE_SIZE,
            "latest_clean_time":utils.format_datetime(self._basic_auth_map_ts),
        }
    
        result["usergrouplist"] = {
            "groupskey_size":None if self._groupskey_map is None else len(self._groupskey_map),
            "usergroupsmap_size":None if self._email_groups_map is None else len(self._email_groups_map),
            "usergroupsmap_maxsize":settings.EMAIL_GROUPS_CACHE_SIZE,
            "publicusergroupsmap_size":None if self._public_email_groups_map is None else len(self._public_email_groups_map),
            "publicusergroupsmap_maxsize":settings.PUBLIC_EMAIL_GROUPS_CACHE_SIZE,
            "groupsmap_size":None if self._groups_map is None else len(self._groups_map),
            "latest_clean_time":utils.format_datetime(self._emailgroups_ts),
        }
    
        return result

    @property
    def healthy(self):
        if not self.usergrouptree :
            return (False,"The UserGroup tree cache is empty")

        if not self.usergroups:
            return (False,"The UserGroup cache is empty")

        if not self.dbca_group:
            return (False,"The cached dbca user group is None")

        if not self.public_group:
            return (False,"The cached public user group is None")

        if not self.usergroupauthorization:
            return (False,"The UserGroupAuthorization cache is empty.")

        if not self.userflows:
            return (False,"The CustomizableUserflow cache is empty")

        if not self._defaultuserflow:
            return (False,"The cached default userflow is None")

        if not self.idps:
            return (False,"The IdentityProvider cache is empty")

        if self._user_authorization_map is None :
            return (False,"The user authorization cache is None")
            
        if len(self._user_authorization_map) > (settings.AUTHORIZATION_CACHE_SIZE + 100) :
            return (False,"The size({}) of the user authorization cache exceed the maximum cache size({})".format(len(self._user_authorization_map), settings.AUTHORIZATION_CACHE_SIZE))
            
        if self._auth_map is None  :
            return (False,"The user authentication cache is None")
    
        if len(self._auth_map) > settings.AUTH_CACHE_SIZE + 100 :
            return (False,"The size({}) of the user authentication cache exceed the maximum cache size({})".format(len(self._auth_map), settings.AUTH_CACHE_SIZE))
    
        if self._basic_auth_map is None :
            return (False,"The basic authentication cache is None")
    
        if len(self._basic_auth_map) > settings.BASIC_AUTH_CACHE_SIZE + 100 :
            return (False,"The size({}) of the basic authentication cache exceed the maximum cache size({})".format(len(self._basic_auth_map), settings.BASIC_AUTH_CACHE_SIZE))
    
        if self._groupskey_map is None :
            return (False,"The groups key map cache is None")
    
        if self._email_groups_map is None:
            return (False,"The email groups map cache is None")
    
        if len(self._email_groups_map) > settings.EMAIL_GROUPS_CACHE_SIZE + 100:
            return (False,"The size({}) of the user groups map cache exceed the maximum cache size({})".format(len(self._email_groups_map), settings.EMAIL_GROUPS_CACHE_SIZE))
    
        if self._public_email_groups_map is None:
            return (False,"The public user groups map cache is None")
    
        if len(self._public_email_groups_map) > settings.PUBLIC_EMAIL_GROUPS_CACHE_SIZE + 100:
            return (False,"The size({}) of the public user groups map cache exceed the maximum cache size({})".format(len(self._public_email_groups_map), settings.PUBLIC_EMAIL_GROUPS_CACHE_SIZE))
    
        if self._groups_map is None:
            return (False,"The groups map cache is None")
    
        return (True,"ok")

if settings.AUTH_CACHE_CLEAN_HOURS:
    class _MemoryCacheWithCleanAuth(_MemoryCache):
        """
        Local memory cache
        """
        def __init__(self):
            super().__init__()
    
            #The runable task to clean authenticaton map and basic authenticaton map
            self._auth_cache_clean_time = HourListTaskRunable("authentication cache",settings.AUTH_CACHE_CLEAN_HOURS)
    
    
        def set_auth(self,key,response):
            """
            cache the auth response content and return the populated http response
            """
            super().set_auth(key,response)
            self.clean_auth_cache()
    
        def set_basic_auth(self,key,response):
            """
            cache the auth token response content and return the populated http response
            """
            super().set_basic_auth(key,response)
            self.clean_auth_cache()
    
        def clean_auth_cache(self,force=False):
            if self._auth_cache_clean_time.can_run() or force:
                self._auth_map.clear()
                self._auth_map_ts = timezone.now()
    
                self._basic_auth_map.clear()
                self._basic_auth_map_ts = timezone.now()
    
        @property
        def status(self):
            result = super().status
            result["userauthenticationmap"]["next_clean_time"] = utils.format_datetime(self._auth_cache_clean_time.next_runtime)
        
            result["basicauthmap"]["next_clean_time"] = utils.format_datetime(self._auth_cache_clean_time.next_runtime)
        
            return result

    MemoryCache = _MemoryCacheWithCleanAuth
else:
    MemoryCache = _MemoryCache

if not settings.DEPLOY_CONFIG_REALTIME:
    class RepeatedlySyncedMemoryCache(MemoryCache):
        """
        Local memory cache
        """
        def __init__(self):
            super().__init__()
    
            #The runable task to check UserGroup, UserAuthorization and UserGroupAuthorication cache
            self._authorization_cache_check_time = IntervalTaskRunable("authorization cache",settings.AUTHORIZATION_CACHE_CHECK_INTERVAL) if settings.AUTHORIZATION_CACHE_CHECK_INTERVAL > 0 else HourListTaskRunable("authorization cache",settings.AUTHORIZATION_CACHE_CHECK_HOURS)
    
            #The runable task to check CustomizableUserflow cache
            self._userflow_cache_check_time = IntervalTaskRunable("customizable userflow cache",settings.USERFLOW_CACHE_CHECK_INTERVAL) if settings.USERFLOW_CACHE_CHECK_INTERVAL > 0 else HourListTaskRunable("customizable userflow cache",settings.USERFLOW_CACHE_CHECK_HOURS)
    
            #The runable task to check IdentityProvider cache
            self._idp_cache_check_time = IntervalTaskRunable("idp cache",settings.IDP_CACHE_CHECK_INTERVAL) if settings.IDP_CACHE_CHECK_INTERVAL > 0 else HourListTaskRunable("idp cache",settings.IDP_CACHE_CHECK_HOURS)
    
        @_MemoryCache.dbca_group.getter
        def dbca_group(self):
            self.refresh_authorization_cache()
            return self._dbca_group
    
        @_MemoryCache.public_group.getter
        def public_group(self):
            self.refresh_authorization_cache()
            return self._public_group
    
        def get_authorizations(self,groupskey,domain):
            """
            During authorization, this method is the first method to be invoked, and then the methods 'userauthrizations','usergrouptree' and 'usergroupauthorization' will be invoked if required.
            So only call method 'refresh_authorization_cache' in this method and ignore in other methods 'userauthrizations','usergrouptree' and 'usergroupauthorization'.
            """
            self.refresh_authorization_cache()
            return self._user_authorization_map.get((groupskey,domain))
    
        @_MemoryCache.idps.getter
        def idps(self):
            self.refresh_idp_cache()
            return self._idps
    
        @_MemoryCache.userflows.getter
        def userflows(self):
            self.refresh_userflow_cache()
            return self._userflows
    
        def get_userflow(self,domain=None):
            """
            Get the userflow configured for that domain, if can't find, return default userflow
            if domain is None, return default userflow
            """
            self.refresh_userflow_cache()
            return super().get_userflow(domain=domain)
    
    
        def refresh_authorization_cache(self,force=False):
            if self._authorization_cache_check_time.can_run() or force:
                self.refresh_usergroups(force)
                self.refresh_usergroupauthorization(force)
    
        def refresh_idp_cache(self,force=False):
            from .models import IdentityProviderChange,IdentityProvider
            if not self._idps:
                logger.debug("Load IdentityProvider data")
                self._idp_cache_check_time.can_run()
                IdentityProvider.refresh_cache()
            elif self._idp_cache_check_time.can_run() or force:
                if IdentityProviderChange.is_changed():
                    logger.debug("IdentityProvider was changed, Reload it.")
                    IdentityProvider.refresh_cache()
                else:
                    logger.debug("IdentityProvider is not changed, no need to reload")
                    pass
    
    
        def refresh_userflow_cache(self,force=False):
            from .models import CustomizableUserflowChange,CustomizableUserflow
            if not self._userflows:
                logger.debug("Load CustomizableUserflow data")
                self._userflow_cache_check_time.can_run()
                CustomizableUserflow.refresh_cache()
            elif self._userflow_cache_check_time.can_run() or force:
                if CustomizableUserflowChange.is_changed():
                    logger.debug("CustomizableUserflow was changed, Reload it.")
                    CustomizableUserflow.refresh_cache()
                else:
                    logger.debug("CustomizableUserflow is not changed, no need to reload")
                    pass
    
    
        @property
        def status(self):
            result = super().status
            result["UserGroup"]["next_check_time"] = utils.format_datetime(self._authorization_cache_check_time.next_runtime)
            result["UserGroupAuthorization"]["next_check_time"] = utils.format_datetime(self._authorization_cache_check_time.next_runtime)
            result["CustomizableUserflow"]["next_check_time"] = utils.format_datetime(self._userflow_cache_check_time.next_runtime)
            result["IdentityProvider"]["next_check_time"] = utils.format_datetime(self._idp_cache_check_time.next_runtime)
            result["userauthorizationmap"]["next_check_time"] = utils.format_datetime(self._authorization_cache_check_time.next_runtime)
            result["usergrouplist"]["next_check_time"] = utils.format_datetime(self._authorization_cache_check_time.next_runtime)
        
            return result

    cache = RepeatedlySyncedMemoryCache()
else:
    
    cache = MemoryCache()

