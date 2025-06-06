import logging
from datetime import timedelta
import traceback
import string

from django.conf import settings
from django.utils import timezone
from django.contrib.auth import SESSION_KEY as USER_SESSION_KEY

from django.contrib.sessions.backends.base import (
    CreateError, SessionBase, UpdateError
)
from django.core.cache import caches
from django.utils.crypto import  get_random_string

from .. import models
from .. import utils
from .. import performance
from authome.models import DebugLog

logger = logging.getLogger(__name__)

if settings.SESSION_CACHES == 0:
    get_firstsessioncache = lambda :None
elif settings.SESSION_CACHES == 1:
    get_firstsessioncache = lambda :caches[settings.SESSION_CACHE_ALIAS]
else:
    get_firstsessioncache = lambda :caches["session0"]

firstsessioncache = get_firstsessioncache()

VALID_DIGITIAL_CHARS = string.digits + string.ascii_letters + "~#?*&^%$/!<>(){}[]"
#VALID_DIGITIAL_CHARS = string.digits + string.ascii_letters
VALID_KEY_CHARS = VALID_DIGITIAL_CHARS

def convert_decimal(number,decimal=len(VALID_DIGITIAL_CHARS)):
    remain_number = number
    converted_number = None
    while remain_number is not None:
        if remain_number < decimal:
            c = VALID_DIGITIAL_CHARS[remain_number]
            remain_number = None
        else:
            c =  VALID_DIGITIAL_CHARS[remain_number % decimal]
            remain_number = int(remain_number / decimal)

        if converted_number:
            converted_number =  c + converted_number
        else:
            converted_number =  c

    return converted_number

def to_decimal(s,decimal):
    number = 0
    s = s.lower()
    l = len(s)
    for i in range(l):
        c = s[i]
        p = l - 1 - i
        if p == 0:
            number += VALID_DIGITIAL_CHARS.index(c)
        else:
            number += VALID_DIGITIAL_CHARS.index(c) * pow(decimal,p)

    return number

def expire_at_redis(cache,key,value,timeout):
    cache.expire_at(key,timezone.now() + timeout)

def expire_at_others(cache,key,value,timeout):
    cache.set(key,value,timeout.seconds)

def expire_at(cache,value,timeout):
    try:
        cache._set_expire_at(value,timeout)
    except AttributeError as ex:
        if hasattr(cache.__class__,'expire_at'):
            setattr(cache.__class__,'_set_expire_at',expire_at_redis)
        else:
            setattr(cache.__class__,'_set_expire_at',expire_at_others)
        cache._set_expire_at(value,timeout)
        
class _AbstractSessionStore(SessionBase):
    COOKIEDOMAIN = settings.SESSION_COOKIE_DOMAIN[1:] if (settings.SESSION_COOKIE_DOMAIN and settings.SESSION_COOKIE_DOMAIN[0] == ".") else settings.SESSION_COOKIE_DOMAIN
    COOKIEDOMAINSUFFIX = settings.SESSION_COOKIE_DOMAIN if (settings.SESSION_COOKIE_DOMAIN and settings.SESSION_COOKIE_DOMAIN[0]) == "." else ".{}".format(settings.SESSION_COOKIE_DOMAIN)
    
    cache_key_prefix =  "session:"
    _idppk = None
    expired_session_key = None
    _samedomain = None
    _cookie_domain = None
    _cookie_changed = False

    def __init__(self,session_key=None,request=None,cookie_domain=None):
        self._request = request
        if cookie_domain:
            self._cookie_domain = cookie_domain
        if session_key and "-" in session_key:
            #authenticated session, get the idp pk from session key
            try:
                self._idppk = to_decimal(session_key[0:session_key.index("-")],36)
            except:
                #not a valid session key
                session_key = None
        super().__init__(session_key)
        self._source_session_key = session_key

    @property
    def samedomain(self):
        """
        Return True if the request's host is the domain of the session cookie or subdomain of the session cookie
        """
        if self._samedomain is None:
            if self._request:
                host = self._request.get_host()
                self._samedomain = host.endswith(self.COOKIEDOMAINSUFFIX) or host == self.COOKIEDOMAIN
            else:
                self._samedomain = True

        return self._samedomain

    @classmethod
    def is_cookie_domain_match(cls,request,cookie_domain):
        """
        Check whether the cookie_domain which is embeded in cookie value match with the required domain, if not match, will delete the cookie and let user login again.
        This is used to address the issue: if SESSION_COOKIE_DOMAINS changed, session cookie domain for non-dbca domain can be changed, and that will cause browser can keep multiple session cookies for the same non-dbca app. this logic
        is try to identify this case, and remove the undesired cookies from browser
        should consider the scenario: backend uses user's session cookie to access other application even in different domain.
        If cookie domain is null, that cookie should come from dbca domain, always return True
        If request host is belonging the cookie domain, Return True if the cookie domain match the required domain otherwise return False
        If requst host is not belonging the cookie domain, means the cookie is used by backend to access the other application which in in other domain, return True

        """
        if not cookie_domain:
            #from dbca domain
            return True
        host = request.get_host() 
        if host[len(cookie_domain) * -1:] == cookie_domain and (len(cookie_domain) == len(host) or host[len(cookie_domain) * -1 -1] == "."):
            #belong the same domain
            domain = settings.GET_SESSION_COOKIE_DOMAIN(host) or host
            return domain == cookie_domain
        else:
           #don't belong the same domain. cross-domain accessing
           return True

    @classmethod
    def get_cookie_domain(cls,request):
        """
        Always return a domain of the current session cookie. 
        used for log.
        """
        host = request.get_host() 
        if host.endswith(cls.COOKIEDOMAINSUFFIX) or host == cls.COOKIEDOMAIN:
            return settings.SESSION_COOKIE_DOMAIN
        else:
            return settings.GET_SESSION_COOKIE_DOMAIN(host) or host

    @property
    def cookie_domain(self):
        """
        Return the domain to populate the session cookie object
        """
        if self.samedomain:
            return settings.SESSION_COOKIE_DOMAIN
        else:
            return settings.GET_SESSION_COOKIE_DOMAIN(self._request.get_host())

    @property
    def current_cookie_domain(self):
        """
        Return the domain of the current session cookie 
        Used for deleting current session cookie from browser
        """
        if self._cookie_domain:
            if self._request.get_host() == self._cookie_domain:
                return None
            else:
                return self._cookie_domain
        elif self.samedomain:
            return settings.SESSION_COOKIE_DOMAIN
        else:
            return settings.GET_SESSION_COOKIE_DOMAIN(self._request.get_host())

    @property
    def cookie_value(self):
        #should be only called if session is not empty
        if self._cookie_domain:
            return "{}{}{}".format(self.session_key or self.expired_session_key,settings.SESSION_COOKIE_DOMAIN_SEPARATOR,self._cookie_domain)
        else:
            return self.session_key or self.expired_session_key

    @property
    def cookie_changed(self):
        return self._cookie_changed or self._source_session_key != (self._session_key or self.expired_session_key)

    @property
    def expireat(self):
        """
        Return expire time; return None if never expired.
        """
        try:
            sessioncache = self._get_cache()
            ttl = sessioncache.ttl(self.cache_key)
            return timezone.localtime() + timedelta(seconds=ttl)
        except:
            return None
    
    @property
    def ttl(self):
        """
        Return expire time; return None if never expired or not supported.
        """
        try:
            sessioncache = self._get_cache()
            return sessioncache.ttl(self.cache_key)
        except:
            return None

    @property
    def idpid(self):
        """
        Return idp id, get idp from session, if failed , try to get it from session key;
        Return None if not found
        """
        idpid = self.get("idp") 
        if idpid:
            return idpid
        elif self._idppk:
            idp = models.IdentityProvider.get_idp(self._idppk)
            if idp:
                return idp.idp
            else:
                return None

    def flush(self):
        self.expired_session_key = None
        super().flush()

    def is_empty(self):
        """
        prevent django from deleting the expired session cookie which can be used to automatically signout.
        """
        if self.expired_session_key:
            return False
        else:
            return super().is_empty()

    def _get_cache(self,session_key=None):
        return None

    @property
    def cache_key(self):
        return self.cache_key_prefix + self._get_or_create_session_key()

    @classmethod
    def get_cache_key(cls,session_key):
        return cls.cache_key_prefix + session_key


    def get_session_cookie_age(self,session_key=None):
        """
        Return different session cookie age for authenticated session and anonymous session
        """
        if not session_key:
            session_key = self._session_key
        if session_key and "-" in session_key:
            return settings.SESSION_COOKIE_AGE
        else:
            return settings.GUEST_SESSION_AGE

    def get_session_age(self):
        """
        Get the session age 
        1. if session has timeout, use timeout as session age
        2. for authenticated session, use setting 'SESSION_AGE'
        3. for anonymous session, use setting 'GUEST_SESSION_AGE'
        """
        try:
            timeout = self._session_cache.get("session_timeout")
            if timeout:
                return timeout
        except:
            pass

        if self._session_key and "-" in self._session_key:
            return settings.SESSION_AGE
        else:
            return settings.GUEST_SESSION_AGE

    def get_expiry_age(self, **kwargs):
        """
        Return sesson cookie age
        """
        return self.get_session_cookie_age()

    def get_cache_key(self,session_key=None):
        if not session_key:
            session_key = self.session_key
        return self.cache_key_prefix + session_key

    def create(self):
        # Because a cache can fail silently (e.g. memcache), we don't know if
        # we are failing to create a new session because of a key collision or
        # because the cache is missing. So we try for a (large) number of times
        # and then raise an exception. That's the risk you shoulder if using
        # cache backing.
        try:
            performance.start_processingstep("create_session")
            for i in range(10000):
                self._session_key = self._get_new_session_key()
                try:
                    self.save(must_create=True)
                except CreateError:
                    continue
                self.modified = True
                return
            raise RuntimeError(
                "Unable to create a new session key. "
                "It is likely that the cache is unavailable.")

        finally:
            performance.end_processingstep("create_session")
            logger.debug("Add a new session({}) for {} into cache".format(self.session_key,self.get(USER_SESSION_KEY,'GUEST')))
            pass


    def save(self, must_create=False):
        try:
            performance.start_processingstep("save_session_to_cache")
            if self.session_key is None:
                return self.create()
            if must_create:
                func = self._get_cache().add
            else:
                func = self._get_cache().set
            result = func(self.cache_key,
                          self._get_session(no_load=must_create),
                          self.get_session_age())
            if must_create and not result:
                raise CreateError
        finally:
            performance.end_processingstep("save_session_to_cache")
            logger.debug("Save a session({}) for {} into cache".format(self.session_key,self.get(USER_SESSION_KEY,'GUEST')))
            pass

    def exists(self, session_key):
        try:
            performance.start_processingstep("check_exists_in_cache")
            return bool(session_key) and (self.cache_key_prefix + session_key) in self._get_cache(session_key)
        finally:
            performance.end_processingstep("check_exists_in_cache")
            pass

    def delete(self, session_key=None):
        try:
            performance.start_processingstep("delete_session_from_cache")
            if session_key is None:
                if self.session_key is None:
                    return
                session_key = self.session_key
            self._get_cache(session_key).delete(self.cache_key_prefix + session_key)
        finally:
            performance.end_processingstep("delete_session_from_cache")
            logger.debug("Delete a session({}) from cache".format(session_key or self.session_key))
            pass

    def populate_session_key(self,idpid,timekey):
        if idpid:
            return "{3}-{1}{0}{2}".format(
                timekey,
                get_random_string(15, VALID_KEY_CHARS),
                get_random_string(15, VALID_KEY_CHARS),
                idpid
            )
        else:
            return "{1}{0}{2}".format(
                timekey,
                get_random_string(15, VALID_KEY_CHARS),
                get_random_string(15, VALID_KEY_CHARS)
            )

        

    @classmethod
    def clear_expired(cls):
        pass


    def _get_new_session_key(self):
        "Return session key that isn't being used."
        cls = self.__class__
        idpid = self.get("idp")
        if idpid:
            idp = models.IdentityProvider.get_idp(idpid)
            idpid = convert_decimal(idp.id,36)
        now = timezone.localtime()
        timekey = convert_decimal((now.timetuple().tm_yday - 1) * 86400 + now.hour * 3600 + now.minute * 60 + now.second)
        while True:
            session_key = self.populate_session_key(idpid,timekey)

            if not self.exists(session_key):
                logger.debug("Create a new session key {}".format(session_key))
                return session_key


if settings.SESSION_CACHES == 1:
    class _SessionStoreWithMultiCacheSupport(_AbstractSessionStore):
        def __init__(self,session_key=None,request=None,cookie_domain=None):
            self._cache = caches[settings.SESSION_CACHE_ALIAS]
            super().__init__(session_key=session_key,request=request,cookie_domain=cookie_domain)

        def _get_cache(self,session_key=None):
            return self._cache
else:
    class _SessionStoreWithMultiCacheSupport(_AbstractSessionStore):
        def _get_cache(self,session_key=None):
            if not session_key:
                session_key = self.session_key
            return caches[settings.SESSION_CACHE_ALIAS(session_key)]

if settings.PREVIOUS_SESSION_CACHES > 0:
    if settings.PREVIOUS_SESSION_CACHES == 1:
        class _SessionStoreWithPreviousCacheSupport(_SessionStoreWithMultiCacheSupport):
            def __init__(self,session_key=None,request=None,cookie_domain=None):
                self._previous_cache = caches[settings.PREVIOUS_SESSION_CACHE_ALIAS]
                super().__init__(session_key=session_key,request=request,cookie_domain=cookie_domain)
       
            def _get_previous_cache(self,session_key=None):
                return self._previous_cache
    
    elif settings.PREVIOUS_SESSION_CACHES > 1:
        class _SessionStoreWithPreviousCacheSupport(_SessionStoreWithMultiCacheSupport):
            def _get_previous_cache(self,session_key):
                return caches[settings.PREVIOUS_SESSION_CACHE_ALIAS(session_key)]

    class SessionStore(_SessionStoreWithPreviousCacheSupport):
        previous_cache_key_prefix =  "session:"
        @property
        def previous_cachekey(self):
            return self.previous_cache_key_prefix + self.session_key

        def load(self):
            """
            Load the session from cache; and reset expire time if cache is redis and session has property 'session_timeout'
            """
            try:
                performance.start_processingstep("load_session")
                sessioncache = self._get_cache()
                cachekey = self.cache_key
                try:
                    performance.start_processingstep("load_session_from_cache")
                    session_data = sessioncache.get(cachekey)
                finally:
                    performance.end_processingstep("load_session_from_cache")
                    pass
                if not session_data:
                    #Try to find the session from previous sesstion cache
                    try:
                        performance.start_processingstep("migrate_session_from_previous_cache")
                        previous_cachekey = self.previous_cachekey
                        previous_sessioncache = self._get_previous_cache(self.session_key)
                        try:
                            performance.start_processingstep("get_session_from_previous_cache")
                            session_data = previous_sessioncache.get(previous_cachekey)
                        finally:
                            performance.end_processingstep("get_session_from_previous_cache")
                            pass
    
                        if session_data:
                            #migrate the session from previous cache to current cache
                            timeout = session_data.get("session_timeout")
                            if timeout and session_data.get(USER_SESSION_KEY):
                                try:
                                    performance.start_processingstep("save_session_to_cache")
                                    sessioncache.set(cachekey,session_data,timeout)
                                finally:
                                    performance.end_processingstep("save_session_to_cache")
                                    pass
                            else:
                                try:
                                    performance.start_processingstep("get_ttl_from_previous_cache")
                                    ttl = previous_sessioncache.ttl(previous_cachekey)
                                except:
                                    ttl = None
                                finally:
                                    performance.end_processingstep("get_ttl_from_previous_cache")
                                    pass

                                try:
                                    performance.start_processingstep("save_session_to_cache")
                                    if ttl:
                                        sessioncache.set(cachekey,session_data,ttl)
                                    else:
                                        sessioncache.set(cachekey,session_data,self.get_session_age())
                                finally:
                                    performance.end_processingstep("save_session_to_cache")
                                    pass
                            #mark the session as migrated session in previous cache
                            try:
                                performance.start_processingstep("delete_session_from_previous_cache")
                                previous_sessioncache.delete(previous_cachekey)
                            finally:
                                performance.end_processingstep("delete_session_from_previous_cache")
                                pass
                            DebugLog.log(DebugLog.MOVE_SESSION,None,None,self._session_key,utils.get_source_session_cookie(self._request),message="Move a session({0}) from previous redis server({1}) to redis server({2})".format(self._session_key,previous_sessioncache.server4print,sessioncache.server4print),target_session_cookie=self._session_key,userid=(session_data or {}).get(USER_SESSION_KEY),request=self._request)
                        else:
                            try:
                                performance.start_processingstep("load_session_from_cache")
                                session_data = sessioncache.get(cachekey)
                                DebugLog.log_if_true(session_data,DebugLog.SESSION_ALREADY_MOVED,None,None,self._session_key,self._session_key,message="Session({0}) has already moved from previous redis server({1}) to redis server({2})".format(self._session_key,previous_sessioncache.server4print,sessioncache.server4print),target_session_cookie=self._session_key,userid=(session_data or {}).get(USER_SESSION_KEY),request=self._request)
                                DebugLog.log_if_true(not session_data,DebugLog.MOVE_NONEXIST_SESSION,None,None,self._session_key,self._session_key,message="No need to move a non-existing session({0}) from previous redis server({1})".format(self._session_key,previous_sessioncache.server4print),target_session_cookie=self._session_key,request=self._request)
                            finally:
                                performance.end_processingstep("load_session_from_cache")
                                pass
                    finally:
                        performance.end_processingstep("migrate_session_from_previous_cache")
                        pass
        
                else:
                    timeout = session_data.get("session_timeout")
                    if timeout and session_data.get(USER_SESSION_KEY):
                        try:
                            performance.start_processingstep("set_session_timeout")
                            sessioncache.expire(cachekey,timeout)
                        except:
                            pass
                        finally:
                            performance.end_processingstep("set_session_timeout")
                            pass
            except :
                logger.error("Failed to load session.{}".format(traceback.format_exc()))
                #rasing exception will cause error "'NoneType' object has no attribute 'get'" in session  middleware
                DebugLog.warning(DebugLog.ERROR,None,None,self._session_key,utils.get_source_session_cookie(self._request),message="Failed to load session({}).{}".format(self._session_key,traceback.format_exc()),request=self._request)
                self._session_key = None
                return  {}
            finally:
                performance.end_processingstep("load_session")
                pass

            if session_data :
                return session_data
    
            if self._session_key and "-" in self._session_key and self.samedomain:
                #this is a authenticated session key, keep it for logout feature
                self.expired_session_key = self._session_key
            self._session_key = None
            return {}
else:
    class SessionStore(_SessionStoreWithMultiCacheSupport):
        def load(self):
            """
            Load the session from cache; and reset expire time if cache is redis and session has property 'session_timeout'
            """
            try:
                performance.start_processingstep("load_session")
                sessioncache = self._get_cache()
                cachekey = self.cache_key
                try:
                    performance.start_processingstep("load_session_from_cache")
                    session_data = sessioncache.get(cachekey)
                finally:
                    performance.end_processingstep("load_session_from_cache")
                    pass
                if session_data:
                    timeout = session_data.get("session_timeout")
                    if timeout and session_data.get(USER_SESSION_KEY):
                        try:
                            performance.start_processingstep("set_session_timeout")
                            sessioncache.expire(cachekey,timeout)
                        except:
                            pass
                        finally:
                            performance.end_processingstep("set_session_timeout")
                            pass
            except :
                logger.error("Failed to load session.{}".format(traceback.format_exc()))
                #rasing exception will cause error "'NoneType' object has no attribute 'get'" in session  middleware
                DebugLog.warning(DebugLog.ERROR,None,None,self._session_key,utils.get_source_session_cookie(self._request),message="Failed to load session({}).{}".format(self._session_key,traceback.format_exc()),request=self._request)
                self._session_key = None
                return  {}
            finally:
                performance.end_processingstep("load_session")
                pass

            if session_data :
                return session_data
    
            if self._session_key and "-" in self._session_key and self.samedomain:
                #this is a authenticated session key, keep it for logout feature
                self.expired_session_key = self._session_key
            self._session_key = None
            return {}

