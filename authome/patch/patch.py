import logging
import traceback

from django.contrib import auth
from django.utils import timezone

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.handlers import exception
from django.http import HttpRequest,HttpResponseForbidden

from social_core.exceptions import AuthException

from ..models import User,UserToken
from authome.models import DebugLog
from ..cache import get_usercache
from ..exceptions import UserDoesNotExistException,InvalidDomainException,Auth2ClusterException
from .. import utils

from .. import performance

logger = logging.getLogger(__name__)

anonymoususer = auth.models.AnonymousUser()

"""
override django builtin method _get_user
To improve the perforance and debug, provide different function in each scenario, (the combination of debug and usercache)

"""
if settings.USER_CACHE_ALIAS:
    def load_user(userid):
        """
        Return the user model instance associated with the given request session.
        If no user is retrieved, return an instance of `AnonymousUser`.
        """
        user = None
        try:
            #try to get user data from user cache
            userkey = settings.GET_USER_KEY(userid)
            usercache = get_usercache(userid)
            
            performance.start_processingstep("get_user_from_cache")
            try:
                user = usercache.get(userkey)
            except:
                DebugLog.warning(DebugLog.ERROR,None,None,None,None,"Failed to load the user from cache .{}".format(traceback.format_exc()))
            finally:
                performance.end_processingstep("get_user_from_cache")
                pass

            if not user:
                #Can't find the user in user cache, retrieve it from database
                performance.start_processingstep("fetch_user_from_db")
                try:
                    user = User.objects.get(pk = userid)
                finally:
                    performance.end_processingstep("fetch_user_from_db")
                    pass
                #cache the user object into user cache
                performance.start_processingstep("set_user_to_cache")
                try:
                    usercache.set(userkey,user,settings.STAFF_CACHE_TIMEOUT if user.is_staff else settings.USER_CACHE_TIMEOUT)
                except:
                    DebugLog.warning(DebugLog.ERROR,None,None,None,None,"Failed to set the user to cache .{}".format(traceback.format_exc()))
                finally:
                    performance.end_processingstep("set_user_to_cache")
                    pass

        except KeyError:
            pass
        except ObjectDoesNotExist as ex:
            #user does not exist.
            #if the current request is auth2_auth, return AUTH_REQUIRED_RESPONSE
            #if the current request is auth2_optional, return AUTH_NOT_REQUIRED_RESPONSE
            #otherwise. logout the user
            raise UserDoesNotExistException()

        return user or anonymoususer

    def load_usertoken(user):
        """
        Return user's access token
        Return None if user has not access token
        """
        usertoken = None
        try:
            #Try to find the access token from user cache, user and user's access token should be cached at the same redis server
            usertokenkey = settings.GET_USERTOKEN_KEY(user.id)
            usercache = get_usercache(user.id)
            
            performance.start_processingstep("get_usertoken_from_cache")
            try:
                usertoken = usercache.get(usertokenkey)
            except:
                pass
            finally:
                performance.end_processingstep("get_usertoken_from_cache")
                pass

            if not usertoken:
                #Access token not found in the user cache, retrieve it from database
                performance.start_processingstep("fetch_usertoken_from_db")
                try:
                    usertoken = UserToken.objects.get(user = user)
                finally:
                    performance.end_processingstep("fetch_usertoken_from_db")
                    pass

                #cache the access token in the user cache
                performance.start_processingstep("set_usertoken_to_cache")
                try:
                    usercache.set(usertokenkey,usertoken,settings.STAFF_CACHE_TIMEOUT if user.is_staff else settings.USER_CACHE_TIMEOUT)
                except:
                    pass
                finally:
                    performance.end_processingstep("set_usertoken_to_cache")
                    pass

        except KeyError:
            pass
        except ObjectDoesNotExist as ex:
            pass

        return usertoken

else:
    def load_user(userid):
        """
        Return the user model instance associated with the given request session.
        If no user is retrieved, return an instance of `AnonymousUser`.
        """
        user = None
        try:
            performance.start_processingstep("fetch_user_from_db")
            try:
                user = User.objects.get(pk = userid)
            finally:
                performance.end_processingstep("fetch_user_from_db")
                pass
        except KeyError:
            pass
        except ObjectDoesNotExist as ex:
            #user does not exist.
            #if the current request is auth2_auth, return AUTH_REQUIRED_RESPONSE
            #if the current request is auth2_optional, return AUTH_NOT_REQUIRED_RESPONSE
            #otherwise. logout the user
            raise UserDoesNotExistException()

        return user or anonymoususer

    def load_usertoken(userid):
        """
        Return user's access token
        Return None if user has not access token
        """
        usertoken = None
        try:
            performance.start_processingstep("fetch_usertoken_from_db")
            try:
                usertoken = UserToken.objects.get(user = userid)
            finally:
                performance.end_processingstep("fetch_usertoken_from_db")
                pass
        except KeyError:
            pass
        except ObjectDoesNotExist as ex:
            pass

        return usertoken

def _get_user(request):
    """
    Return the user associated to the request session;
    Return anonymoususer if no user is associated
    """
    try:
        userid = auth._get_user_session_key(request)
    except:
        return anonymoususer

    return load_user(userid)
    

auth.get_user = _get_user


def get_response_for_exception():
    original_handler = exception.response_for_exception
    def _response_for_exception(request, exc):
        from .. import views
        if isinstance(exc, AuthException):
            return views.handler400(request,exc)
        elif isinstance(exc, Auth2ClusterException):
            return views.handler400(request,exc)
        elif isinstance(exc, InvalidDomainException):
            return HttpResponseForbidden(str(exc))
        else:
            try:
                useremail = request.user.email
            except:
                useremail = None
            DebugLog.warning(
                DebugLog.ERROR,utils.get_source_lb_hash_key(request),
                utils.get_source_clusterid(request),
                utils.get_source_session_key(request),
                utils.get_source_session_cookie(request),
                useremail=useremail,
                message="Failed to process request.{}".format("\n".join(traceback.format_exception(type(exc),exc,exc.__traceback__)))
            )
            
            return original_handler(request,exc)
    return _response_for_exception

exception.response_for_exception = get_response_for_exception()


def get_host():
    original_get_host = HttpRequest.get_host
    def _init_get_host(self):
        if self.path in ("/sso/auth","/sso/auth_basic","/sso/auth_optional","/sso/auth_basic_optional"):
            host = self.headers.get("x-upstream-server-name")
            if host:
                logger.debug("Customize the request method 'get_host' to get the request from request header 'x-upstream-server-name'; if not found, then use the default logic.")
                HttpRequest.get_host = _get_host
                return host
            else:
                logger.debug("The request method 'get_host' is not customized, reset it to the default logic.")
                HttpRequest.get_host = original_get_host
                return original_get_host(self)
        else:
            return self.headers.get("x-upstream-server-name") or original_get_host(self)

    def _get_host(self):
        return self.headers.get("x-upstream-server-name") or original_get_host(self)

    return _init_get_host

HttpRequest.get_host = get_host()
