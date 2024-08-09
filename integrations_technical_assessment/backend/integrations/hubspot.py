# hubspot.py

from fastapi import Request
from dotenv import load_dotenv
from requests_oauthlib import OAuth2Session  
import os
import pickle
import json
import uuid
from urllib.parse import parse_qsl
import asyncio
import aiofiles

load_dotenv()

#enable HTTP
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'


# Replace with your App's Client ID and Secret
CLIENT_ID     = os.getenv('Hubspot_Client_ID')
CLIENT_SECRET = os.getenv('Hubspot_Secret_Token')

# If modifying these scopes, delete the file hstoken.pickle.
SCOPES = ['crm.objects.contacts.read']

user_id = str(uuid.uuid4())
org_id = str(uuid.uuid4())

async def authorize_hubspot(user_id, org_id):
    # TODO
    """
    Connects your app a Hub, then fetches the first Contact in the CRM.
    Note: If you want to change hubs or scopes, delete the `hstoken.pickle` file and rerun.
    """
    app_config = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scopes': SCOPES,
        'auth_uri': 'https://app.hubspot.com/oauth/authorize',
        'token_uri': 'https://api.hubapi.com/oauth/v1/token'
    }
    
    token_file = f'hstoken_{user_id}_{org_id}.pickle'
    # The file hstoken.pickle stores the app's access and refresh tokens for the hub you connect to.
    # It is created automatically when the authorization flow completes for the first time.
    if os.path.exists(token_file):
        with open(token_file,'rb') as tokenfile:
            token = pickle.load(tokenfile)
    # If no token file is found, let the user log in (and install the app if needed)
    else:
        oauth = OAuth2Session(
            client_id=app_config['client_id'],
            scope=app_config['scopes'],
            redirect_uri=f'http://localhost:8000/integrations/hubspot/oauth2callback'
        )
        authorization_url, _ = oauth.authorization_url(app_config['auth_uri'],state=f'user_id={user_id}&org_id={org_id}')
        return {'user_id': user_id, 'org_id': org_id, 'authorization_url': authorization_url}
    
    # Call the 'Get all contacts' API endpoint
    response = hubspot.get(
            'https://api.hubapi.com/contacts/v1/lists/all/contacts/all', 
            params={ 'count': 1 } # Return only 1 result -- for demo purposes
        )

    # Pretty-print our API result to console
    print('Here is one Contact Record from your CRM:')
    print('-----------------------------------------')
    print(json.dumps(response.json(), indent=2, sort_keys=True))

    
    #return {'user_id': user_id, 'org_id': org_id, 'authorization_url': authorization_url}
    return{'message': 'Hubspot integration successful!'}

    pass


async def oauth2callback_hubspot(request: Request):
    app_config = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'scopes': SCOPES,
        'auth_uri': 'https://app.hubspot.com/oauth/authorize',
        'token_uri': 'https://api.hubapi.com/oauth/v1/token'
    }

    oauth = OAuth2Session(
        client_id=app_config['client_id'],
        scope=app_config['scopes'],
        redirect_uri=str(request.url_for('oauth2callback_hubspot_integration'))
    )

    # Get the full URL of the current request
    full_url = str(request.url)

    try:
        # Use asyncio to run the synchronous fetch_token method
        token = await asyncio.to_thread(
            oauth.fetch_token,
            app_config['token_uri'],
            authorization_response=full_url,
            include_client_id=True,
            client_secret=app_config['client_secret'],
            verify=False  # Only for development, remove in production
        )

        # Extract user_id and org_id from the state parameter
        state = request.query_params.get('state', '')
        state_dict = dict(parse_qsl(state))
        user_id = state_dict.get('user_id')
        org_id = state_dict.get('org_id')

        if user_id and org_id:
            await SaveTokenToFile(token, user_id, org_id)
            return {'message': 'HubSpot integration successful!'}
        else:
            return {'error': 'Missing user_id or org_id in state'}

    except Exception as e:
        return {'error': f'OAuth callback error: {str(e)}'}

async def create_integration_item_metadata_object(response_json):
    contacts = response_json.get('contacts', [])
    items = []
    for contact in contacts:
        item = {
            'id': contact.get('vid'),
            'name': contact.get('properties', {}).get('firstname', {}).get('value', '') + ' ' + 
                    contact.get('properties', {}).get('lastname', {}).get('value', ''),
            'email': contact.get('properties', {}).get('email', {}).get('value', ''),
            'phone': contact.get('properties', {}).get('phone', {}).get('value', ''),
            'company': contact.get('properties', {}).get('company', {}).get('value', ''),
        }
        items.append(item)
    return items

async def get_hubspot_credentials(user_id, org_id):
    token_file = f'hstoken_{user_id}_{org_id}.json'
    try:
        async with aiofiles.open(token_file, 'r') as f:
            token_data = await f.read()
            return {'credentials': json.loads(token_data)}
    except FileNotFoundError:
        return {'error': 'Credentials not found'}


async def get_items_hubspot(credentials):
    try:
        # Parse the credentials string into a dictionary
        token = json.loads(credentials)
        
        hubspot = OAuth2Session(
            CLIENT_ID,
            token=token,
            auto_refresh_url='https://api.hubapi.com/oauth/v1/token',
            auto_refresh_kwargs={'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET},
            token_updater=lambda token: None
        )

        response = await asyncio.to_thread(
            hubspot.get,
            'https://api.hubapi.com/contacts/v1/lists/all/contacts/all',
            params={'count': 100}
        )

        if response.status_code == 200:
            items = await create_integration_item_metadata_object(response.json())
            return {'items': items}
        else:
            return {'error': f'Failed to fetch HubSpot contacts: {response.status_code}'}
    except json.JSONDecodeError:
        return {'error': 'Invalid credentials format'}
    except Exception as e:
        return {'error': f'Error fetching HubSpot contacts: {str(e)}'}


class SimpleAuthCallbackApp(object):
    """
    Used by our simple server to receive and 
    save the callback data authorization.
    """
    def __init__(self):
        self.request_uri = None
        self._success_message = (
            'All set! Your app is authorized.  ' + 
            'You can close this window now and go back where you started from.'
        )

    def __call__(self, environ, start_response):
        from wsgiref.util import request_uri
        
        start_response('200 OK', [('Content-type', 'text/plain')])
        self.request_uri = request_uri(environ)
        return [self._success_message.encode('utf-8')]



def InstallAppAndCreateToken(config, port=0):
    """
    Creates a simple local web app+server to authorize your app with a HubSpot hub.
    Returns the refresh and access token.
    """  
    from wsgiref import simple_server
    import webbrowser

    local_webapp = SimpleAuthCallbackApp()
    local_webserver = simple_server.make_server(host='localhost', port=port, app=local_webapp)

    redirect_uri = 'http://{}:{}/'.format('localhost', local_webserver.server_port)

    oauth = OAuth2Session(
        client_id=config['client_id'],
        scope=config['scopes'],
        redirect_uri=redirect_uri
    )

    auth_url, _ = oauth.authorization_url(config['auth_uri'])
    
    print('-- Authorizing your app via Browser --')
    print('If your browser does not open automatically, visit this URL:')
    print(auth_url)
    webbrowser.open(auth_url, new=1, autoraise=True)
    local_webserver.handle_request()

    # Https required by requests_oauthlib 
    auth_response = local_webapp.request_uri.replace('http','https')

    token = oauth.fetch_token(
        config['token_uri'],
        authorization_response=auth_response,
        # HubSpot requires you to include the ClientID and ClientSecret
        include_client_id=True,
        client_secret=config['client_secret']
    )
    return token

class SimpleAuthCallbackApp(object):
    """
    Used by our simple server to receive and 
    save the callback data authorization.
    """
    def __init__(self):
        self.request_uri = None
        self._success_message = (
            'All set! Your app is authorized.  ' + 
            'You can close this window now and go back where you started from.'
        )

    def __call__(self, environ, start_response):
        from wsgiref.util import request_uri
        
        start_response('200 OK', [('Content-type', 'text/plain')])
        self.request_uri = request_uri(environ)
        return [self._success_message.encode('utf-8')]



async def SaveTokenToFile(token, user_id, org_id):
    token_file = f'hstoken_{user_id}_{org_id}.json'
    async with aiofiles.open(token_file, 'w') as f:
        await f.write(json.dumps(token))

