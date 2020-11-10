from django.http import HttpResponseRedirect, HttpResponse, HttpResponseForbidden,JsonResponse 
from django.template.response import TemplateResponse
from django.contrib.auth import login, logout
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.http import urlencode
from django.utils import timezone
from ipware.ip import get_client_ip
import json
import base64
import hashlib
import re
import traceback
import logging
from datetime import datetime

from django.contrib.auth.models import User
from authome.models import can_access,UserToken
from authome.cache import cache

logger = logging.getLogger(__name__)

def parse_basic(basic_auth):
    if not basic_auth:
        raise Exception('Missing credentials')
    match = re.match('^Basic\\s+([a-zA-Z0-9+/=]+)$', basic_auth)
    if not match:
        raise Exception('Malformed Authorization header')
    basic_auth_raw = base64.b64decode(match.group(1)).decode('utf-8')
    if ':' not in basic_auth_raw:
        raise Exception('Missing password')
    return basic_auth_raw.split(":", 1)

NOT_AUTHORIZED_RESPONSE = HttpResponseForbidden()
def check_authorization(request,useremail):
    """
    Return None if authorized;otherwise return Authorized failed response
    """
    domain = request.headers.get("x-upstream-server-name") or request.get_host()
    path = request.headers.get("x-upstream-request-uri") or request.path
    try:
        path = path[:path.index("?")]
    except:
        pass

    
    if can_access(useremail,domain,path):
        logger.debug("User({}) can access https://{}{}".format(useremail,domain,path))
        return None
    else:
        logger.debug("User({}) can't access https://{}{}".format(useremail,domain,path))
        return NOT_AUTHORIZED_RESPONSE


def _populate_response(request,f_cache,cache_key,user,session_key=None):
    response_contents = {
        'email': user.email,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name
    }
    if session_key:
        response_contents['session_key'] = session_key

    content = json.dumps(response_contents)

    headers = response_contents
    headers["full_name"] = u"{}, {}".format(user.last_name,user.first_name)
    headers["logout_url"] = "/sso/auth_logout"

    # cache response
    cache_headers = dict()
    for key, val in headers.items():
        key = "X-" + key.replace("_", "-")
        cache_headers[key] = val
    # cache authentication entries
    response = f_cache(cache_key,[content, cache_headers])
    logger.debug("cache the sso auth data for the user({}) with key({})".format(user.email,cache_key))

    return response

def _auth(request):
    if not request.user.is_authenticated:
        logger.debug("User is not authenticated")
        return None

    logger.debug("The user({}) is authenticated".format(request.user.email))

    res = check_authorization(request,request.user.email)
    if res:
        #user has no permission to access this url
        return res

    user = request.user
    auth_key = cache.get_auth_key(user.email,request.session.session_key)
    response = cache.get_auth(auth_key)

    if response:
        logger.debug("The user({}) is authenticated and cached".format(request.user.email))
        return response
    else:
        return _populate_response(request,cache.set_auth,auth_key,user,request.session.session_key)

AUTH_REQUIRED_RESPONSE = HttpResponse(status=401)
AUTH_REQUIRED_RESPONSE.content = "Authentication required"

@csrf_exempt
def auth(request):
    res = _auth(request)
    if not res:
        return AUTH_REQUIRED_RESPONSE
    else:
        return res

BASIC_AUTH_REQUIRED_RESPONSE = HttpResponse(status=401)
BASIC_AUTH_REQUIRED_RESPONSE["WWW-Authenticate"] = 'Basic realm="Please login with your email address and access token"'
BASIC_AUTH_REQUIRED_RESPONSE.content = "Basic auth required"

@csrf_exempt
def auth_token(request):
    """
    First authenticate the token and then fall back to session authentication
    """
    auth_token = request.META.get('HTTP_AUTHORIZATION').strip() if 'HTTP_AUTHORIZATION' in request.META else ''
    if not auth_token:
        #not provide basic auth data,check whether session is already authenticated or not.
        res = _auth(request)
        if res:
            #already authenticated
            return res
        else:
            #require the user to provide credential using basic auth
            return BASIC_AUTH_REQUIRED_RESPONSE

    username, token = parse_basic(auth_token)

    auth_token_key = cache.get_token_auth_key(username,token) 
    response= cache.get_token_auth(auth_token_key)
    if response:
        #already authenticated with token auth data, using the token auth data instead of current session authentication data (if have)
        useremail = response['X-email']
        if settings.CHECK_AUTH_TOKEN_PER_REQUEST:
            user = User.objects.get(email__iexact=useremail)
            if not user.token or not user.token.is_valid(token):
                #token is invalid, fallback to session authentication
                cache.delete_token_auth(auth_token_key)
                res = _auth(request)
                if res:
                    #already authenticated
                    logger.debug("Failed to authenticate the user({}) with token, fall back to use session authentication".format(username))
                    return res
                else:
                    #require the user to provide credential using basic auth
                    logger.debug("Failed to authenticate the user({}) with token".format(username))
                    return BASIC_AUTH_REQUIRED_RESPONSE

            useremail = user.email

        request.session.modified = False
            
        res = check_authorization(request,useremail)
        if res:
            #not authorized
            return res
        else:
            return response
    else:
        try:
            if "@" in username:
                user = User.objects.get(email__iexact=username)
            else:
                user = User.objects.filter(username__iexact=username).first()
                if not user:
                    logger.debug("User({}) doesn't exist".format(username))
                    return BASIC_AUTH_REQUIRED_RESPONSE

            if request.user.is_authenticated and user.email == request.user.email:
                #the user of the token auth is the same as the authenticated session user;use the session authentication data directly
                return _auth(request)

            if user.token and user.token.is_valid(token):
                logger.debug("Succeed to authenticate the user({}) with token".format(username))
                request.user = user
                request.session.modified = False

                response = _populate_response(request,cache.set_token_auth,auth_token_key,user)
                res = check_authorization(request,user.email)
                if res:
                    return res
                else:
                    return response
            else:
                res = _auth(request)
                if res:
                    #already authenticated
                    logger.debug("Failed to authenticate the user({}) with token, fall back to use session authentication".format(username))
                    return res
                else:
                    #require the user to provide credential using basic auth
                    logger.debug("Failed to authenticate the user({}) with token".format(username))
                    return BASIC_AUTH_REQUIRED_RESPONSE

        except Exception as e:
            return BASIC_AUTH_REQUIRED_RESPONSE


def logout_view(request):
    logout(request)
    return HttpResponseRedirect(
        'https://login.windows.net/common/oauth2/logout')


def home(request):
    next_url = request.GET.get('next', None)
    if not request.user.is_authenticated:
        url = reverse('social:begin', args=['azuread-oauth2'])
        if next_url:
            url += '?{}'.format(urlencode({'next': next_url}))
        return HttpResponseRedirect(url)
    if next_url:
        return HttpResponseRedirect('https://{}'.format(next_url))
    return HttpResponseRedirect(reverse('auth'))

@csrf_exempt
def profile(request):
    response = _auth(request)
    if not response:
        return AUTH_REQUIRED_RESPONSE

    user = request.user

    content = json.loads(response.content)
    current_ip,routable = get_client_ip(request)
    content['client-logon-ip'] = current_ip
    try:
        token = UserToken.objects.filter(user = user).first()
        if not token or not token.enabled:
            content["access_token_error"] = "Access token is not enabled, please ask administrator to enable."
        elif not token.token:
            content["access_token_error"] = "Access token is created, please ask administrator to create"
        elif token.is_expired:
            content["access_token"] = token.token
            content["access_token_created"] = timezone.localtime(token.created).strftime("%Y-%m-%d %H:%M:%S")
            content["access_token_expired"] = token.expired.strftime("%Y-%m-%d")
            content["access_token_error"] = "Access token is expired, please ask administroator to recreate"
        else:
            content["access_token"] = token.token
            content["access_token_created"] = timezone.localtime(token.created).strftime("%Y-%m-%d %H:%M:%S")
            if token.expired:
                content["access_token_expired"] = token.expired.strftime("%Y-%m-%d 23:59:59")
    except Exception as ex:
        logger.error("Failed to get access token for the user({}).{}".format(user.email,traceback.format_exc()))
        content["access_token_error"] = str(ex)

    res = HttpResponse(content=json.dumps(content),status=response.status_code,content_type="application/json")
    res['X-client-logon-ip'] = current_ip
    for name,value in response.items():
        res[name] = value

    return res

