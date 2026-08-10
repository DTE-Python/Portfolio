#!/usr/bin/env python3
import datetime, os, sys, asyncio, time, hmac, hashlib, base64, json

from flask import Flask, request, redirect, session, Response, render_template



import requests as Requests

from requests_oauthlib import OAuth2Session

#from twitchio.ext import eventsub, commands

from flask.json import jsonify

from flask_apscheduler import APScheduler

app = Flask(__name__)



scheduler = APScheduler()

AUTHORIZATION_BASE_URL  = "https://id.twitch.tv/oauth2/authorize"
TOKEN_URL               = "https://id.twitch.tv/oauth2/token"
VALIDATION_URL          = "https://id.twitch.tv/oauth2/validate"
EVENTSUB_URL            = "https://api.twitch.tv/helix/eventsub/subscriptions"

TWITCH_MESSAGE_ID           = 'Twitch-Eventsub-Message-Id'.lower()
TWITCH_MESSAGE_TIMESTAMP    = 'Twitch-Eventsub-Message-Timestamp'.lower()
TWITCH_MESSAGE_SIGNATURE    = 'Twitch-Eventsub-Message-Signature'.lower()
TWITCH_MESSAGE_TYPE         = 'Twitch-Eventsub-Message-Type'.lower()
HMAC_PREFIX                 = 'sha256='

global user_access_token
global refresh_token 
user_access_token = ""
refresh_token = ""

global app_access_token
app_access_token = ""

global most_recent_event
most_recent_event = ""

scheduler.api_enabled = True
scheduler.init_app(app)
scheduler.start()

global wsecret
wsecret = os.urandom(32)

# some variables
def UserData():
	#global wsecret
	return 	{"desiredScope" 	:	str(os.environ.get('DESIRED_SCOPE')), 
			"ttvChannel" 	:	str(os.environ.get('TTV_CHANNEL')).split("."), 
			"clientSecret"	:	str(os.environ.get('CLIENT_SECRET')), 
			"clientId"		:	str(os.environ.get('CLIENT_ID')), 
            # TO-DO: properly randomize and secure secret
			"webhookSecret" :	"AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz",#str(wsecret), 
			"defaultId"		:	str(os.environ.get('DEFAULT_ID'))}

MESSAGE_TYPE = {
    "notif" : "notification",
    "verif" : "webhook_callback_verification",
    "revoke" : "revocation"
}

# main page
@app.route("/", methods=["GET", "POST"])
def hello_world():
    datalist = UserData()
    
    app_access_token = GetAAToken()
    
    webhook_status = Requests.get(EVENTSUB_URL, headers={"Authorization" : "Bearer " + app_access_token, "Client-Id" : datalist["clientId"]}).json()
    
    flag = False
    for hook in webhook_status['data']:
        if hook["type"] == 'channel.channel_points_custom_reward_redemption.add':
            flag = True
        if hook['status'] == 'webhook_callback_verification_failed':
            flag = False

    if not flag:
        CreateEventSubSubscription()
    
    #wData = Requests.get("https://fdf7-104-220-49-165.ngrok-free.app/callback", headers={"ReceiveRecentEvent" : "True"})    
    
    webhook_status = Requests.get(EVENTSUB_URL, headers={"Authorization" : "Bearer " + app_access_token, "Client-Id" : datalist["clientId"]})
    
    wStatus = str(webhook_status.json())
    
    return render_template('index.html', wStatus = wStatus)

# oauth verification begin
@app.route("/ttvrequest")
def ttv_request():
    datalist = UserData()
    
    clientId= datalist["clientId"]
   
    twitch = OAuth2Session(clientId, redirect_uri="https://fdf7-104-220-49-165.ngrok-free.app/callback", scope=datalist["desiredScope"])
    
    authorization_url, state = twitch.authorization_url(AUTHORIZATION_BASE_URL)
    
    session['oauth_state'] = state
    
    return f'<a href={authorization_url}>Connect with Twitch</a>'#redirect(authorization_url)

# callback url for oauth and events
@app.route("/callback", methods=["GET", "POST"])
def authorize():
    global user_access_token
    global refresh_token
    global most_recent_event
    
    datalist = UserData()
    
    clientId = datalist["clientId"]
    clientSecret = datalist["clientSecret"]
    
    code = request.args.get('code')
    

    # receiving events
    if request.method == 'POST':
        data = request.get_data(as_text=True)
        
        message_signature = request.headers.get(TWITCH_MESSAGE_SIGNATURE)
        
        requestHead = [request.headers.get(TWITCH_MESSAGE_ID), request.headers.get(TWITCH_MESSAGE_TIMESTAMP)]
        
        # verify event is from Twitch
        ttv_verified = VerifyWebhook(data, message_signature, requestHead)
        
        if ttv_verified:
            mType = request.headers.get(TWITCH_MESSAGE_TYPE)
            rqjson = request.json
            
            if mType == MESSAGE_TYPE["verif"]:
                response_content = rqjson["challenge"]
                
            elif mType == MESSAGE_TYPE["notif"]:
                response_content = ''
                
            elif mType == MESSAGE_TYPE["revoke"]:
                # throw error on revocation
                # TO-DO: proper logging
                response_content = ''
                if rqjson["status"] == "user_removed":
                    raise Exception('**User not found or removed**')
                if rqjson["status"] == "authorization_revoked":
                    raise Exception('**Authorization revoked**')
                if rqjson["status"] == "notification_failures_exceeded":
                    raise Exception('**Notification failures exceeded**')
                if rqjson["status"] == "version_removed":
                    raise Exception('**Subscription version removed**')
            else:
                # throw error on unrecognized message type
                response_content = ''
                raise Exception('Message type not recognized')
                
            most_recent_event = data
            
            return Response(response_content, mimetype="text/plain")
        else:
            return ("AUTH FAILED", 403)
    else:
        # on GET request, create access token and refresh hourly
        # scheduler.add_job(func=MakeUAToken, trigger='interval', id="makeToken", seconds=3600, replace_existing=True, args=[code])
        # return MakeUAToken(code)
        
        # make this more secure
        return most_recent_event
        


  
# access token validation + creation calling
def MakeUAToken(code=''):
    global user_access_token
    global refresh_token
    
    # if access token exists, attempt to refresh
    if user_access_token != "":
        status = ValidateToken(user_access_token).json()
        
        # "status" is in the json if the validation failed
        if "status" in status:
            response = GetOrRefreshUAToken(refresh_token=refresh_token).json()
            
            user_access_token = response['access_token']
            refresh_token = response['refresh_token']
            
            # validate after attempting to create
            status = ValidateToken(user_access_token)
            
            # TO-DO: Proper Logging
            if "status" in status:
                raise Exception(f"access token error: {status['message']}")
            
        # if status isn't in the response it's good to go
        else:
            return user_access_token
    # create if not existing
    else: 
        response = GetOrRefreshUAToken(code=code).json()
        
        user_access_token = response['access_token']
        refresh_token = response['refresh_token']
        
        status = ValidateToken(user_access_token).json()
        
        if "status" in status:
            raise Exception(f"access token error: {status['message']}")
    
        return user_access_token

# User Access token maker
def GetOrRefreshUAToken(refresh_token='', code=''):
    datalist = UserData()
    clientId = datalist["clientId"]
    clientSecret = datalist["clientSecret"]
    
    grant_type = ("authorization_code" if code!='' else "refresh_token")
    
    return Requests.post(TOKEN_URL+"?client_id="+clientId+
                         "&client_secret="+clientSecret+
                         ("&code="+code if code!='' else "&refresh_token="+refresh_token)+
                         "&grant_type="+grant_type+
                         "&redirect_uri=https://fdf7-104-220-49-165.ngrok-free.app/callback")

# check if access token is valid
def ValidateToken(token):
    return Requests.get(VALIDATION_URL, headers={"Authorization" : "OAuth " + token})

# check if our hmac matches Twitch's, verifying that the webhook is from Twitch
def VerifyWebhook(data, hmac_header, reqHead):
    datalist = UserData()
    
    secret = datalist["webhookSecret"]
    
    message = GetHmacMessage(data, reqHead)
    
    my_hmac= GetHmac(secret, message)
    
    return hmac.compare_digest(HMAC_PREFIX + my_hmac.hexdigest(), hmac_header)

# combine Twitch data for hmac
def GetHmacMessage(data, reqHead):
    return reqHead[0] + reqHead[1] + data

# combine secret with Twitch data to make proper hmac
def GetHmac(secret, message):
    my_hmac = hmac.new(bytearray(secret, 'utf-8'), bytearray(message, 'utf-8'), digestmod=hashlib.sha256)
    return my_hmac

# create EventSub subscription
def CreateEventSubSubscription():
    global app_access_token
    
    datalist = UserData()
    
    clientId = datalist["clientId"]
    clientSecret = datalist["clientSecret"]
    
    broadcastId = datalist["defaultId"]
    
    wsecret = datalist["webhookSecret"]
    
    channelPointRedeemJson = {
        "type"      : "channel.channel_points_custom_reward_redemption.add",
        "version"   : "1",
        "condition" : {
            "broadcaster_user_id" : broadcastId
        },
        "transport" : {
            "method"   : "webhook",
            "callback" : "https://fdf7-104-220-49-165.ngrok-free.app/callback",
            "secret"   : wsecret
        }
    }
    
    return Requests.post(EVENTSUB_URL, headers={
                                                "Authorization" : "Bearer " + app_access_token,
                                                "Client-Id"     : clientId,
                                                "Content-Type"  : "application/json"
                                                    },
                        json=channelPointRedeemJson)

# App Access
def GetAAToken():
    global app_access_token
    datalist = UserData()

    clientId = datalist["clientId"]
    clientSecret = datalist["clientSecret"]
    
    grant_type = "client_credentials"
    
    response = Requests.post(TOKEN_URL+"?client_id="+clientId+
                         "&client_secret="+clientSecret+
                         "&grant_type="+grant_type).json()
    
    app_access_token = response['access_token']

    return app_access_token

if __name__ == "__main__":
    scheduler.start()
    app.run()

