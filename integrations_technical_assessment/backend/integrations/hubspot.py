# hubspot.py

from fastapi import Request
from requests_oauthlib import OAuth2Session  
import json
from urllib.parse import parse_qsl
import asyncio
import aiofiles
import base64
from integrations.integration_item import IntegrationItem
import secrets
import urllib.parse
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
import logging
import httpx

from redis_client import add_key_value_redis, get_value_redis, delete_key_redis
from dotenv import load_dotenv
import os 

load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

#enable HTTP
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# Replace with your App's Client ID and Secret
CLIENT_ID     = os.getenv('Hubspot_Client_ID')
CLIENT_SECRET = os.getenv('Hubspot_Secret_Token')
encoded_client_id_secret = base64.b64encode(f'{CLIENT_ID}:{CLIENT_SECRET}'.encode()).decode()

REDIRECT_URI = 'http://localhost:8000/integrations/hubspot/oauth2callback'
authorization_url = f'https://app.hubspot.com/oauth/authorize?client_id={CLIENT_ID}&scope=crm.objects.contacts.read&redirect_uri={REDIRECT_URI}'

# If modifying these scopes, delete the file hstoken.pickle.
SCOPES = ['crm.objects.contacts.read']

async def authorize_hubspot(user_id, org_id):
    # TODO
    state_data = {
        'state': secrets.token_urlsafe(32),
        'user_id': user_id,
        'org_id': org_id
    }
    encoded_state = json.dumps(state_data)
    await add_key_value_redis(f'hubspot_state:{org_id}:{user_id}', encoded_state, expire=600)

    return f'{authorization_url}&state={encoded_state}'
    pass


async def oauth2callback_hubspot(request: Request):
    if request.query_params.get('error'):
        raise HTTPException(status_code=400, detail=request.query_params.get('error_description'))
    
    code = request.query_params.get('code')
    encoded_state = request.query_params.get('state')

    try:
        decoded_state = urllib.parse.unquote(encoded_state)
        cleaned_state = decoded_state.rstrip('\\').rstrip('"').replace('\\"', '"')
        if not cleaned_state.endswith('}'):
            cleaned_state += '"}'
        state_data = json.loads(cleaned_state)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse state: {cleaned_state}")
        raise HTTPException(status_code=400, detail=f"Invalid state parameter: {str(e)}")

    original_state = state_data.get('state')
    user_id = state_data.get('user_id')
    org_id = state_data.get('org_id')

    if not all([original_state, user_id, org_id]):
        raise HTTPException(status_code=400, detail="Missing required state parameters")

    redis_key = f'hubspot_state:{org_id}:{user_id}'
    saved_state = await get_value_redis(redis_key)

    if saved_state:
        try:
            saved_state_data = json.loads(saved_state)
            if original_state != saved_state_data.get('state'):
                raise HTTPException(status_code=400, detail='State does not match')
        except json.JSONDecodeError:
            raise HTTPException(status_code=500, detail='Invalid saved state format')
    else:
        logger.warning(f"No saved state found for key: {redis_key}")

    try:
        async with httpx.AsyncClient() as client:
            response, _ = await asyncio.gather(
                client.post(
                    'https://api.hubapi.com/oauth/v1/token',
                    data={
                        'grant_type': 'authorization_code',
                        'client_id': CLIENT_ID,
                        'client_secret': CLIENT_SECRET,
                        'redirect_uri': REDIRECT_URI,
                        'code': code
                    },
                    headers={
                        'Content-Type': 'application/x-www-form-urlencoded',
                    }
                ),
                delete_key_redis(redis_key)
            )
        
        response.raise_for_status()
        credentials = response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"HubSpot API error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

    await add_key_value_redis(f'hubspot_credentials:{org_id}:{user_id}', json.dumps(credentials), expire=600)

    close_window_script = """
    <html>
        <script>
            window.close();
        </script>
    </html>
    """
    return HTMLResponse(content=close_window_script)

async def get_hubspot_credentials(user_id, org_id):
    credentials = await get_value_redis(f'hubspot_credentials:{org_id}:{user_id}')
    if not credentials:
        raise HTTPException(status_code=400, detail='No credentials found.')
    credentials = json.loads(credentials)
    await delete_key_redis(f'hubspot_credentials:{org_id}:{user_id}')

    return credentials

def create_integration_item_metadata_object(contact: dict) -> IntegrationItem: 
    return IntegrationItem(
        id=contact.get('vid'),
        name=f"{contact.get('properties', {}).get('firstname', {}).get('value', '')} {contact.get('properties', {}).get('lastname', {}).get('value', '')}",
        type='Contact',
        parent_id=None,
        parent_path_or_name=None,
    )   

async def get_items_hubspot(credentials) -> list[IntegrationItem]:
    credentials = json.loads(credentials)
    async with httpx.AsyncClient() as client:
        response = await client.get(
            'https://api.hubapi.com/contacts/v1/lists/all/contacts/all',
            params={'count': 100},
            headers={'Authorization': f'Bearer {credentials.get("access_token")}'}
        )

    if response.status_code == 200:
        contacts = response.json().get('contacts', [])
        list_of_integration_item_metadata = [
            create_integration_item_metadata_object(contact)
            for contact in contacts
        ]
        return list_of_integration_item_metadata
    else:
        raise HTTPException(status_code=response.status_code, detail='Failed to fetch HubSpot contacts')
